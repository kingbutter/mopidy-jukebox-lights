"""Pykka frontend actor that keeps WLED in step with playback."""

import json
import logging
import os
import queue
import threading
import time
import urllib.request

import pykka
from mopidy.core import CoreListener

from .color import pick_palette

logger = logging.getLogger(__name__)


# Named colors for the idle effect. Warm tones read best through a diffuser;
# the cool ones are here because some cabinets suit them.
NAMED_COLORS = {
    "amber": (240, 168, 48),
    "warm-white": (255, 197, 143),
    "candle": (255, 147, 41),
    "gold": (255, 215, 0),
    "red": (220, 20, 20),
    "oxblood": (140, 30, 45),
    "pink": (255, 60, 140),
    "purple": (150, 40, 210),
    "blue": (30, 90, 255),
    "cyan": (0, 200, 220),
    "teal": (0, 190, 160),
    "green": (30, 210, 60),
    "lime": (160, 240, 40),
    "white": (255, 255, 255),
    "off": (0, 0, 0),
}


def _parse_rgb(text, fallback=(240, 168, 48)):
    """Accept a name, a hex string, or r,g,b -- people should not have to
    look up that amber is 240,168,48."""
    if text is None:
        return fallback
    raw = str(text).strip().lower()
    if not raw:
        return fallback

    if raw in NAMED_COLORS:
        return NAMED_COLORS[raw]

    hexish = raw.lstrip("#")
    if len(hexish) in (3, 6) and all(c in "0123456789abcdef" for c in hexish):
        if len(hexish) == 3:
            hexish = "".join(c * 2 for c in hexish)
        return tuple(int(hexish[i:i + 2], 16) for i in (0, 2, 4))

    try:
        parts = [int(p) for p in raw.replace(" ", "").split(",")]
        if len(parts) == 3 and all(0 <= p <= 255 for p in parts):
            return tuple(parts)
    except (ValueError, TypeError):
        pass
    return fallback


