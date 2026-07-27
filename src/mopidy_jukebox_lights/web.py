"""Status page for the lights.

The frontend actor has no UI of its own, which makes "why is the cabinet
amber?" a journal-reading exercise. This answers it at a glance: whether WLED
is reachable, which segments were discovered, what state the lights are in and
why, and what color is currently showing.

It also carries a test button, which the standalone daemon had as a --test
flag and the extension otherwise loses.

Routes (mounted by Mopidy under /jukeboxlights/):
    /                 status page
    /status.json      the same, as JSON
    /test             POST: cycle red/green/blue/amber
    /rediscover       POST: re-read effects and segments from WLED
"""

import json

import tornado.web
from pykka import ActorRegistry

from .frontend import LightsFrontend


def _actor():
    refs = ActorRegistry.get_by_class(LightsFrontend)
    return refs[0] if refs else None


def _status(timeout=3):
    ref = _actor()
    if ref is None:
        return None
    try:
        return ref.proxy().get_status().get(timeout=timeout)
    except Exception:
        return None


_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jukebox lights</title>
<style>
  :root{{--night:#150e10;--night2:#1f1519;--night3:#2a1d22;--amber:#f0a830;
        --amber2:#ffd166;--paper:#f2e8d5;--chrome:#8a9199;--chrome2:#565d63;
        --good:#7fd18f;--bad:#e07a5f}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--night);color:var(--paper);min-height:100vh;padding:6vh 5vw;
       font:16px/1.6 "Liberation Sans Narrow","DejaVu Sans Condensed",
       "Arial Narrow",system-ui,sans-serif}}
  .wrap{{max-width:660px;margin:0 auto}}
  h1{{font-size:clamp(22px,4vw,34px);letter-spacing:.2em;text-transform:uppercase;
     color:var(--amber);font-weight:700;margin-bottom:.15em}}
  .sub{{color:var(--chrome);letter-spacing:.14em;text-transform:uppercase;
       font-size:13px;margin-bottom:2em}}
  .state{{display:flex;align-items:center;gap:14px;background:var(--night2);
         border-left:4px solid {accent};padding:16px 20px;margin-bottom:.6em}}
  .swatch{{width:42px;height:42px;flex:none;border:1px solid #0a0507;
          background:{swatch}}}
  .state b{{display:block;font-size:19px;letter-spacing:.1em;text-transform:uppercase;
           color:{accent}}}
  .state span{{color:var(--chrome);font-size:14px}}
  .why{{color:var(--chrome2);font-size:13px;margin-bottom:2em}}
  h2{{font-size:12px;letter-spacing:.3em;text-transform:uppercase;
     color:var(--chrome2);margin:2em 0 .7em}}
  table{{width:100%;border-collapse:collapse;
        font-family:"DejaVu Sans Mono","Liberation Mono",monospace;font-size:14px}}
  td{{padding:8px 12px;border-bottom:1px solid var(--night3)}}
  td:first-child{{color:var(--chrome)}}
  td:last-child{{text-align:right;color:var(--amber2)}}
  .ok{{color:var(--good)}} .no{{color:var(--bad)}}
  form{{display:inline}}
  button{{background:var(--night3);border:1px solid var(--amber);color:var(--amber);
         padding:13px 24px;font:inherit;font-weight:700;letter-spacing:.14em;
         text-transform:uppercase;margin:0 8px 8px 0}}
  button:active{{background:var(--amber);color:#2b2118}}
  code{{background:var(--night2);padding:2px 7px}}
  p{{color:var(--chrome);font-size:14px}}
  a{{color:var(--amber)}}
</style>
</head>
<body><div class="wrap">
  <h1>Cabinet lights</h1>
  <div class="sub">Mopidy-JukeboxLights &middot; {host}</div>

  <div class="state">
    <div class="swatch"></div>
    <div><b>{mode_label}</b><span>{color_label}</span></div>
  </div>
  <div class="why">{why}</div>

  <h2>Segments discovered</h2>
  <table>{segments}</table>

  <h2>Settings</h2>
  <table>{settings}</table>

  <h2>Actions</h2>
  <form method="post" action="test"><button>Test colors</button></form>
  <form method="post" action="rediscover"><button>Re-read segments</button></form>
  <p style="margin-top:1.4em">Change these in the <code>[jukeboxlights]</code>
     section of <code>mopidy.conf</code>, then restart Mopidy.
     Raw values: <a href="status.json">status.json</a></p>
</div></body>
</html>
"""

_OFFLINE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Jukebox lights</title>
<style>body{{background:#150e10;color:#f2e8d5;font:16px/1.6 system-ui;
padding:8vh 6vw}}h1{{color:#e07a5f;letter-spacing:.2em;text-transform:uppercase}}
code{{background:#1f1519;padding:2px 7px}}p{{color:#8a9199;max-width:52ch}}</style>
</head><body><h1>Lights frontend not running</h1>
<p>The extension is installed but its actor is not answering. Check that
<code>[jukeboxlights]</code> has <code>enabled = true</code> in
<code>mopidy.conf</code>, then look at
<code>journalctl -u mopidy</code> for a startup error.</p></body></html>
"""

_MODES = {
    "playing": ("#ffd166", "Following the music"),
    "idle": ("#f0a830", "Idle &mdash; breathing amber"),
    "dark": ("#565d63", "Dark"),
    "unknown": ("#8a9199", "No state yet"),
}


def _why(st):
    if not st["connected"]:
        return f"Cannot reach WLED at {st['wled_host']}. {st['last_error'] or ''}"
    if st["mode"] == "playing":
        return "A track is playing, so the color comes from its album art."
    if st["mode"] == "dark":
        return ("Nothing is playing and the kiosk panel is blanked, so the "
                "tubes are off. They come back on touch or on playback.")
    if st["mode"] == "idle":
        if st["follow_display"] and not st["display_blanked"]:
            return ("Nothing is playing. The panel is still awake, so the "
                    "tubes breathe rather than going dark.")
        if not st["follow_display"]:
            return ("Nothing is playing. follow_display is off, so the tubes "
                    "breathe instead of going dark.")
        return "Nothing is playing."
    return "Waiting for the first track."


def _rows(pairs):
    return "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in pairs)


class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        st = _status()
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        if st is None:
            self.write(_OFFLINE)
            return

        accent, label = _MODES.get(st["mode"], _MODES["unknown"])
        rgb = st["last_rgb"]
        swatch = f"rgb({rgb[0]},{rgb[1]},{rgb[2]})" if rgb else "#2a1d22"
        color_label = (
            f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
            + (f" &middot; accent rgb({st['last_accent'][0]}, "
               f"{st['last_accent'][1]}, {st['last_accent'][2]})"
               if st["last_accent"] else "")
        ) if rgb else "&mdash;"

        if st["segments"]:
            segs = _rows([
                (f"{s['name']}", f"LEDs {s['start']}&ndash;{s['stop'] - 1} "
                                 f"({s['len']})"
                                 + (" &middot; accent"
                                    if s["id"] in st["accent_segments"] else ""))
                for s in st["segments"]
            ])
        else:
            segs = ("<tr><td>none discovered</td><td>defaulting to segment 0"
                    "</td></tr>")

        settings = _rows([
            ("WLED", f"<span class='{'ok' if st['connected'] else 'no'}'>"
                     f"{st['wled_host']} "
                     f"{'reachable' if st['connected'] else 'unreachable'}</span>"),
            ("Brightness", st["brightness"]),
            ("Idle after", f"{st['idle_after']} s"),
            ("Accent segments", ", ".join(map(str, st["accent_segments"])) or "none"),
            ("Follow display", "yes" if st["follow_display"] else "no"),
            ("Panel blanked", "yes" if st["display_blanked"] else "no"),
            ("Artwork cached", st["cached_artwork"]),
        ])

        self.write(_PAGE.format(
            host=st["wled_host"], accent=accent, swatch=swatch,
            mode_label=label, color_label=color_label,
            why=_why(st), segments=segs, settings=settings,
        ))


class StatusHandler(tornado.web.RequestHandler):
    def get(self):
        st = _status()
        self.set_header("Content-Type", "application/json")
        self.set_header("Cache-Control", "no-store")
        if st is None:
            self.set_status(503)
            self.write(json.dumps({"error": "lights frontend not running"}))
            return
        self.write(json.dumps(st))


class ActionHandler(tornado.web.RequestHandler):
    def initialize(self, action):
        self.action = action

    def post(self):
        ref = _actor()
        if ref is None:
            self.set_status(503)
            self.write("lights frontend not running")
            return
        getattr(ref.proxy(), self.action)()
        self.redirect("./")

    def get(self):
        # Someone following the link by hand rather than pressing the button.
        self.redirect("./")


def app_factory(config, core):
    return [
        (r"/", IndexHandler),
        (r"/status.json", StatusHandler),
        (r"/test", ActionHandler, {"action": "run_test"}),
        (r"/rediscover", ActionHandler, {"action": "rediscover"}),
    ]
