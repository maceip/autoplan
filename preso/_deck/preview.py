"""Render the built .pptx back to PNG so we look at the file, not the intent.

This is a fast composition check. The authoritative render is LibreOffice -> PDF.
"""
from __future__ import annotations

import io
import math
import os

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from layout import _face
from theme import W, H, F_SANS

EMU = 6350
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def px(v):
    return v / EMU


def _srgb(el):
    c = el.find(f".//{A}srgbClr")
    if c is None:
        return None, 1.0
    v = c.get("val")
    rgb = tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
    a = c.find(f"{A}alpha")
    alpha = int(a.get("val")) / 100000 if a is not None else 1.0
    return rgb, alpha


def _fill(shape):
    try:
        if shape.fill.type is None:
            return None, 1.0
        el = shape.fill._xPr
        return _srgb(el)
    except Exception:
        return None, 1.0


def _line(shape):
    try:
        if shape.line.width is None:
            return None, 1.0, 1
        el = shape.line._get_or_add_ln()
        rgb, a = _srgb(el)
        return rgb, a, max(1, int(round(px(shape.line.width))))
    except Exception:
        return None, 1.0, 1


def _dashed(shape):
    ln = shape.line._get_or_add_ln()
    return ln.find(f"{A}prstDash") is not None


def _arrow(shape):
    ln = shape.line._get_or_add_ln()
    return ln.find(f"{A}tailEnd") is not None


def render(path, outdir):
    prs = Presentation(path)
    os.makedirs(outdir, exist_ok=True)
    outs = []
    for i, slide in enumerate(prs.slides, 1):
        img = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(img, "RGBA")

        for sh in slide.shapes:
            st = sh.shape_type
            x, y = px(sh.left), px(sh.top)
            w, h = px(sh.width), px(sh.height)

            if st == MSO_SHAPE_TYPE.PICTURE:
                im = Image.open(io.BytesIO(sh.image.blob)).convert("RGB")
                im = im.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
                img.paste(im, (int(x), int(y)))

            elif st == MSO_SHAPE_TYPE.MEDIA:
                # movie: draw its poster if we can find it next to the file
                poster = os.path.join(os.path.dirname(path), "media", "poster.png")
                if os.path.exists(poster):
                    im = Image.open(poster).convert("RGB")
                    im = im.resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
                    img.paste(im, (int(x), int(y)))

            elif st == MSO_SHAPE_TYPE.LINE:
                rgb, a, lw = _line(sh)
                if rgb is None:
                    continue
                col = (*rgb, int(a * 255))
                x1, y1, x2, y2 = x, y, x + w, y + h
                xf = sh.element.find(f".//{A}xfrm")
                if xf is not None:
                    if xf.get("flipH") == "1":
                        x1, x2 = x2, x1
                    if xf.get("flipV") == "1":
                        y1, y2 = y2, y1
                if _dashed(sh):
                    L = math.hypot(x2 - x1, y2 - y1)
                    n = max(1, int(L / 14))
                    for k in range(n):
                        t0, t1 = k / n, (k + 0.55) / n
                        d.line([x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0,
                                x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1], fill=col, width=lw)
                else:
                    d.line([x1, y1, x2, y2], fill=col, width=lw)
                if _arrow(sh):
                    ang = math.atan2(y2 - y1, x2 - x1)
                    for sgn in (1, -1):
                        a2 = ang + sgn * 2.6
                        d.line([x2, y2, x2 + 11 * math.cos(a2), y2 + 11 * math.sin(a2)],
                               fill=col, width=lw)

            elif st == MSO_SHAPE_TYPE.AUTO_SHAPE:
                f, fa = _fill(sh)
                l, la, lw = _line(sh)
                box = [x, y, x + w, y + h]
                if f:
                    d.rectangle(box, fill=(*f, int(fa * 255)))
                if l and la > 0.01:
                    d.rectangle(box, outline=(*l, int(la * 255)), width=lw)

            elif sh.has_text_frame:
                cy = y
                for para in sh.text_frame.paragraphs:
                    if not para.runs:
                        continue
                    r0 = para.runs[0]
                    size = (r0.font.size.pt * 2) if r0.font.size else 20
                    name = r0.font.name or F_SANS
                    bold = bool(r0.font.bold)
                    rgb, _ = _srgb(r0._r.find(f"{A}rPr"))
                    color = rgb or (255, 255, 255)
                    ls = para.line_spacing
                    lh = (ls.pt * 2) if hasattr(ls, "pt") else size * 1.4
                    rPr = r0._r.find(f"{A}rPr")
                    spc = (int(rPr.get("spc")) / 100.0 * 2) if (rPr is not None and rPr.get("spc")) else 0.0
                    txt = "".join(r.text for r in para.runs)
                    f = _face(name, size, bold)
                    align = str(para.alignment or "LEFT")
                    if align.startswith("CENTER"):
                        tw = d.textlength(txt, font=f) + spc * max(0, len(txt) - 1)
                        cx = x + (w - tw) / 2
                    elif align.startswith("RIGHT"):
                        tw = d.textlength(txt, font=f) + spc * max(0, len(txt) - 1)
                        cx = x + w - tw
                    else:
                        cx = x
                    asc, desc = f.getmetrics()
                    ty = cy + (lh - (asc + desc)) / 2
                    if spc:
                        for ch in txt:
                            d.text((cx, ty), ch, font=f, fill=color)
                            cx += d.textlength(ch, font=f) + spc
                    else:
                        d.text((cx, ty), txt, font=f, fill=color)
                    cy += lh

        p = os.path.join(outdir, f"s{i:02d}.png")
        img.save(p)
        outs.append(p)
    return outs


if __name__ == "__main__":
    import sys
    for f in render(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "out/preview"):
        print(f)
