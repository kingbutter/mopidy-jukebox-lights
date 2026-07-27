"""The lights status page.

Mounted under /jukeboxlights/ by Mopidy. Tests mount the routes the same way
so the paths under test are the paths that exist at runtime.
"""

import json
import threading
from unittest import mock

import pykka
import pytest
import tornado.web
from tornado.testing import AsyncHTTPTestCase

from mopidy_jukebox_lights import web
from mopidy_jukebox_lights.frontend import LightsFrontend

STATUS = {
    "wled_host": "172.20.25.44",
    "connected": True,
    "last_error": None,
    "mode": "playing",
    "playing": True,
    "segments": [
        {"id": 0, "name": "Bottom Left", "start": 12, "stop": 32, "len": 20},
        {"id": 1, "name": "Upper Left", "start": 42, "stop": 51, "len": 9},
    ],
    "accent_segments": [1],
    "brightness": 160,
    "idle_after": 45,
    "idle_color": [240, 168, 48],
    "follow_display": True,
    "display_flag": "/run/jukebox/display-off",
    "display_blanked": False,
    "last_rgb": [253, 13, 0],
    "last_accent": [0, 121, 255],
    "cached_artwork": 7,
}


def mounted(app_routes):
    return tornado.web.Application(
        [(f"/jukeboxlights{r[0]}", *r[1:]) for r in app_routes]
    )


class TestPage(AsyncHTTPTestCase):
    def get_app(self):
        return mounted(web.app_factory({}, mock.Mock()))

    def setUp(self):
        super().setUp()
        self._patch = mock.patch.object(web, "_status", return_value=dict(STATUS))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        super().tearDown()

    def test_root_is_a_page_not_a_404(self):
        r = self.fetch("/jukeboxlights/")
        assert r.code == 200
        assert "text/html" in r.headers["Content-Type"]

    def test_shows_current_color_and_segments(self):
        body = self.fetch("/jukeboxlights/").body.decode()
        assert "rgb(253, 13, 0)" in body
        assert "Bottom Left" in body
        assert "Upper Left" in body
        assert "172.20.25.44" in body

    def test_marks_which_segments_carry_the_accent(self):
        body = self.fetch("/jukeboxlights/").body.decode()
        # segment 1 is the accent one in STATUS
        upper = body[body.index("Upper Left"):body.index("Upper Left") + 200]
        assert "accent" in upper

    def test_status_json_round_trips(self):
        r = self.fetch("/jukeboxlights/status.json")
        assert r.code == 200
        assert json.loads(r.body)["mode"] == "playing"
        assert r.headers["Cache-Control"] == "no-store"


class TestExplanations(AsyncHTTPTestCase):
    """The 'why' line is the whole point of the page."""

    def get_app(self):
        return mounted(web.app_factory({}, mock.Mock()))

    def _body_with(self, **over):
        st = dict(STATUS)
        st.update(over)
        with mock.patch.object(web, "_status", return_value=st):
            return self.fetch("/jukeboxlights/").body.decode()

    def test_playing_explains_album_art(self):
        assert "album art" in self._body_with(mode="playing")

    def test_dark_explains_the_blanked_panel(self):
        body = self._body_with(mode="dark", playing=False, display_blanked=True)
        assert "panel is blanked" in body

    def test_idle_explains_why_it_is_not_dark(self):
        body = self._body_with(mode="idle", playing=False, display_blanked=False)
        assert "still awake" in body

    def test_idle_explains_follow_display_being_off(self):
        body = self._body_with(mode="idle", playing=False, follow_display=False)
        assert "follow_display is off" in body

    def test_unreachable_wled_says_so(self):
        body = self._body_with(connected=False, last_error="timed out")
        assert "Cannot reach WLED" in body
        assert "timed out" in body


class TestNoActor(AsyncHTTPTestCase):
    def get_app(self):
        return mounted(web.app_factory({}, mock.Mock()))

    def test_page_degrades_when_the_actor_is_absent(self):
        with mock.patch.object(web, "_status", return_value=None):
            r = self.fetch("/jukeboxlights/")
        assert r.code == 200
        assert "not running" in r.body.decode()

    def test_status_json_returns_503(self):
        with mock.patch.object(web, "_status", return_value=None):
            r = self.fetch("/jukeboxlights/status.json")
        assert r.code == 503


class TestActions(AsyncHTTPTestCase):
    def get_app(self):
        return mounted(web.app_factory({}, mock.Mock()))

    def test_test_button_reaches_the_actor(self):
        ref = mock.Mock()
        with mock.patch.object(web, "_actor", return_value=ref):
            r = self.fetch("/jukeboxlights/test", method="POST", body="",
                           follow_redirects=False)
        assert r.code in (301, 302)
        ref.proxy.return_value.run_test.assert_called_once()

    def test_rediscover_button_reaches_the_actor(self):
        ref = mock.Mock()
        with mock.patch.object(web, "_actor", return_value=ref):
            self.fetch("/jukeboxlights/rediscover", method="POST", body="",
                       follow_redirects=False)
        ref.proxy.return_value.rediscover.assert_called_once()

    def test_actions_503_without_an_actor(self):
        with mock.patch.object(web, "_actor", return_value=None):
            r = self.fetch("/jukeboxlights/test", method="POST", body="")
        assert r.code == 503


def test_get_status_talks_to_a_real_actor():
    """End to end through pykka's registry, which is how the page finds it."""
    cfg = {"jukeboxlights": {
        "enabled": True, "wled_host": "127.0.0.1:1", "brightness": 160,
        "idle_after": 45, "idle_color": "240,168,48", "accent_segments": ["1"],
        "follow_display": True, "display_flag": "/nonexistent"}}
    actor = LightsFrontend.start(cfg, mock.Mock())
    try:
        st = web._status(timeout=5)
        assert st is not None
        assert st["wled_host"] == "127.0.0.1:1"
        assert st["accent_segments"] == [1]
        assert st["display_blanked"] is False
    finally:
        pykka.ActorRegistry.stop_all(timeout=5)
