import configparser
from unittest import mock

import mopidy_jukebox_lights


def test_get_default_config():
    cfg = mopidy_jukebox_lights.Extension().get_default_config()
    assert "[jukeboxlights]" in cfg
    assert "enabled = true" in cfg
    assert "wled_host" in cfg


def test_get_config_schema():
    schema = mopidy_jukebox_lights.Extension().get_config_schema()
    for key in ("wled_host", "brightness", "idle_after", "idle_color",
                "accent_segments", "follow_display", "display_flag"):
        assert key in schema


def test_defaults_satisfy_schema():
    ext = mopidy_jukebox_lights.Extension()
    parser = configparser.RawConfigParser()
    parser.read_string(ext.get_default_config())
    values, errors = ext.get_config_schema().deserialize(
        dict(parser["jukeboxlights"]))
    assert errors == {}
    assert 1 <= values["brightness"] <= 255


def test_setup_registers_frontend_and_status_page():
    from mopidy_jukebox_lights.frontend import LightsFrontend
    registry = mock.Mock()
    mopidy_jukebox_lights.Extension().setup(registry)
    calls = {c[0][0]: c[0][1] for c in registry.add.call_args_list}
    assert calls["frontend"] is LightsFrontend
    assert calls["http:app"]["name"] == "jukeboxlights"
    assert callable(calls["http:app"]["factory"])
