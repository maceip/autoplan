"""Render the layout spec to PNG with PIL — used to verify exactly what the deck contains."""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

from spec import (W, H, F_DISPLAY, F_MONO, F_SANS, WHITE)

FONT_FILES = {
    (F_DISPLAY, False): os.path.expanduser("~/Library/Fonts/Halvar-Breitschrift-ExtraBold-Demo.ttf"),
    (F_MONO, False): os.path.expanduser("~/Library/Fonts/IBMPlexMono-Regular.otf"),
    (F_MONO, True): os.path.expanduser("~/Library/Fonts/IBMPlexMono-SemiBold.otf"),
    (F_SANS, False): "/System/Library/Fonts/HelveticaNeue.ttc",
    (F_SANS, True): "/System/Library/Fonts/HelveticaNeue.ttc",
}
_CACHE: dict = {}


def _font(name, size, bold=False):
    key = (name, size, bold)
    if key in _CACHE:
        return _CACHE[key]
    path = FONT_FILES.get((name, bold)) or FONT_FILES[(name, False)]
    idx = 0
    if name == F_SANS:
        idx = 1 if bold else 0
    f = ImageFont.truetype(path, size=max(1, int(round(size))), index=idx)
    _CACHE[key] = f
    return f


def _hx(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(fg, alpha, bg=(0, 0, 0)):
    return tuple(int(fg[i] * alpha + bg[i] * (1 - alpha)) for i in range(3))


def _wrap(draw, s, font, maxw, track):
    out = []
    for para in s.split("\n"):
        if not para:
            out.append("")
            continue
        words, line = para.split(" "), ""
        for wd in words:
            trial = (line + " " + wd).strip()
            width = draw.textlength(trial, font=font) + track * max(0, len(trial) - 1)
            if width <= maxw or not line:
                line = trial
            else:
                out.append(line)
                line = wd
        out.append(line)
    return out


def _draw_line_tracked(draw, xy, s, font, fill, track):
    x, y = xy
    if not track:
        draw.text((x, y), s, font=font, fill=fill)
        return
    for ch in s:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + track


def render(slide, path, scale=1.0):
    img = Image.new("RGB", (int(W * scale), int(H * scale)), (0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    for p in slide.prims:
        t = p["t"]
        if t == "rect":
            xy = [p["x"] * scale, p["y"] * scale, (p["x"] + p["w"]) * scale, (p["y"] + p["h"]) * scale]
            fill = _hx(p["fill"]) if p["fill"] else None
            outline = _hx(p["line"]) if p["line"] else None
            d.rectangle(xy, fill=fill, outline=outline, width=max(1, int(p["lw"] * scale)))
        elif t == "pic":
            im = Image.open(p["path"]).convert("RGB")
            im = im.resize((max(1, int(p["w"] * scale)), max(1, int(p["h"] * scale))), Image.LANCZOS)
            img.paste(im, (int(p["x"] * scale), int(p["y"] * scale)))
        elif t == "rule":
            y = p["y"] * scale
            d.line([p["x"] * scale, y, (p["x"] + p["w"]) * scale, y],
                   fill=_mix(_hx(p["color"]), p["alpha"]), width=max(1, int(p["lw"] * scale)))
        elif t == "vrule":
            x = p["x"] * scale
            d.line([x, p["y"] * scale, x, (p["y"] + p["h"]) * scale],
                   fill=_mix(_hx(p["color"]), p["alpha"]), width=max(1, int(p["lw"] * scale)))
        elif t == "arrow":
            col = _mix(_hx(p["color"]), p["alpha"])
            x1, y1, x2, y2 = (v * scale for v in (p["x1"], p["y1"], p["x2"], p["y2"]))
            d.line([x1, y1, x2, y2], fill=col, width=max(1, int(p["lw"] * scale)))
            import math
            ang = math.atan2(y2 - y1, x2 - x1)
            hs = p["head"] * scale
            for sgn in (1, -1):
                a = ang + sgn * 2.5
                d.line([x2, y2, x2 + hs * math.cos(a), y2 + hs * math.sin(a)],
                       fill=col, width=max(1, int(p["lw"] * scale)))
        elif t == "text":
            size = p["size"] * scale
            f = _font(p["font"], size, p["bold"])
            s = p["s"].upper() if p["caps"] else p["s"]
            track = p["track"] * size
            lines = _wrap(d, s, f, p["w"] * scale, track)
            asc, desc = f.getmetrics()
            lh = size * p["line"]
            total = lh * len(lines)
            y = p["y"] * scale
            if p["anchor"] == "m" and p.get("h"):
                y = p["y"] * scale + (p["h"] * scale - total) / 2
            for ln in lines:
                if p["align"] == "c":
                    wid = d.textlength(ln, font=f) + track * max(0, len(ln) - 1)
                    x = p["x"] * scale + (p["w"] * scale - wid) / 2
                elif p["align"] == "r":
                    wid = d.textlength(ln, font=f) + track * max(0, len(ln) - 1)
                    x = (p["x"] + p["w"]) * scale - wid
                else:
                    x = p["x"] * scale
                _draw_line_tracked(d, (x, y + (lh - (asc + desc)) / 2), ln, f,
                                   _hx(p["color"]), track)
                y += lh

    img.save(path)
    return path


def contact(slides, out, cols=2, thumb=(760, 428)):
    from PIL import ImageDraw as ID
    rows = (len(slides) + cols - 1) // cols
    gap = 24
    sheet = Image.new("RGB", (cols * thumb[0] + (cols + 1) * gap,
                              rows * (thumb[1] + 30) + (rows + 1) * gap), (18, 18, 18))
    d = ID.Draw(sheet)
    for i, sl in enumerate(slides):
        tmp = f"/tmp/_c{i}.png"
        render(sl, tmp, scale=thumb[0] / W)
        im = Image.open(tmp)
        x = gap + (i % cols) * (thumb[0] + gap)
        y = gap + (i // cols) * (thumb[1] + 30 + gap)
        sheet.paste(im, (x, y + 24))
        d.text((x + 2, y + 4), f"{i+1:02d}  {sl.title}", fill=(230, 230, 230))
    sheet.save(out)
    return out
