"""Frontend actor behaviour, against a stub WLED."""

import threading
import time
from unittest import mock

import pytest

from mopidy_jukebox_lights.frontend import LightsFrontend, Wled, _parse_rgb


# ── pure helpers ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("240,168,48", (240, 168, 48)),
    ("0,0,0", (0, 0, 0)),
    ("255, 255, 255", (255, 255, 255)),
    ("nonsense", (240, 168, 48)),      # falls back
    ("1,2", (240, 168, 48)),           # wrong arity
    ("300,0,0", (240, 168, 48)),       # out of range
    ("", (240, 168, 48)),
])
def test_parse_rgb(text, expected):
    assert _parse_rgb(text) == expected


# ── WLED client ───────────────────────────────────────────────────────────
def make_wled():
    w = Wled("127.0.0.1:1")
    w.effects = {"solid": 0, "breathe": 2}
    w.segs = [0, 1, 2]
    w._post = mock.Mock()
    return w


def test_solid_paints_every_segment():
    w = make_wled()
    w.solid((255, 0, 0), (0, 0, 255), set(), 160)
    payload = w._post.call_args[0][0]
    assert [s["id"] for s in payload["seg"]] == [0, 1, 2]
    assert all(s["col"][0] == [255, 0, 0] for s in payload["seg"])


def test_accent_segments_get_the_other_color():
    w = make_wled()
    w.solid((255, 0, 0), (0, 0, 255), {1}, 160)
    seg = {s["id"]: s["col"][0] for s in w._post.call_args[0][0]["seg"]}
    assert seg[0] == [255, 0, 0]
    assert seg[1] == [0, 0, 255]
    assert seg[2] == [255, 0, 0]


def test_repeated_identical_state_is_not_resent():
    # An ESP32 should not be hammered with a POST per poll.
    w = make_wled()
    w.solid((255, 0, 0), None, set(), 160)
    w.solid((255, 0, 0), None, set(), 160)
    assert w._post.call_count == 1


def test_changing_color_does_resend():
    w = make_wled()
    w.solid((255, 0, 0), None, set(), 160)
    w.solid((0, 255, 0), None, set(), 160)
    assert w._post.call_count == 2


def test_off_then_idle_are_distinct_states():
    w = make_wled()
    w.off()
    w.off()
    assert w._post.call_count == 1
    w.idle((240, 168, 48), 160)
    assert w._post.call_count == 2
    assert w._post.call_args[0][0]["on"] is True


# ── actor ─────────────────────────────────────────────────────────────────
def base_config(**over):
    cfg = {"enabled": True, "wled_host": "127.0.0.1:1", "brightness": 160,
           "idle_after": 1, "idle_color": "240,168,48", "accent_segments": [],
           "follow_display": True, "display_flag": "/nonexistent"}
    cfg.update(over)
    return {"jukeboxlights": cfg}


def test_shutdown_event_does_not_shadow_pykka():
    # pykka.ThreadingActor already defines _stop(); naming our Event self._stop
    # breaks actor shutdown with "'Event' object is not callable".
    actor = LightsFrontend(base_config(), mock.Mock())
    assert isinstance(actor._shutdown, threading.Event)
    assert callable(getattr(actor, "_stop", None))


def test_accent_segments_parsed_from_config():
    actor = LightsFrontend(base_config(accent_segments=["1", "3", "x"]), mock.Mock())
    assert actor.accent_segs == {1, 3}


def test_playback_events_track_state():
    actor = LightsFrontend(base_config(), mock.Mock())
    tl = mock.Mock()
    tl.track = mock.Mock(uri="spotify:track:1")

    actor.track_playback_started(tl)
    assert actor._playing is True
    assert actor._q.get_nowait() == ("track", "spotify:track:1")

    actor.playback_state_changed("playing", "stopped")
    assert actor._playing is False


def test_ticker_picks_off_when_the_panel_flag_exists(tmp_path):
    flag = tmp_path / "display-off"
    flag.write_text("")
    actor = LightsFrontend(
        base_config(display_flag=str(flag), idle_after=0), mock.Mock())
    actor._playing = False
    actor._stopped_at = time.time() - 5
    t = threading.Thread(target=actor._run_ticker, daemon=True)
    t.start()
    kind, _ = actor._q.get(timeout=5)
    actor._shutdown.set()
    assert kind == "off"


def test_ticker_picks_idle_when_the_panel_is_awake(tmp_path):
    actor = LightsFrontend(
        base_config(display_flag=str(tmp_path / "absent"), idle_after=0),
        mock.Mock())
    actor._playing = False
    actor._stopped_at = time.time() - 5
    t = threading.Thread(target=actor._run_ticker, daemon=True)
    t.start()
    kind, _ = actor._q.get(timeout=5)
    actor._shutdown.set()
    assert kind == "idle"


def test_ticker_stays_quiet_while_playing(tmp_path):
    import queue
    actor = LightsFrontend(base_config(idle_after=0), mock.Mock())
    actor._playing = True
    t = threading.Thread(target=actor._run_ticker, daemon=True)
    t.start()
    with pytest.raises(queue.Empty):
        actor._q.get(timeout=3)
    actor._shutdown.set()
