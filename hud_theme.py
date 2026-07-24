"""Shared sci-fi HUD drawing helpers for Helldivers image cards."""

from __future__ import annotations

import math
import random
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from .visual_assets import asset_image, font, paste_contain, text_width


BG = (6, 12, 22)
PANEL = (12, 22, 36, 210)
PANEL_EDGE = (56, 96, 128, 200)
CYAN = (86, 210, 245)
GOLD = (232, 196, 96)
TEXT = (236, 244, 250)
MUTED = (140, 168, 188)
DIM = (88, 112, 132)

FACTION = {
    "Humans": (90, 180, 240),
    "Super Earth": (90, 180, 240),
    "DSS": (180, 220, 245),
    "Defense": (80, 160, 230),
    "Urgent": (230, 80, 90),
    "Automaton": (230, 75, 80),
    "Terminids": (235, 185, 55),
    "Illuminate": (165, 100, 235),
}


def vertical_gradient(
    size: tuple[int, int],
    top: tuple[int, int, int] = (8, 16, 28),
    bottom: tuple[int, int, int] = (3, 6, 12),
) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(int(top[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, width, y), fill=color)
    return image


def add_stars(image: Image.Image, count: int = 180, seed: int = 42) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    rnd = random.Random(seed)
    w, h = image.size
    for _ in range(count):
        x, y = rnd.randrange(w), rnd.randrange(h)
        b = rnd.randrange(90, 220)
        a = rnd.randrange(80, 180)
        if rnd.random() < 0.08:
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(b, b + 20, 255, a))
        else:
            draw.point((x, y), fill=(b, b + 10, 255, a))


def circuit_header(image: Image.Image, box: tuple[int, int, int, int], accent=CYAN) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=14, fill=(10, 22, 36, 235), outline=accent + (160,), width=2)
    # circuit traces
    for i in range(6):
        y = y0 + 18 + i * 10
        draw.line((x0 + 120 + i * 40, y, x1 - 30 - i * 18, y), fill=accent + (35,), width=1)
    for i in range(8):
        x = x0 + 180 + i * 70
        draw.line((x, y0 + 12, x + 28, y0 + 12), fill=accent + (50,), width=1)
        draw.ellipse((x + 26, y0 + 9, x + 32, y0 + 15), outline=accent + (70,), width=1)


def glass_panel(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    accent: tuple[int, int, int],
    radius: int = 12,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    x0, y0, x1, y1 = box
    # soft outer glow
    glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.rounded_rectangle(box, radius=radius, outline=accent + (70,), width=3)
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(6)))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rounded_rectangle(box, radius=radius, fill=(12, 24, 38, 200), outline=accent + (140,), width=1)
    draw.rectangle((x0, y0 + 8, x0 + 5, y1 - 8), fill=accent + (230,))
    # top highlight
    draw.line((x0 + 14, y0 + 1, x1 - 14, y0 + 1), fill=accent + (90,), width=1)


def progress_bar(
    draw: Any,
    box: tuple[int, int, int, int],
    pct: float,
    *,
    accent: tuple[int, int, int],
    height: int = 10,
) -> None:
    x0, y0, x1, _ = box
    y1 = y0 + height
    draw.rounded_rectangle((x0, y0, x1, y1), radius=height // 2, fill=(28, 40, 54, 255))
    fill_w = int((x1 - x0) * max(0.0, min(1.0, pct / 100.0)))
    if fill_w > 4:
        draw.rounded_rectangle((x0, y0, x0 + fill_w, y1), radius=height // 2, fill=accent + (255,))
        # glow tip
        tip = x0 + fill_w
        draw.ellipse((tip - 6, y0 - 2, tip + 2, y1 + 2), fill=accent + (180,))


def segmented_bar(
    draw: Any,
    box: tuple[int, int, int, int],
    pct: float,
    *,
    accent: tuple[int, int, int],
    segments: int = 20,
) -> None:
    x0, y0, x1, y1 = box
    total = max(1, x1 - x0)
    gap = 2
    seg_w = max(3, (total - gap * (segments - 1)) // segments)
    filled = int(segments * max(0.0, min(1.0, pct / 100.0)))
    for i in range(segments):
        sx = x0 + i * (seg_w + gap)
        color = accent if i < filled else (40, 52, 66)
        alpha = 255 if i < filled else 180
        draw.rounded_rectangle((sx, y0, sx + seg_w, y1), radius=2, fill=color + (alpha,))


def badge(
    draw: Any,
    text: str,
    xy: tuple[int, int],
    *,
    accent: tuple[int, int, int],
    fill_bg: bool = True,
) -> tuple[int, int]:
    f = font(13, bold=True)
    tw = int(text_width(draw, text, f))
    pad_x, pad_y = 12, 6
    x, y = xy
    box = (x, y, x + tw + pad_x * 2, y + 26)
    if fill_bg:
        draw.rounded_rectangle(box, radius=8, fill=accent + (40,), outline=accent + (200,), width=1)
    else:
        draw.rounded_rectangle(box, radius=8, outline=accent + (200,), width=1)
    draw.text((x + pad_x, y + pad_y), text, font=f, fill=accent)
    return box[2], box[3]


def paste_emblem(image: Image.Image, key: str, box: tuple[int, int, int, int], opacity: float = 1.0) -> None:
    emblem = asset_image(key)
    if emblem is None:
        return
    if opacity < 1.0:
        emblem = emblem.copy()
        a = emblem.getchannel("A").point(lambda v: int(v * opacity))
        emblem.putalpha(a)
    paste_contain(image, emblem, box)


def metal_header(image: Image.Image, height: int = 88, accent: tuple[int, int, int] = CYAN) -> None:
    w = image.width
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(height):
        t = y / max(1, height - 1)
        c = tuple(int(28 * (1 - t) + 14 * t) for _ in range(3))
        draw.line((0, y, w, y), fill=c + (255,))
    draw.rectangle((0, 0, w, 4), fill=accent + (220,))
    draw.line((0, height - 1, w, height - 1), fill=(70, 90, 110, 180), width=1)


def cockpit_frame(image: Image.Image) -> None:
    """Dark vignette corners for map cockpit look."""
    w, h = image.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # top/bottom bars
    draw.rectangle((0, 0, w, 70), fill=(4, 8, 14, 180))
    draw.rectangle((0, h - 120, w, h), fill=(4, 8, 14, 210))
    # side vignette
    for i in range(40):
        a = int(120 * (1 - i / 40))
        draw.rectangle((i, 70, i + 1, h - 120), fill=(0, 0, 0, a))
        draw.rectangle((w - 1 - i, 70, w - i, h - 120), fill=(0, 0, 0, a))
    image.alpha_composite(overlay)
