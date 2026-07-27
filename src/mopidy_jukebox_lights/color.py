"""Album-art color extraction.

Averaging a sleeve gives brown every time. Instead: bucket the pixels
coarsely, discard anything too dark or too desaturated to register as light,
and score the rest by pixel count weighted by saturation. The accent is the
strongest remaining bucket whose hue is meaningfully different, so a
two-color cabinet reads as two colors rather than two shades of one.
"""

import colorsys
import io

from PIL import Image


def _boost(rgb, sat=1.35, val=1.15, floor=0.55):
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    s = min(1.0, s * sat + 0.10)      # LEDs need more saturation than screens
    v = max(floor, min(1.0, v * val))
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (round(r * 255), round(g * 255), round(b * 255))


def pick_palette(data):
    """
    Return (dominant, accent). The accent is the strongest bucket whose hue is
    meaningfully different from the dominant, so a two-color cabinet reads as
    two colors rather than two shades of the same one. Falls back to the
    dominant when the sleeve genuinely only has one hue.
    """
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((96, 96))

    raw = im.tobytes()
    buckets = {}
    for i in range(0, len(raw) - 2, 3):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if v < 0.20 or s < 0.18:
            continue
        key = (r >> 4, g >> 4, b >> 4)
        acc = buckets.setdefault(key, [0, 0.0, 0, 0, 0, 0.0])
        acc[0] += 1
        acc[1] += s
        acc[2] += r
        acc[3] += g
        acc[4] += b
        acc[5] += h

    if not buckets:
        im2 = im.resize((1, 1))
        r, g, b = im2.getpixel((0, 0))
        v = max(r, g, b) / 255
        lvl = int(80 + 120 * v)
        warm = (lvl, int(lvl * 0.72), int(lvl * 0.34))
        return warm, warm

    def score(item):
        count, ssum = item[1][0], item[1][1]
        return count * (ssum / count) ** 1.5

    ranked = sorted(buckets.items(), key=score, reverse=True)

    def rgb_of(entry):
        count, _s, rs, gs, bs, _h = entry
        return (rs / count, gs / count, bs / count)

    dom_raw = rgb_of(ranked[0][1])
    dom_h = colorsys.rgb_to_hsv(*[c / 255 for c in dom_raw])[0]

    accent_raw = None
    for _key, entry in ranked[1:]:
        h = colorsys.rgb_to_hsv(*[c / 255 for c in rgb_of(entry)])[0]
        d = abs(h - dom_h)
        d = min(d, 1 - d)               # hue is circular
        if d > 0.08:                    # ~29 degrees apart
            accent_raw = rgb_of(entry)
            break

    dom = _boost(dom_raw)
    accent = _boost(accent_raw) if accent_raw else dom
    return dom, accent


