"""Render an actual .pptx back to PNG so we verify the file, not the intent."""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from spec import W, H, F_DISPLAY, F_MONO, F_SANS

EMU_PER_PX = 6350
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

FONT_FILES = {
    (F_DISPLAY, False): os.path.expanduser("~/Library/Fonts/Halvar-Breitschrift-ExtraBold-Demo.ttf"),
    (F_MONO, False): os.path.expanduser("~/Library/Fonts/IBMPlexMono-Regular.otf"),
    (F_MONO, True): os.path.expanduser("~/Library/Fonts/IBMPlexMono-SemiBold.otf"),
    (F_SANS, False): "/System/Library/Fonts/HelveticaNeue.ttc",
    (F_SANS, True): "/System/Library/Fonts/HelveticaNeue.ttc",
}
_C = {}


def _font(name, px, bold=False):
    k = (name, round(px, 1), bold)
    if k in _C:
        return _C[k]
    path = FONT_FILES.get((name, bold)) or FONT_FILES.get((name, False)) or FONT_FILES[(F_SANS, False)]
    idx = 1 if (name == F_SANS and bold) else 0
    try:
        f = ImageFont.truetype(path, max(1, int(round(px))), index=idx)
    except Exception:
        f = ImageFont.truetype(FONT_FILES[(F_SANS, False)], max(1, int(round(px))))
    _C[k] = f
    return f


def _px(v):
    return v / EMU_PER_PX


def _color_of(fmt):
    """python-pptx RGBColor is a str of six hex digits."""
    for getter in (lambda: fmt.rgb, lambda: fmt.fore_color.rgb,
                   lambda: fmt.color.rgb, lambda: fmt.fill.fore_color.rgb):
        try:
            c = str(getter())
            if len(c) == 6:
                return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
        except Exception:
            continue
    return (255, 255, 255)


def _line_style(shape):
    ln = shape.line._get_or_add_ln()
    col = (255, 255, 255)
    for c in ln.iter(f"{A}srgbClr"):
        v = c.get("val")
        if v and len(v) == 6:
            col = tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
        a = c.find(f"{A}alpha")
        alpha = int(a.get("val")) / 100000 if a is not None else 1.0
        return col, alpha
    return col, 1.0


def _is_dashed(shape):
    ln = shape.line._get_or_add_ln()
    d = ln.find(f"{A}prstDash")
    return d is not None and d.get("val") in ("dash", "sysDash", "lgDash")


