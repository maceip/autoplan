"""FlashHandoff keynote — layout spec shared by the PPTX writer and the PNG verifier."""
from __future__ import annotations

import os

# ---------------------------------------------------------------- canvas
W, H = 1920, 1080
M = 104                 # outer margin
TOP_RULE, BOT_RULE = 74, 1006

# ---------------------------------------------------------------- colour
BLACK = "#000000"
WHITE = "#FFFFFF"
DIM = "#9A9A9A"
DIM2 = "#6E6E6E"
YELLOW = "#EDEE05"
BLUE = "#2E9FE0"
GREEN = "#33C42B"
MAGENTA = "#E840C8"
ORANGE = "#F0741A"

# ---------------------------------------------------------------- type
F_DISPLAY = "Halvar Breitschrift DEMO ExBold"
F_MONO = "IBM Plex Mono"
F_SANS = "Helvetica Neue"

# px -> pt (canvas is 1920x1080 px == 960x540 pt)
def pt(px: float) -> float:
    return px / 2.0


# ---------------------------------------------------------------- primitives
class Slide:
    def __init__(self, idx: int, title: str, notes: str = ""):
        self.idx = idx
        self.title = title
        self.notes = notes
        self.prims: list[dict] = []

    # -- drawing ---------------------------------------------------
    def rect(self, x, y, w, h, fill=None, line=None, lw=1.0):
        self.prims.append(dict(t="rect", x=x, y=y, w=w, h=h, fill=fill, line=line, lw=lw))
        return self

    def pic(self, path, x, y, w, h):
        self.prims.append(dict(t="pic", path=path, x=x, y=y, w=w, h=h))
        return self

    def rule(self, x, y, w, color=WHITE, alpha=0.22, weight=1.0):
        self.prims.append(dict(t="rule", x=x, y=y, w=w, color=color, alpha=alpha, lw=weight))
        return self

    def vrule(self, x, y, h, color=WHITE, alpha=0.22, weight=1.0):
        self.prims.append(dict(t="vrule", x=x, y=y, h=h, color=color, alpha=alpha, lw=weight))
        return self

    def text(self, x, y, w, s, font=F_SANS, size=30, color=WHITE, bold=False,
             line=1.22, track=0.0, align="l", anchor="t", caps=False, h=None,
             italic=False, space_after=0.0):
        self.prims.append(dict(t="text", x=x, y=y, w=w, h=h, s=s, font=font, size=size,
                               color=color, bold=bold, line=line, track=track,
                               align=align, anchor=anchor, caps=caps, italic=italic,
                               space_after=space_after))
        return self

    def arrow(self, x1, y1, x2, y2, color=WHITE, alpha=0.45, lw=1.6, head=9, dashed=False):
        self.prims.append(dict(t="arrow", x1=x1, y1=y1, x2=x2, y2=y2, color=color,
                               alpha=alpha, lw=lw, head=head, dashed=dashed))
        return self

    # -- recurring furniture ---------------------------------------
    def frame(self, kicker: str, section: str, page: str = "", accent=WHITE):
        self.rule(M, TOP_RULE, W - 2 * M, WHITE, 0.20, 1.0)
        self.rule(M, BOT_RULE, W - 2 * M, WHITE, 0.20, 1.0)
        self.text(M, 34, 700, kicker, F_MONO, 17, DIM, track=0.16, caps=True)
        self.text(W - M - 300, 34, 300, section, F_MONO, 17, DIM, track=0.16,
                  caps=True, align="r")
        self.text(M, 1022, 700, "FLASHHANDOFF  ·  AUTOPLAN  ·  14 NOV 2026",
                  F_MONO, 15, DIM2, track=0.16, caps=True)
        if page:
            self.text(W - M - 300, 1022, 300, page, F_MONO, 15, DIM2, track=0.16,
                      caps=True, align="r")
        return self


# ---------------------------------------------------------------- helpers
def headline(sl: Slide, y, s, size=86, color=WHITE, w=None, line=0.98):
    sl.text(M, y, w or (W - 2 * M), s, F_DISPLAY, size, color, line=line, track=-0.012)
    return sl


def eyebrow(sl: Slide, x, y, s, color=YELLOW, w=800):
    sl.text(x, y, w, s, F_MONO, 19, color, track=0.20, caps=True)
    return sl


def body(sl: Slide, x, y, w, s, size=28, color="#D8D8D8", line=1.34):
    sl.text(x, y, w, s, F_SANS, size, color, line=line)
    return sl


def label(sl: Slide, x, y, w, s, color=WHITE, size=22, track=0.14):
    sl.text(x, y, w, s, F_MONO, size, color, track=track, caps=True)
    return sl


def card(sl: Slide, x, y, w, h, accent=None, fill="#0C0C0C", alpha_border=0.22):
    sl.rect(x, y, w, h, fill=fill, line=WHITE, lw=1.0)
    if accent:
        sl.rect(x, y, w, 4, fill=accent)
    return sl


def arrow_h(sl: Slide, x1, x2, y, color=WHITE, alpha=0.4, dashed=False, head=10):
    sl.arrow(x1, y, x2 - head * 1.2, y, color, alpha, 1.6, head, dashed)
    return sl
