"""Color extraction.

Averaging a sleeve gives brown every time, so the interesting cases are the
ones where the dominant color is a small part of the image, and where there
is no usable hue at all.
"""

import colorsys
import io

import pytest
from PIL import Image, ImageDraw

from mopidy_jukebox_lights.color import pick_palette


def sleeve(draw_fn, size=300):
    im = Image.new("RGB", (size, size), (20, 20, 22))
    draw_fn(ImageDraw.Draw(im))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def hue_degrees(rgb):
    h, _s, _v = colorsys.rgb_to_hsv(*[c / 255 for c in rgb])
    return h * 360


def saturation(rgb):
    return colorsys.rgb_to_hsv(*[c / 255 for c in rgb])[1]


@pytest.mark.parametrize("fill,low,high", [
    ((200, 30, 30), 340, 20),    # red wraps past 360
    ((30, 200, 60), 90, 160),    # green
    ((30, 60, 220), 200, 260),   # blue
    ((240, 215, 40), 45, 70),    # yellow
])
def test_dominant_hue_matches_the_sleeve(fill, low, high):
    dom, _ = pick_palette(sleeve(lambda d: d.rectangle([0, 0, 300, 300], fill=fill)))
    deg = hue_degrees(dom)
    if low > high:              # wrapped range
        assert deg >= low or deg <= high
    else:
        assert low <= deg <= high


def test_small_bright_area_beats_a_dark_background():
    # A tiny orange square on near-black must win; averaging would give mud.
    data = sleeve(lambda d: (d.rectangle([0, 0, 300, 300], fill=(8, 8, 10)),
                             d.rectangle([140, 140, 160, 160], fill=(255, 120, 10))))
    dom, _ = pick_palette(data)
    assert 15 <= hue_degrees(dom) <= 45


def test_two_tone_sleeve_yields_two_distinct_hues():
    data = sleeve(lambda d: (d.rectangle([0, 0, 300, 150], fill=(220, 40, 30)),
                             d.rectangle([0, 150, 300, 300], fill=(20, 120, 230))))
    dom, accent = pick_palette(data)
    gap = abs(hue_degrees(dom) - hue_degrees(accent))
    assert min(gap, 360 - gap) > 29


def test_single_hue_sleeve_returns_the_same_color_twice():
    data = sleeve(lambda d: d.rectangle([0, 0, 300, 300], fill=(180, 25, 25)))
    dom, accent = pick_palette(data)
    assert dom == accent


def test_monochrome_falls_back_to_warm_white_not_grey():
    data = sleeve(lambda d: [d.rectangle([0, y, 300, y + 8], fill=(y % 210,) * 3)
                             for y in range(0, 300, 8)])
    dom, accent = pick_palette(data)
    assert dom == accent
    # Warm, not neutral: a grey strip reads as "broken" rather than "playing".
    assert dom[0] > dom[2]


def test_output_is_always_saturated_enough_to_read_as_color():
    data = sleeve(lambda d: d.rectangle([0, 0, 300, 300], fill=(150, 120, 110)))
    dom, _ = pick_palette(data)
    assert saturation(dom) > 0.15
    assert all(0 <= c <= 255 for c in dom)
