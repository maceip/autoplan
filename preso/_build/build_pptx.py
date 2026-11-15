"""Write the layout spec out as a real .pptx (Keynote opens this natively)."""
from __future__ import annotations

import copy
from lxml import etree
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR

from spec import W, H

EMU_PER_PX = 6350          # 1920 px == 13.333 in == 12192000 EMU
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}
ANCHOR = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE}


def _rgb(c):
    c = c.lstrip("#")
    return RGBColor(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _alpha(shape, alpha):
    """Apply transparency to a solid line fill."""
    ln = shape.line._get_or_add_ln()
    for clr in ln.iter(f"{A}srgbClr"):
        a = etree.SubElement(clr, f"{A}alpha")
        a.set("val", str(int(alpha * 100000)))


def _arrowhead(shape, head_px):
    """Triangle arrow head on the end point only."""
    ln = shape.line._get_or_add_ln()
    e = etree.SubElement(ln, f"{A}tailEnd")
    e.set("type", "triangle")
    e.set("w", "med")
    e.set("len", "med")


def _dash(shape):
    """Insert prstDash in schema order: after the fill, before headEnd/tailEnd."""
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


def _frame_line(shape, color, alpha, lw_px):
    shape.line.color.rgb = _rgb(color)
    shape.line.width = Pt(lw_px / 2.0)
    _alpha(shape, alpha)


def build(slides, path):
    prs = Presentation()
    prs.slide_width = Emu(W * EMU_PER_PX)
    prs.slide_height = Emu(H * EMU_PER_PX)
    blank = prs.slide_layouts[6]

    for spec in slides:
        s = prs.slides.add_slide(blank)

        # black canvas
        bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0,
                                Emu(W * EMU_PER_PX), Emu(H * EMU_PER_PX))
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(0, 0, 0)
        bg.line.fill.background()
        bg.shadow.inherit = False

        for p in spec.prims:
            t = p["t"]

            if t == "rect":
                sh = s.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                        Emu(int(p["x"] * EMU_PER_PX)), Emu(int(p["y"] * EMU_PER_PX)),
                                        Emu(int(p["w"] * EMU_PER_PX)), Emu(int(p["h"] * EMU_PER_PX)))
                sh.shadow.inherit = False
                if p["fill"]:
                    sh.fill.solid()
                    sh.fill.fore_color.rgb = _rgb(p["fill"])
                else:
                    sh.fill.background()
                if p["line"]:
                    _frame_line(sh, p["line"], 1.0, p["lw"])
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
                c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                           Emu(int(x1 * EMU_PER_PX)), Emu(int(y1 * EMU_PER_PX)),
                                           Emu(int(x2 * EMU_PER_PX)), Emu(int(y2 * EMU_PER_PX)))
                _frame_line(c, p["color"], p["alpha"], p["lw"])

            elif t == "arrow":
                c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,
                                           Emu(int(p["x1"] * EMU_PER_PX)), Emu(int(p["y1"] * EMU_PER_PX)),
                                           Emu(int(p["x2"] * EMU_PER_PX)), Emu(int(p["y2"] * EMU_PER_PX)))
                _frame_line(c, p["color"], p["alpha"], p["lw"])
                if p["dashed"]:
                    _dash(c)
                _arrowhead(c, p["head"])

            elif t == "text":
                box = s.shapes.add_textbox(
                    Emu(int(p["x"] * EMU_PER_PX)), Emu(int(p["y"] * EMU_PER_PX)),
                    Emu(int(p["w"] * EMU_PER_PX)),
                    Emu(int((p["h"] or p["size"] * p["line"] * 1.2) * EMU_PER_PX)))
                tf = box.text_frame
                tf.word_wrap = True
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                tf.vertical_anchor = ANCHOR[p["anchor"]]
                # disable autofit so nothing shrinks behind our back
                bodyPr = tf._txBody.find(f"{A}bodyPr")
                for tag in ("normAutofit", "spAutoFit"):
                    for e in bodyPr.findall(f"{A}{tag}"):
                        bodyPr.remove(e)

                txt = p["s"].upper() if p["caps"] else p["s"]
                lines = txt.split("\n")
                for i, ln in enumerate(lines):
                    para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                    para.alignment = ALIGN[p["align"]]
                    para.line_spacing = Pt(p["size"] * p["line"] / 2.0)
                    para.space_before = Pt(0)
                    para.space_after = Pt(0)
                    run = para.add_run()
                    run.text = ln
                    f = run.font
                    f.name = p["font"]
                    f.size = Pt(p["size"] / 2.0)
                    f.bold = p["bold"]
                    f.italic = p["italic"]
                    f.color.rgb = _rgb(p["color"])
                    rPr = run._r.get_or_add_rPr()
                    if p["caps"]:
                        rPr.set("cap", "all")
                    if p["track"]:
                        rPr.set("spc", str(int(p["track"] * p["size"] * 50)))
                    # make sure east-asian/complex-script also resolve to the same face
                    for tag in ("ea", "cs"):
                        e = etree.SubElement(rPr, f"{A}{tag}")
                        e.set("typeface", p["font"])

        if spec.notes:
            tf = s.notes_slide.notes_text_frame
            paras = spec.notes.split("\n")
            tf.text = paras[0]
            for ln in paras[1:]:
                tf.add_paragraph().text = ln

    prs.save(path)
    return path
