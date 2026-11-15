"""Procedural 3D rib/wave textures matching the Keynote '3D Pattern Design' theme."""
import numpy as np
from PIL import Image, ImageFilter


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def pattern(base_hex, w, h, angle_deg=0.0, period=70.0, warp_px=4.0,
            contrast=0.40, spec=0.20, softness=0.7, seed=0.0, warp_freq=0.55):
    """Ribbed 3D pattern.

    angle_deg: 0 -> vertical ribs, 90 -> horizontal ribs.
    period:    distance between rib crests in px.
    warp_px:   lateral wobble of the ribs in px (keep small relative to period).
    """
    base = np.array(hex2rgb(base_hex), dtype=np.float32) / 255.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)

    a = np.deg2rad(angle_deg)
    d = xx * np.cos(a) + yy * np.sin(a)
    perp = -xx * np.sin(a) + yy * np.cos(a)

    # gentle lateral wobble, expressed directly in phase so it never aliases
    wob = np.sin(perp * (2 * np.pi / (max(w, h) * warp_freq)) + seed)
    wob += 0.35 * np.sin(perp * (2 * np.pi / (max(w, h) * 0.19)) + seed * 1.9)
    t = (d + warp_px * wob) * (2 * np.pi / period)

    s = np.sin(t)
    # broad soft ridge: bright crest, shaded valley, never pure black
    shade = 1.0 - contrast * (0.5 - 0.5 * s) ** 1.25
    rgb = base[None, None, :] * shade[:, :, None]

    crest = np.clip((s - 0.55) / 0.45, 0, 1) ** 1.6
    rgb = rgb + spec * crest[:, :, None] * (1.0 - rgb)

    img = Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8), "RGB")
    if softness:
        img = img.filter(ImageFilter.GaussianBlur(softness))
    return img


def vignette(img, strength=0.10):
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2, h / 2
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / 1.414
    m = 1.0 - strength * r ** 2
    arr = np.asarray(img).astype(np.float32) * m[:, :, None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


SPECS = {
    # name:      colour     angle period warp
    "yellow":  ("#EDEE05",   0.0,   72,  3.0),
    "blue":    ("#2E9FE0",  90.0,  118,  7.0),
    "green":   ("#33C42B",  90.0,  112,  6.0),
    "magenta": ("#E840C8",  90.0,  124,  7.0),
    "orange":  ("#F0741A",  58.0,  106,  5.0),
}


def build(name, w, h, seed=0.0, period=None, contrast=0.40, softness=0.7):
    color, ang, base_period, warp = SPECS[name]
    per = period if period is not None else base_period
    im = pattern(color, w, h, angle_deg=ang, period=per, warp_px=warp,
                 contrast=contrast, spec=0.18, softness=softness, seed=seed)
    return vignette(im, 0.08)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for n in SPECS:
        build(n, 1920, 1080).save(f"{out}/{n}.png")
        print("wrote", n)
