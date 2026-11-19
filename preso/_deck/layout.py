"""Layout primitives + text measurement.

Every line of type is measured with the real font files before it is placed.
Nothing in the deck is allowed to auto-wrap: if a line does not fit the box the
build fails loudly instead of silently reflowing in Keynote.
"""
from __future__ import annotations

import os
from PIL import ImageFont

from theme import (
    W, H, M, CW, TOP_RULE, BOT_RULE, KICKER_Y, FOOTER_Y,
    BLACK, WHITE, INK, DIM, DIMMER, FAINT, HAIR, LIME,
    F_DISPLAY, F_MONO, F_SANS, T_MICRO, T_NANO, T_BODY, LH_TEXT,
)

FONT_FILES = {
    (F_DISPLAY, False): "~/Library/Fonts/Halvar-Breitschrift-ExtraBold-Demo.ttf",
    (F_MONO, False): "~/Library/Fonts/IBMPlexMono-Regular.otf",
    (F_MONO, True): "~/Library/Fonts/IBMPlexMono-SemiBold.otf",
    (F_SANS, False): "/System/Library/Fonts/HelveticaNeue.ttc",
    (F_SANS, True): "/System/Library/Fonts/HelveticaNeue.ttc",
}
_CACHE: dict = {}


def _face(font: str, size: float, bold: bool = False):
    key = (font, round(size, 2), bold)
    if key in _CACHE:
        return _CACHE[key]
    path = os.path.expanduser(FONT_FILES.get((font, bold)) or FONT_FILES[(font, False)])
    idx = 1 if (font == F_SANS and bold) else 0
    f = ImageFont.truetype(path, size=max(1, int(round(size))), index=idx)
    _CACHE[key] = f
    return f


def text_width(s: str, font: str, size: float, track: float = 0.0, bold: bool = False) -> float:
    f = _face(font, size, bold)
    base = f.getlength(s)
    return base + track * size * max(0, len(s) - 1)


def wrap(s: str, font: str, size: float, width: float, track: float = 0.0,
         bold: bool = False) -> list[str]:
    """Greedy wrap to `width`, then shrink the target 4% so Keynote's metrics
    (which differ from FreeType's by a hair) never produce an extra line."""
    target = width * 0.96
    out: list[str] = []
    for para in s.split("\n"):
        if not para.strip():
            out.append("")
            continue
        words, line = para.split(" "), ""
        for wd in words:
            trial = f"{line} {wd}".strip()
            if not line or text_width(trial, font, size, track, bold) <= target:
                line = trial
            else:
                out.append(line)
                line = wd
        out.append(line)
    return out


class Text:
    def __init__(self, x, y, w, s, font=F_SANS, size=22, color=INK, bold=False,
                 line=LH_TEXT, track=0.0, align="l", caps=False, wrap_width=None,
                 explicit=False):
        self.x, self.y, self.w = x, y, w
        self.size, self.font, self.bold = size, font, bold
        self.color, self.line, self.track = color, line, track
        self.align, self.caps = align, caps
        txt = s.upper() if caps else s
        self.lines = txt.split("\n") if explicit else wrap(txt, font, size, wrap_width or w, track, bold)
        self.lh = size * line
        self.h = self.lh * len(self.lines)
        self.widest = max((text_width(ln, font, size, track, bold) for ln in self.lines), default=0)

    def bbox(self):
        return (self.x, self.y, self.x + self.w, self.y + self.h)

    def overflow(self) -> float:
        """How far the widest line exceeds the box, in px (<=0 is good)."""
        return self.widest - self.w


