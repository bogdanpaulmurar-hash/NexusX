# -*- coding: utf-8 -*-
"""
Generates the NexusX icon (taskbar, window, tray, shortcut):
petrol gradient tile + code brackets  < >  joined by a chain link — "code" + "links".

    python tools/make_icon.py        → assets/nexusx.png, nexusx_512.png, nexusx.ico, nexusx_tray.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
ASSETS = Path(__file__).resolve().parents[1] / "assets"


def _gradient(size: int) -> Image.Image:
    top, bottom = (0, 55, 76), (0, 163, 190)  # Siemens petrol dark → accent
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = min(1.0, max(0.0, (x * 0.35 + y * 0.65) / size))
            px[x, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return g


def _link(draw: ImageDraw.ImageDraw, cx: int, cy: int, w: int, h: int, width: int, fill) -> None:
    draw.rounded_rectangle((cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2), radius=h // 2, outline=fill, width=width)


def render(size: int = S) -> Image.Image:
    base = _gradient(256).resize((size, size), Image.BICUBIC).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255)
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile.paste(base, (0, 0), mask)

    # subtle top highlight
    hl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse((-size * 0.3, -size * 0.75, size * 1.3, size * 0.42), fill=(255, 255, 255, 34))
    tile = Image.alpha_composite(tile, Image.composite(hl, Image.new("RGBA", hl.size), mask))

    fg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(fg)
    white = (255, 255, 255, 255)
    stroke = int(size * 0.075)
    # code brackets
    m, top, bot = int(size * 0.17), int(size * 0.30), int(size * 0.70)
    mid = size // 2
    d.line([(m + int(size * 0.13), top), (m, mid), (m + int(size * 0.13), bot)], fill=white, width=stroke, joint="curve")
    d.line([(size - m - int(size * 0.13), top), (size - m, mid), (size - m - int(size * 0.13), bot)], fill=white, width=stroke, joint="curve")
    for x, y in ((m + int(size * 0.13), top), (m, mid), (m + int(size * 0.13), bot),
                 (size - m - int(size * 0.13), top), (size - m, mid), (size - m - int(size * 0.13), bot)):
        r = stroke // 2
        d.ellipse((x - r, y - r, x + r, y + r), fill=white)

    # chain link: two interlocked rounded links on a rising diagonal
    lw, lh, lt = int(size * 0.27), int(size * 0.145), int(size * 0.048)
    off = int(size * 0.088)
    amber = (255, 214, 102, 255)
    white_l = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _link(ImageDraw.Draw(white_l), mid + off, mid, lw, lh, lt, white)
    amber_l = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _link(ImageDraw.Draw(amber_l), mid - off, mid, lw, lh, lt, amber)
    link_layer = Image.alpha_composite(white_l, amber_l)
    # white passes over amber at the upper crossing → interlocked look
    clip = Image.new("L", (size, size), 0)
    ImageDraw.Draw(clip).rectangle((mid + off - lw // 2 - lt, mid - lh // 2 - lt, mid + off - lw // 2 + lt * 2, mid - lh // 4), fill=255)
    top_white = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    top_white.paste(white_l, (0, 0), clip)
    link_layer = Image.alpha_composite(link_layer, top_white)
    link_layer = link_layer.rotate(35, resample=Image.BICUBIC, center=(mid, mid))

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow.paste((0, 30, 45, 120), (0, 0), Image.alpha_composite(fg, link_layer).split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.012))
    shadow = shadow.transform(shadow.size, Image.AFFINE, (1, 0, -size * 0.008, 0, 1, -size * 0.012))

    out = Image.alpha_composite(tile, shadow)
    out = Image.alpha_composite(out, fg)
    out = Image.alpha_composite(out, link_layer)
    return out


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    big = render(S)
    big.resize((512, 512), Image.LANCZOS).save(ASSETS / "nexusx_512.png")
    png256 = big.resize((256, 256), Image.LANCZOS)
    png256.save(ASSETS / "nexusx.png")
    big.resize((64, 64), Image.LANCZOS).save(ASSETS / "nexusx_tray.png")
    sizes = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]
    png256.save(ASSETS / "nexusx.ico", sizes=sizes)
    print("Icons written to", ASSETS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
