# Mopidy-JukeboxLights

[![PyPI](https://img.shields.io/pypi/v/Mopidy-JukeboxLights)](https://pypi.org/project/Mopidy-JukeboxLights/)
[![CI](https://github.com/kingbutter/mopidy-jukebox-lights/actions/workflows/ci.yml/badge.svg)](https://github.com/kingbutter/mopidy-jukebox-lights/actions)

A [Mopidy](https://mopidy.com/) extension that drives
[WLED](https://kno.wled.ge/) LED strips with colors pulled from the album art
of whatever is playing.

## What it does

- **Color from the sleeve.** Averaging album art gives brown every time.
  Instead this buckets pixels, discards anything too dark or too washed out to
  register as light, and scores the rest by pixel count weighted by
  saturation — so a small bright detail on a black sleeve still wins.
- **Two-color cabinets.** Picks an accent from the strongest hue at least
  ~29° away from the dominant, and paints nominated segments with it. A
  red-and-blue sleeve lights red and blue, not two shades of purple.
- **Event driven.** A Mopidy frontend actor listening for
  `track_playback_started`, so the lights change the instant the track does.
  Network calls run on a worker thread and never block Mopidy's event loop.
- **Idle and dark states.** Breathes amber when nothing is playing, and goes
  fully dark when a kiosk panel blanks — see `follow_display` below.

## Status page

Once running, `http://<your-host>:6680/jukeboxlights/` shows what the lights
are doing and, more usefully, *why* — whether WLED is reachable, which
segments were discovered, and whether the strip is following music, breathing
amber, or dark because the kiosk panel blanked. It also has a button to cycle
red/green/blue/amber for checking wiring without needing to play anything.

## Installation

```sh
python3 -m pip install Mopidy-JukeboxLights
```

## Configuration

```ini
[jukeboxlights]
enabled = true
wled_host = 172.20.25.44       # IP or host:port of your WLED device
brightness = 160               # 1-255
idle_after = 45                # seconds of silence before the idle effect
idle_color = 240,168,48        # amber
accent_segments = 1,2,3        # segment ids that get the accent color
follow_display = true
display_flag = /run/jukebox/display-off
```

Segments are read from WLED at startup, so a strip run in one uncut piece with
hidden stretches behind a door frame works without any config here — define
the visible runs as WLED segments and this follows them.

### Turning the lights off with the screen

If something else on the machine creates the file named by `display_flag` when
a kiosk display blanks, the strip goes fully dark rather than breathing — but
only while nothing is playing. Remove the file and it comes back. Set
`follow_display = false` to ignore this entirely.

## Project resources

- [Source code](https://github.com/kingbutter/mopidy-jukebox-lights)
- [Issue tracker](https://github.com/kingbutter/mopidy-jukebox-lights/issues)

## Credits

- Original author: [King Butter](https://github.com/kingbutter)
- Current maintainer: [King Butter](https://github.com/kingbutter)
x
