"""The deck's one graphic device: a folded, ribbed 3D pattern.

Rendered procedurally at full size so it stays crisp at 1920 and can be cropped
to any panel shape without upscaling artefacts.
"""
from __future__ import annotations

import os
import numpy as np
from PIL import Image, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "pat")


def _hex(h: str):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


def fold(base: str, w: int, h: int, period: float = 74.0, lean: float = 1.1,
         contrast: float = 0.19, wave: float = 26.0, spec: float = 0.10,
         seed: float = 0.0, ss: int = 2) -> Image.Image:
    """Vertical ribs that bend gently, shaded like fabric folded over a form."""
    W_, H_ = w * ss, h * ss
    yy, xx = np.mgrid[0:H_, 0:W_].astype(np.float32)

    # a slow horizontal wave bends the ribs, so it reads as a surface not stripes
    bend = wave * np.sin(yy / H_ * np.pi * 1.1 + seed) + wave * 0.35 * np.sin(
        yy / H_ * np.pi * 2.7 + seed * 1.7)
    d = (xx + bend) / (period * ss) + lean * (yy / H_)

    s = np.sin(2 * np.pi * d)
    # asymmetric ridge: broad lit face, narrow shaded crease
    shade = 1.0 - contrast * (0.5 - 0.5 * s) ** 1.45

    base_rgb = _hex(base)
    rgb = base_rgb[None, None, :] * shade[:, :, None]

    crest = np.clip((s - 0.45) / 0.55, 0, 1) ** 2.0
    rgb = rgb + spec * crest[:, :, None] * (1.0 - rgb)

    # gentle top-to-bottom falloff so panels do not look flat
    fall = 1.0 - 0.07 * (yy / H_)
    rgb = rgb * fall[:, :, None]

    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB")
    img = img.resize((w, h), Image.LANCZOS)
    return img.filter(ImageFilter.GaussianBlur(0.4))


def get(name: str, base: str, w: int, h: int, **kw) -> str:
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, f"{name}_{w}x{h}.png")
    if not os.path.exists(p):
        fold(base, w, h, **kw).save(p)
    return p


PALETTE = {
    "lime": "#DFE80C",
    "purple": "#7E63E0",
    "blue": "#1E7FC2",
    "green": "#1F9A3C",
    "orange": "#D9650E",
    "magenta": "#B93AA8",
}


def panel(hue: str, w: int, h: int, **kw) -> str:
    return get(hue, PALETTE[hue], w, h, **kw)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for k, v in PALETTE.items():
        fold(v, 920, 1080).save(os.path.join(OUT, f"{k}_preview.png"))
        print("wrote", k)
