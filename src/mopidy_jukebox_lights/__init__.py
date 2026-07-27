"""Mopidy-JukeboxLights -- drive WLED from whatever Mopidy is playing.

As a Mopidy frontend rather than a polling daemon, this reacts to
track_playback_started the instant it fires instead of noticing up to a poll
interval later, and it gets the track model handed to it directly rather than
asking for it over JSON-RPC.
"""

import pathlib
from importlib.metadata import PackageNotFoundError, version

from mopidy import config, ext

# Single source of truth: the git tag becomes the package version via
# setuptools-scm, and Mopidy requires Extension.version to match what is on
# PyPI. Reading it back from the installed metadata keeps them in step.
try:
    __version__ = version("Mopidy-JukeboxLights")
except PackageNotFoundError:  # running from a source tree
    __version__ = "0.0.0"


class Extension(ext.Extension):
    dist_name = "Mopidy-JukeboxLights"
    ext_name = "jukeboxlights"
    version = __version__

    def get_default_config(self):
        # Read the file directly rather than via config.read(): the helper has
        # moved between Mopidy versions, and this only needs to return text.
        return (pathlib.Path(__file__).parent / "ext.conf").read_text()

    def get_config_schema(self):
        schema = super().get_config_schema()
        schema["wled_host"] = config.String()
        schema["brightness"] = config.Integer(minimum=1, maximum=255)
        schema["idle_after"] = config.Integer(minimum=1)
        schema["idle_color"] = config.String()
        schema["accent_segments"] = config.List(optional=True)
        schema["follow_display"] = config.Boolean()
        schema["display_flag"] = config.String()
        return schema

    def setup(self, registry):
        from .frontend import LightsFrontend
        from .web import app_factory

        registry.add("frontend", LightsFrontend)
        # A status page, so "why is the cabinet amber?" is answerable without
        # reading the journal -- and so the color test the standalone daemon
        # had as --test is still reachable.
        registry.add("http:app", {"name": self.ext_name, "factory": app_factory})
