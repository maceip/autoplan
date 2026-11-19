"""Design tokens for the FlashHandoff deck.

One canvas, one grid, one type scale. Every slide is composed from these.
"""
from __future__ import annotations

# ---------------------------------------------------------------- canvas
W, H = 1920, 1080
M = 88                      # outer margin
CW = W - 2 * M              # 1744 usable width

TOP_RULE = 58
BOT_RULE = 1022
KICKER_Y = 24
FOOTER_Y = 1038

# ---------------------------------------------------------------- ink
BLACK = "#000000"
WHITE = "#FFFFFF"

INK = "#F4F4F6"             # primary text
DIM = "#A6A6AE"             # secondary text
DIMMER = "#78787F"          # tertiary / captions
FAINT = "#4A4A50"           # rules, disabled
HAIR = "#3A3A40"            # hairline on black

# ---------------------------------------------------------------- accents
LIME = "#E7F84A"            # the deck's one loud colour
PURPLE = "#B7A3F9"          # agent-stack callouts
PURPLE_DK = "#1B1630"
ORANGE = "#FF7A1A"
CORAL = "#F08A6A"
BLUE = "#2BA6F7"
GREEN = "#74DC96"
MAGENTA = "#E255C9"

# dark card tints — the hue laid over black at ~12%
CARD_PURPLE = "#1C1730"
CARD_BLUE = "#0D2131"
CARD_GREEN = "#0F291B"
CARD_ORANGE = "#2B1A0C"
CARD_OLIVE = "#282A12"
CARD_SLATE = "#16181F"
CARD_NEUTRAL = "#0E0E11"

# ---------------------------------------------------------------- type
F_DISPLAY = "Halvar Breitschrift DEMO ExBold"
F_MONO = "IBM Plex Mono"
F_SANS = "Helvetica Neue"

# px sizes (canvas is 1920x1080; 1px == 0.5pt)
T_TITLE = 118
T_H1 = 72
T_H2 = 54
T_H3 = 40
T_H4 = 30
T_LEAD = 26
T_BODY = 22
T_SMALL = 20
T_MICRO = 15
T_NANO = 13

LH_TIGHT = 0.98
LH_HEAD = 1.06
LH_TEXT = 1.40
LH_LOOSE = 1.52