class Wled:
    """Thin WLED client. All calls happen on the worker thread."""

    def __init__(self, host):
        self.host = host
        self.effects = {}
        self.segs = [0]
        self.seg_info = []
        self.last = None
        # Kept for the status page: "what is it showing right now" is the
        # first question when the cabinet looks wrong.
        self.connected = False
        self.last_error = None
        self.mode = "unknown"
        self.last_rgb = None
        self.last_accent = None

    def _get(self, path, timeout=4):
        with urllib.request.urlopen(f"http://{self.host}/{path}", timeout=timeout) as r:
            return json.load(r)

    def _post(self, payload, timeout=4):
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://{self.host}/json/state",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def discover(self):
        """Effect ids are indices into /json/eff and move between WLED
        releases, so look them up. Segments are read rather than assumed so
        re-running the layout tool needs no config change here."""
        try:
            names = self._get("json/eff")
            self.effects = {n.lower(): i for i, n in enumerate(names)}
        except Exception as e:
            logger.warning("JukeboxLights: could not read effects: %s", e)
        try:
            state = self._get("json/state")
            segs = [
                s
                for s in state.get("seg", [])
                if s.get("stop", 0) > s.get("start", 0)
            ]
            self.segs = [s.get("id", i) for i, s in enumerate(segs)] or [0]
            self.seg_info = [
                {
                    "id": s.get("id", i),
                    "name": s.get("n") or f"segment {s.get('id', i)}",
                    "start": s.get("start", 0),
                    "stop": s.get("stop", 0),
                    "len": s.get("stop", 0) - s.get("start", 0),
                }
                for i, s in enumerate(segs)
            ]
            self.connected = True
            self.last_error = None
            logger.info(
                "JukeboxLights: %d segment(s) on %s", len(self.segs), self.host
            )
        except Exception as e:
            logger.warning("JukeboxLights: could not read segments: %s", e)
            self.segs = [0]
            self.connected = False
            self.last_error = str(e)

    def fx(self, name, default=0):
        return self.effects.get(name.lower(), default)

    def solid(self, rgb, accent, accent_segs, brightness):
        key = ("solid", rgb, accent, tuple(sorted(accent_segs)), brightness)
        if self.last == key:
            return
        accent = accent or rgb
        segs = []
        for i in self.segs:
            main = accent if i in accent_segs else rgb
            other = rgb if i in accent_segs else accent
            segs.append(
                {
                    "id": i,
                    "fx": self.fx("solid", 0),
                    "sx": 128,
                    "ix": 128,
                    "col": [list(main), list(other), [0, 0, 0]],
                }
            )
        self._post({"on": True, "bri": brightness, "transition": 12, "seg": segs})
        self.last = key
        self.mode = "playing"
        self.last_rgb, self.last_accent = rgb, accent
        self.connected = True
        logger.debug("JukeboxLights: color %s accent %s", rgb, accent)

    def idle(self, rgb, brightness):
        key = ("idle", rgb, brightness)
        if self.last == key:
            return
        self._post(
            {
                "on": True,
                "bri": max(40, brightness // 3),
                "transition": 20,
                "seg": [
                    {
                        "id": i,
                        "fx": self.fx("breathe", 2),
                        "sx": 40,
                        "col": [list(rgb), [0, 0, 0], [0, 0, 0]],
                    }
                    for i in self.segs
                ],
            }
        )
        self.last = key
        self.mode = "idle"
        self.last_rgb, self.last_accent = rgb, None
        self.connected = True
        logger.debug("JukeboxLights: idle breathe")

    def off(self):
        if self.last == ("off",):
            return
        self._post({"on": False, "transition": 30})
        self.last = ("off",)
        self.mode = "dark"
        self.connected = True
        logger.debug("JukeboxLights: dark")


class LightsFrontend(pykka.ThreadingActor, CoreListener):
    def __init__(self, config, core):
        super().__init__()
        self.core = core
        cfg = config["jukeboxlights"]
        self.wled = Wled(cfg["wled_host"])
        self.brightness = cfg["brightness"]
        self.idle_after = cfg["idle_after"]
        self.idle_rgb = _parse_rgb(cfg["idle_color"])
        self.accent_segs = {
            int(x) for x in (cfg["accent_segments"] or []) if str(x).strip().isdigit()
        }
        self.follow_display = cfg["follow_display"]
        self.display_flag = cfg["display_flag"]

        self._art = {}
        self._playing = False
        self._stopped_at = time.time()
        self._q = queue.Queue()
        # NOT self._stop: pykka.ThreadingActor already has a _stop() method and
        # shadowing it with an Event breaks actor shutdown.
        self._shutdown = threading.Event()
        self._worker = None
        self._ticker = None

    # ── actor lifecycle ──────────────────────────────────────────────────
    def on_start(self):
        # Network work happens off the actor thread: an artwork fetch can take
        # seconds, and blocking here would stall every other Mopidy event.
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self._ticker = threading.Thread(target=self._run_ticker, daemon=True)
        self._ticker.start()
        self._q.put(("discover", None))

    def on_stop(self):
        self._shutdown.set()
        self._q.put(("quit", None))

    # ── Mopidy events ────────────────────────────────────────────────────
    def track_playback_started(self, tl_track):
        self._playing = True
        track = getattr(tl_track, "track", None)
        if track is not None:
            self._q.put(("track", track.uri))

    def track_playback_resumed(self, tl_track, time_position):
        self._playing = True
        track = getattr(tl_track, "track", None)
        if track is not None:
            self._q.put(("track", track.uri))

    def playback_state_changed(self, old_state, new_state):
        self._playing = new_state == "playing"
        if not self._playing:
            self._stopped_at = time.time()

    def track_playback_ended(self, tl_track, time_position):
        self._stopped_at = time.time()

    # ── queried by the HTTP status page ──────────────────────────────────
    def get_status(self):
        """Everything the status page needs, gathered on the actor thread so
        it is a consistent snapshot rather than a torn read."""
        flag_present = os.path.exists(self.display_flag)
        return {
            "wled_host": self.wled.host,
            "connected": self.wled.connected,
            "last_error": self.wled.last_error,
            "mode": self.wled.mode,
            "playing": self._playing,
            "segments": self.wled.seg_info,
            "accent_segments": sorted(self.accent_segs),
            "brightness": self.brightness,
            "idle_after": self.idle_after,
            "idle_color": list(self.idle_rgb),
            "follow_display": self.follow_display,
            "display_flag": self.display_flag,
            "display_blanked": flag_present,
            "last_rgb": list(self.wled.last_rgb) if self.wled.last_rgb else None,
            "last_accent": list(self.wled.last_accent) if self.wled.last_accent else None,
            "cached_artwork": len(self._art),
        }

    def set_idle_color(self, value):
        """Change the idle color now. Not persisted -- mopidy.conf remains the
        source of truth across restarts, and the status page says so."""
        rgb = _parse_rgb(value, self.idle_rgb)
        self.idle_rgb = rgb
        self.wled.last = None          # force a repaint on the next tick
        if not self._playing:
            self._q.put(("idle", None))
        return list(rgb)

    def run_test(self):
        """Cycle a few colors so wiring can be checked without music."""
        self._q.put(("test", None))
        return True

    def rediscover(self):
        self._q.put(("discover", None))
        return True

    # ── worker ───────────────────────────────────────────────────────────
    def _run_worker(self):
        while not self._shutdown.is_set():
            try:
                kind, arg = self._q.get(timeout=1)
            except queue.Empty:
                continue
            if kind == "quit":
                return
            try:
                if kind == "discover":
                    self.wled.discover()
                elif kind == "track":
                    self._paint(arg)
                elif kind == "idle":
                    self.wled.idle(self.idle_rgb, self.brightness)
                elif kind == "off":
                    self.wled.off()
                elif kind == "test":
                    for rgb, acc in (
                        ((255, 0, 0), (0, 90, 255)),
                        ((0, 255, 0), (255, 0, 160)),
                        ((0, 0, 255), (255, 170, 0)),
                        (self.idle_rgb, (0, 160, 255)),
                    ):
                        self.wled.solid(rgb, acc, self.accent_segs, self.brightness)
                        time.sleep(1.2)
                    self.wled.last = None      # let normal painting resume
            except Exception as e:
                logger.warning("JukeboxLights: %s failed: %s", kind, e)

    def _paint(self, uri):
        pal = self._art.get(uri)
        if pal is None:
            pal = (self.idle_rgb, self.idle_rgb)
            try:
                images = self.core.library.get_images([uri]).get() or {}
                imgs = images.get(uri) or []
                if imgs:
                    best = sorted(
                        imgs, key=lambda i: getattr(i, "width", 0) or 0, reverse=True
                    )[0]
                    url = best.uri
                    with urllib.request.urlopen(url, timeout=6) as r:
                        pal = pick_palette(r.read())
                else:
                    logger.debug("JukeboxLights: no artwork for %s", uri)
            except Exception as e:
                logger.debug("JukeboxLights: artwork failed for %s: %s", uri, e)
            self._art[uri] = pal
            if len(self._art) > 300:
                self._art.clear()
        self.wled.solid(pal[0], pal[1], self.accent_segs, self.brightness)

    # ── idle / deep sleep ────────────────────────────────────────────────
    def _run_ticker(self):
        """Playback is event-driven, but 'nothing has happened for a while'
        needs a clock. Cheap: one wakeup every two seconds, no network unless
        the desired state actually changes."""
        while not self._shutdown.wait(2):
            if self._playing:
                continue
            if time.time() - self._stopped_at < self.idle_after:
                continue
            dark = self.follow_display and os.path.exists(self.display_flag)
            self._q.put(("off" if dark else "idle", None))
