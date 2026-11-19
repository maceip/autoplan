"""Write the composed slides out as a native .pptx (Keynote opens it directly)."""
from __future__ import annotations

import os
from lxml import etree
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR

from theme import W, H

EMU_PER_PX = 6350          # 1920 px == 13.333 in == 12192000 EMU
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}


def _rgb(c: str) -> RGBColor:
    c = c.lstrip("#")
    return RGBColor(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _set_alpha(color_parent, alpha: float):
    """Attach <a:alpha> to the first srgbClr under a fill/line parent."""
    for clr in color_parent.iter(f"{A}srgbClr"):
        e = etree.SubElement(clr, f"{A}alpha")
        e.set("val", str(int(alpha * 100000)))
        return


def _dash(shape):
    ln = shape.line._get_or_add_ln()
    d = etree.Element(f"{A}prstDash")
    d.set("val", "dash")
    anchor = None
    for tag in ("headEnd", "tailEnd", "extLst"):
        e = ln.find(f"{A}{tag}")
        if e is not None:
            anchor = e
            break
    if anchor is not None:
        anchor.addprevious(d)
    else:
        ln.append(d)


def _arrowhead(shape):
    ln = shape.line._get_or_add_ln()
    e = etree.SubElement(ln, f"{A}tailEnd")
    e.set("type", "triangle")
    e.set("w", "med")
    e.set("len", "med")


def _line(shape, color, alpha, lw_px):
    shape.line.color.rgb = _rgb(color)
    shape.line.width = Pt(lw_px / 2.0)
    if alpha < 1.0:
        _set_alpha(shape.line._get_or_add_ln(), alpha)


def _textbox(slide, t):
    h = t.h if t.h > 0 else t.size * t.line * 1.4
    box = slide.shapes.add_textbox(Emu(int(t.x * EMU_PER_PX)), Emu(int(t.y * EMU_PER_PX)),
                                   Emu(int(t.w * EMU_PER_PX)), Emu(int(h * EMU_PER_PX)))
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP

    bodyPr = tf._txBody.find(f"{A}bodyPr")
    for tag in ("normAutofit", "spAutoFit"):
        for e in bodyPr.findall(f"{A}{tag}"):
            bodyPr.remove(e)

    for i, ln in enumerate(t.lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = ALIGN[t.align]
        para.line_spacing = Pt(t.size * t.line / 2.0)
        para.space_before = Pt(0)
        para.space_after = Pt(0)
        run = para.add_run()
        run.text = ln if ln else " "
        f = run.font
        f.name = t.font
        f.size = Pt(t.size / 2.0)
        f.bold = t.bold
        f.color.rgb = _rgb(t.color)
        rPr = run._r.get_or_add_rPr()
        if t.caps:
            rPr.set("cap", "all")
        if t.track:
            rPr.set("spc", str(int(t.track * t.size * 50)))
        for tag in ("ea", "cs"):
            e = etree.SubElement(rPr, f"{A}{tag}")
            e.set("typeface", t.font)
    return box


def build(slides, path, poster_map=None):
    prs = Presentation()
    prs.slide_width = Emu(W * EMU_PER_PX)
    prs.slide_height = Emu(H * EMU_PER_PX)
    blank = prs.slide_layouts[6]

    for spec in slides:
        s = prs.slides.add_slide(blank)

        bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                Emu(W * EMU_PER_PX), Emu(H * EMU_PER_PX))
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(0, 0, 0)
        bg.line.fill.background()
        bg.shadow.inherit = False

        for p in spec.items:
            t = p["t"]

            if t == "rect":
                sh = s.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE,
                    Emu(int(p["x"] * EMU_PER_PX)), Emu(int(p["y"] * EMU_PER_PX)),
                    Emu(int(p["w"] * EMU_PER_PX)), Emu(int(p["h"] * EMU_PER_PX)))
                sh.shadow.inherit = False
                if p["fill"]:
                    sh.fill.solid()
                    sh.fill.fore_color.rgb = _rgb(p["fill"])
                    if p["alpha"] < 1.0:
                        _set_alpha(sh.fill._xPr, p["alpha"])
                else:
                    sh.fill.background()
                if p["line"]:
                    _line(sh, p["line"], p["alpha"], p["lw"])
                else:
                    sh.line.fill.background()

            elif t == "pic":
                s.shapes.add_picture(p["path"],
                                     Emu(int(p["x"] * EMU_PER_PX)), Emu(int(p["y"] * EMU_PER_PX)),
                                     Emu(int(p["w"] * EMU_PER_PX)), Emu(int(p["h"] * EMU_PER_PX)))

            elif t in ("rule", "vrule"):
                if t == "rule":
                    x1, y1, x2, y2 = p["x"], p["y"], p["x"] + p["w"], p["y"]
                else:
                    x1, y1, x2, y2 = p["x"], p["y"], p["x"], p["y"] + p["h"]
                c = s.shapes.add_connector(
                    MSO_CONNECTOR.STRAIGHT,
                    Emu(int(x1 * EMU_PER_PX)), Emu(int(y1 * EMU_PER_PX)),
                    Emu(int(x2 * EMU_PER_PX)), Emu(int(y2 * EMU_PER_PX)))
                _line(c, p["color"], p["alpha"], p["lw"])

            elif t == "arrow":
                c = s.shapes.add_connector(
                    MSO_CONNECTOR.STRAIGHT,
                    Emu(int(p["x1"] * EMU_PER_PX)), Emu(int(p["y1"] * EMU_PER_PX)),
                    Emu(int(p["x2"] * EMU_PER_PX)), Emu(int(p["y2"] * EMU_PER_PX)))
                _line(c, p["color"], p["alpha"], p["lw"])
                if p["dashed"]:
                    _dash(c)
                _arrowhead(c)

            elif t == "video":
                poster = p.get("poster") or (poster_map or {}).get(p["path"])
                try:
                    mv = s.shapes.add_movie(
                        p["path"],
                        Emu(int(p["x"] * EMU_PER_PX)), Emu(int(p["y"] * EMU_PER_PX)),
                        Emu(int(p["w"] * EMU_PER_PX)), Emu(int(p["h"] * EMU_PER_PX)),
                        poster_frame_image=poster, mime_type="video/mp4")
                    mv.name = "Nucleus demo"
                except Exception:
                    if poster and os.path.exists(poster):
                        s.shapes.add_picture(
                            poster,
                            Emu(int(p["x"] * EMU_PER_PX)), Emu(int(p["y"] * EMU_PER_PX)),
                            Emu(int(p["w"] * EMU_PER_PX)), Emu(int(p["h"] * EMU_PER_PX)))

        for txt in spec.texts:
            _textbox(s, txt)

        if spec.notes:
            tf = s.notes_slide.notes_text_frame
            paras = spec.notes.split("\n")
            tf.text = paras[0]
            for ln in paras[1:]:
                tf.add_paragraph().text = ln

    prs.save(path)
    return path