class Slide:
    def __init__(self, n: int, title: str, notes: str = ""):
        self.n = n
        self.title = title
        self.notes = notes
        self.items: list[dict] = []
        self.texts: list[Text] = []

    # ---------------------------------------------------------- shapes
    def rect(self, x, y, w, h, fill=None, line=None, lw=1.0, alpha=1.0):
        self.items.append(dict(t="rect", x=x, y=y, w=w, h=h, fill=fill, line=line,
                               lw=lw, alpha=alpha))
        return self

    def pic(self, path, x, y, w, h):
        self.items.append(dict(t="pic", path=path, x=x, y=y, w=w, h=h))
        return self

    def rule(self, x, y, w, color=WHITE, alpha=0.14, lw=1.0):
        self.items.append(dict(t="rule", x=x, y=y, w=w, color=color, alpha=alpha, lw=lw))
        return self

    def vrule(self, x, y, h, color=WHITE, alpha=0.14, lw=1.0):
        self.items.append(dict(t="vrule", x=x, y=y, h=h, color=color, alpha=alpha, lw=lw))
        return self

    def arrow(self, x1, y1, x2, y2, color=WHITE, alpha=0.4, lw=1.4, head=9, dashed=False):
        self.items.append(dict(t="arrow", x1=x1, y1=y1, x2=x2, y2=y2, color=color,
                               alpha=alpha, lw=lw, head=head, dashed=dashed))
        return self

    def video(self, path, poster, x, y, w, h):
        self.items.append(dict(t="video", path=path, poster=poster, x=x, y=y, w=w, h=h))
        return self

    # ---------------------------------------------------------- type
    def text(self, x, y, w, s, font=F_SANS, size=T_BODY, color=INK, **kw) -> Text:
        t = Text(x, y, w, s, font=font, size=size, color=color, **kw)
        self.texts.append(t)
        return t

    def frame(self, kicker: str, page: str = "", accent=DIM):
        self.rule(M, TOP_RULE, CW, WHITE, 0.18, 1.0)
        self.rule(M, BOT_RULE, CW, WHITE, 0.18, 1.0)
        self.text(M, KICKER_Y, 900, kicker, F_MONO, T_MICRO, accent, track=0.17, caps=True)
        self.text(W - M - 220, KICKER_Y, 220, page or f"{self.n:02d} / 11", F_MONO, T_MICRO,
                  DIMMER, track=0.17, caps=True, align="r")
        self.text(M, FOOTER_Y, 700, "FLASHHANDOFF  ·  AUTOPLAN  ·  14 NOV 2026",
                  F_MONO, T_NANO, FAINT, track=0.16, caps=True)
        return self

    # ---------------------------------------------------------- components
    def card(self, x, y, w, h, fill="#0E0E11", border=0.13, accent=None,
             accent_h=5, accent_pos="top"):
        self.rect(x, y, w, h, fill=fill, line=WHITE, lw=1.0, alpha=border)
        if accent:
            if accent_pos == "top":
                self.rect(x, y, w, accent_h, fill=accent)
            elif accent_pos == "left":
                self.rect(x, y, accent_h, h, fill=accent)
        return self

    def label(self, x, y, w, s, color=DIM, size=T_MICRO, track=0.16):
        return self.text(x, y, w, s, F_MONO, size, color, track=track, caps=True)

    def num(self, x, y, s, color=LIME, size=34):
        return self.text(x, y, 90, s, F_DISPLAY, size, color, track=-0.02, explicit=True)

    # ---------------------------------------------------------- lint
    def lint(self) -> list[str]:
        issues = []
        for t in self.texts:
            if t.overflow() > 1.0:
                issues.append(f"slide {self.n:02d}: text overflows box by {t.overflow():.0f}px "
                              f"— {t.lines[0][:48]!r}")
            x0, y0, x1, y1 = t.bbox()
            if x0 < M - 2 or x1 > W - M + 2:
                issues.append(f"slide {self.n:02d}: text outside margin "
                              f"({x0:.0f}..{x1:.0f}) — {t.lines[0][:40]!r}")
            if t.y < BOT_RULE - 40 and y1 > BOT_RULE - 4:
                issues.append(f"slide {self.n:02d}: text crosses footer rule "
                              f"(bottom {y1:.0f}) — {t.lines[0][:40]!r}")
        return issues


# ---------------------------------------------------------------- helpers
def headline(sl: Slide, y, s, size=72, color=INK, w=None, line=1.02, track=-0.015):
    return sl.text(M, y, w or CW, s, F_DISPLAY, size, color, line=line, track=track)


def subhead(sl: Slide, y, s, size=26, color=DIM, w=None, line=1.42):
    return sl.text(M, y, w or 1240, s, F_SANS, size, color, line=line)


def kicker(sl: Slide, x, y, s, color=LIME, w=700, size=T_MICRO):
    return sl.text(x, y, w, s, F_MONO, size, color, track=0.18, caps=True)