def render_pptx(path, outdir):
    prs = Presentation(path)
    out = []
    for i, slide in enumerate(prs.slides, 1):
        img = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(img, "RGBA")

        for sh in slide.shapes:
            st = sh.shape_type
            x, y = _px(sh.left), _px(sh.top)
            w, h = _px(sh.width), _px(sh.height)

            if st == MSO_SHAPE_TYPE.PICTURE:
                im = Image.open(sh.image.blob and __import__("io").BytesIO(sh.image.blob))
                im = im.convert("RGB").resize((max(1, int(w)), max(1, int(h))), Image.LANCZOS)
                img.paste(im, (int(x), int(y)))

            elif st == MSO_SHAPE_TYPE.LINE:
                col, alpha = _line_style(sh)
                dash = _is_dashed(sh)
                x2 = x + _px(sh.width) if False else x
                # connectors: begin/end are encoded in flipH/flipV
                x1, y1, x2, y2 = x, y, x + w, y + h
                if sh.element.find(f".//{A}xfrm") is not None:
                    xf = sh.element.find(f".//{A}xfrm")
                    if xf.get("flipH") == "1":
                        x1, x2 = x2, x1
                    if xf.get("flipV") == "1":
                        y1, y2 = y2, y1
                lw = max(1, int(round(_px(sh.line.width or 12700))))
                if dash:
                    import math
                    L = math.hypot(x2 - x1, y2 - y1)
                    n = max(1, int(L / 12))
                    for k in range(n):
                        t0, t1 = k / n, (k + 0.55) / n
                        d.line([x1 + (x2 - x1) * t0, y1 + (y2 - y1) * t0,
                                x1 + (x2 - x1) * t1, y1 + (y2 - y1) * t1],
                               fill=(*col, int(alpha * 255)), width=lw)
                else:
                    d.line([x1, y1, x2, y2], fill=(*col, int(alpha * 255)), width=lw)

            elif st == MSO_SHAPE_TYPE.AUTO_SHAPE:
                fill = None
                try:
                    if sh.fill.type is not None and str(sh.fill.type) != "MSO_FILL_TYPE.BACKGROUND (5)":
                        fill = _color_of(sh.fill)
                except Exception:
                    fill = None
                outline = None
                try:
                    if sh.line.width and sh.line.width > 0:
                        col, alpha = _line_style(sh)
                        outline = (*col, int(alpha * 255))
                except Exception:
                    outline = None
                if fill or outline:
                    d.rectangle([x, y, x + w, y + h], fill=fill, outline=outline,
                                width=max(1, int(round(_px(sh.line.width or 12700)))) if outline else 0)

            elif st == MSO_SHAPE_TYPE.TEXT_BOX or sh.has_text_frame:
                tf = sh.text_frame
                anchor_mid = str(tf.vertical_anchor).startswith("MIDDLE")
                lines = []
                for para in tf.paragraphs:
                    txt = "".join(r.text for r in para.runs)
                    if not para.runs:
                        lines.append(("", 18, F_SANS, False, (255, 255, 255), 1.2, 0, 0))
                        continue
                    r0 = para.runs[0]
                    size = (r0.font.size.pt * 2) if r0.font.size else 18
                    name = r0.font.name or F_SANS
                    bold = bool(r0.font.bold)
                    col = _color_of(r0.font)
                    ls = para.line_spacing
                    ls_px = (ls.pt * 2) if hasattr(ls, "pt") else (ls * size if isinstance(ls, float) else size * 1.2)
                    rPr = r0._r.find(f"{A}rPr")
                    spc = int(rPr.get("spc")) / 100.0 * 2 if (rPr is not None and rPr.get("spc")) else 0.0
                    align = str(para.alignment or "LEFT")
                    lines.append((txt, size, name, bold, col, ls_px, spc, align))

                total = sum(l[5] for l in lines)
                cy = y + ((h - total) / 2 if anchor_mid else 0)
                for txt, size, name, bold, col, ls_px, spc, align in lines:
                    f = _font(name, size, bold)
                    if not txt:
                        cy += ls_px
                        continue
                    if align.startswith("CENTER"):
                        tw = d.textlength(txt, font=f) + spc * max(0, len(txt) - 1)
                        tx = x + (w - tw) / 2
                    elif align.startswith("RIGHT"):
                        tw = d.textlength(txt, font=f) + spc * max(0, len(txt) - 1)
                        tx = x + w - tw
                    else:
                        tx = x
                    # greedy wrap inside the text box, as PowerPoint does
                    words, cur = txt.split(" "), ""
                    wrapped = []
                    for wd in words:
                        trial = (cur + " " + wd).strip()
                        tw_ = d.textlength(trial, font=f) + spc * max(0, len(trial) - 1)
                        if tw_ <= w or not cur:
                            cur = trial
                        else:
                            wrapped.append(cur)
                            cur = wd
                    wrapped.append(cur)
                    for line_txt in wrapped:
                        lx = tx
                        if align.startswith("CENTER"):
                            lw_ = d.textlength(line_txt, font=f) + spc * max(0, len(line_txt) - 1)
                            lx = x + (w - lw_) / 2
                        elif align.startswith("RIGHT"):
                            lw_ = d.textlength(line_txt, font=f) + spc * max(0, len(line_txt) - 1)
                            lx = x + w - lw_
                        if spc:
                            for ch in line_txt:
                                d.text((lx, cy), ch, font=f, fill=col)
                                lx += d.textlength(ch, font=f) + spc
                        else:
                            d.text((lx, cy), line_txt, font=f, fill=col)
                        cy += ls_px

        p = os.path.join(outdir, f"slide{i}.png")
        img.save(p)
        out.append(p)
    return out


if __name__ == "__main__":
    import sys
    print(render_pptx(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "/tmp"))
