"""Original placeholder stills for The Midnight Archive.

No stock photography is used. Every image is drawn locally with Pillow from the
storyboard's visual language, so the result is licence-clean and reproducible.
The renderer applies slow zoom/pan, so compositions keep their subject away from
the outer 8% and the subtitle band.
"""

from __future__ import annotations

import math
import random
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from midnight_archive.config import Settings
from midnight_archive.models import Scene, Storyboard

W, H = 1350, 2400

INK = (9, 14, 18)
TEAL_BLACK = (8, 18, 23)
TEAL = (24, 52, 59)
TEAL_LIGHT = (52, 88, 94)
AMBER = (214, 146, 68)
AMBER_PALE = (244, 197, 126)
PAPER = (206, 197, 174)
PAPER_BRIGHT = (233, 226, 207)
RED_PENCIL = (135, 46, 40)
GREY = (108, 108, 103)


def _rgb(color: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    return (color[0], color[1], color[2], alpha)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(
    width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    t = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    arr = np.zeros((height, width, 3), dtype=np.float32)
    for channel in range(3):
        arr[:, :, channel] = top[channel] + (bottom[channel] - top[channel]) * t[:, :, 0]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _glow(
    image: Image.Image,
    center: tuple[float, float],
    radius: float,
    color: tuple[int, int, int],
    strength: float = 0.75,
) -> Image.Image:
    """Screen a soft radial light into the frame."""

    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32) / 255.0
    yy, xx = np.mgrid[0 : rgb.height, 0 : rgb.width]
    distance = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2) / max(1.0, radius)
    mask = np.clip(1.0 - distance, 0.0, 1.0) ** 2.2
    mask = (mask * strength)[..., None]
    tint = np.asarray(color, dtype=np.float32) / 255.0
    lit = 1.0 - (1.0 - arr) * (1.0 - tint * mask)
    result = Image.fromarray((np.clip(lit, 0, 1) * 255).astype(np.uint8), "RGB")
    if alpha is not None:
        result = result.convert("RGBA")
        result.putalpha(alpha)
    return result


def _vignette(image: Image.Image, amount: float = 0.72) -> Image.Image:
    yy, xx = np.mgrid[0 : image.height, 0 : image.width]
    cx, cy = image.width / 2, image.height * 0.46
    distance = np.sqrt(((xx - cx) / (image.width * 0.72)) ** 2 + ((yy - cy) / (image.height * 0.72)) ** 2)
    mask = np.clip(1.0 - amount * distance**2.1, 0.16, 1.0)[..., None]
    arr = np.asarray(image, dtype=np.float32) * mask
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _grain(image: Image.Image, seed: int, amount: float = 5.5) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = np.asarray(image, dtype=np.float32)
    noise = rng.normal(0.0, amount, arr.shape[:2])[..., None]
    arr = arr + noise
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def _blur(image: Image.Image, radius: float) -> Image.Image:
    return image.filter(ImageFilter.GaussianBlur(radius))


@lru_cache(maxsize=32)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    tracking: int = 0,
) -> None:
    if tracking <= 0:
        draw.text(xy, text, font=font, fill=fill)
        return
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        width = draw.textlength(char, font=font)
        x += width + tracking


def _paste_paper(
    base: Image.Image,
    paper: Image.Image,
    position: tuple[int, int],
    angle: float = 0.0,
    shadow: int = 70,
) -> None:
    rotated = paper.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    alpha = rotated.getchannel("A")
    black = Image.new("RGBA", rotated.size, (0, 0, 0, shadow))
    black.putalpha(alpha.filter(ImageFilter.GaussianBlur(14)).point(lambda v: int(v * shadow / 255)))
    base.alpha_composite(black, (position[0] + 10, position[1] + 18))
    base.alpha_composite(rotated, position)


def _paper_texture(width: int, height: int, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = np.zeros((height, width, 4), dtype=np.float32)
    arr[:, :, :3] = PAPER
    grain = rng.normal(0, 3.3, (height, width, 1))
    arr[:, :, :3] += grain
    arr[:, :, 3] = 255
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA")


def _fit_tracking_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    max_size: int,
    max_width: float,
    tracking: int,
) -> tuple[ImageFont.ImageFont, int]:
    """Pick the largest font/tracking pair that fits a masthead."""

    size = max_size
    while size > 10:
        font = _font(font_path, size)
        total = sum(draw.textlength(char, font=font) + tracking for char in text) - tracking
        if total <= max_width:
            return font, tracking
        size -= 1
    return _font(font_path, 10), 0


def _newspaper(width: int, height: int, seed: int, masthead: bool = True) -> Image.Image:
    paper = _paper_texture(width, height, seed)
    draw = ImageDraw.Draw(paper)
    font_path = "assets/fonts/Montserrat-Bold.ttf"
    if masthead:
        masthead_font, tracking = _fit_tracking_text(
            draw,
            "THE MIDNIGHT ARCHIVE",
            font_path,
            max(12, int(height * 0.050)),
            width * 0.74,
            1,
        )
        _text(draw, (width * 0.08, height * 0.045), "THE MIDNIGHT ARCHIVE", masthead_font, _rgb((38, 35, 30)), tracking=tracking)
        draw.line((width * 0.08, height * 0.115, width * 0.92, height * 0.115), fill=_rgb((60, 56, 48), 160), width=2)
    columns = 3
    top = height * 0.17 if masthead else height * 0.08
    column_width = (width * 0.84) / columns
    rng = random.Random(seed)
    for column in range(columns):
        x = width * 0.08 + column * column_width
        headline_h = rng.randint(int(height * 0.035), int(height * 0.065))
        draw.rectangle(
            (x, top, x + column_width * 0.78, top + headline_h),
            fill=_rgb((68, 63, 54), 190),
        )
        y = top + headline_h * 1.7
        while y < height * 0.94:
            line_width = column_width * rng.uniform(0.55, 0.92)
            line_height = max(2, int(height * 0.004))
            draw.rectangle((x, y, x + line_width, y + line_height), fill=_rgb((95, 88, 76), 105))
            y += line_height * 2.8
    return paper


def _doormat(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=8, fill=_rgb((39, 35, 27)))
    for offset in range(12, x2 - x1, 24):
        draw.line((x1 + offset, y1 + 8, x1 + offset, y2 - 8), fill=_rgb((63, 56, 40), 120), width=3)
    draw.rectangle((x1 + 12, y1 + 12, x2 - 12, y2 - 12), outline=_rgb((104, 85, 51), 160), width=3)


def _corridor_doormat(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, TEAL_BLACK, (3, 6, 8)).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    # Wallpaper and perspective corridor.
    vanishing = (W * 0.54, H * 0.46)
    draw.polygon(
        [(0, 0), (W, 0), (W * 0.86, H * 0.55), (W * 0.14, H * 0.55)],
        fill=_rgb((38, 43, 31)),
    )
    for x in range(-200, W + 200, 95):
        draw.line((x, 0, vanishing[0] + (x - W / 2) * 0.24, H * 0.54), fill=_rgb((61, 59, 32), 70), width=2)
    # Ceiling and floor.
    draw.polygon([(0, 0), (W * 0.14, H * 0.54), (W * 0.86, H * 0.54), (W, 0)], fill=_rgb((10, 16, 18)))
    draw.polygon([(0, H), (W * 0.14, H * 0.54), (W * 0.86, H * 0.54), (W, H)], fill=_rgb((16, 20, 21)))
    for index in range(1, 8):
        y = H * 0.54 + (H * 0.46) * (index / 8) ** 1.7
        draw.line((0, y, W, y), fill=_rgb((29, 32, 31), 110), width=2)
    # Doors.
    for side in (-1, 1):
        x = W * 0.5 + side * W * 0.38
        width = W * 0.19
        height = H * 0.33
        top = H * 0.224
        draw.rectangle((x - width / 2, top, x + width / 2, top + height), fill=_rgb((15, 20, 20)))
        draw.rectangle((x - width / 2 + 8, top + 8, x + width / 2 - 8, top + height), outline=_rgb((71, 66, 45), 130), width=3)
        draw.ellipse((x + width * 0.28, top + height * 0.52, x + width * 0.28 + 12, top + height * 0.52 + 12), fill=_rgb(AMBER, 190))
    # Ceiling light with sodium halo.
    base = _glow(base, (W * 0.52, H * 0.11), W * 0.48, (185, 119, 47), 0.65)
    draw = ImageDraw.Draw(base, "RGBA")
    draw.rectangle((W * 0.44, H * 0.08, W * 0.60, H * 0.092), fill=_rgb((250, 216, 160), 220))
    # Doormat and newspaper.
    mat = (W * 0.27, H * 0.555, W * 0.73, H * 0.685)
    _doormat(draw, tuple(int(v) for v in mat))
    paper = _newspaper(int(W * 0.32), int(H * 0.155), seed)
    paper = paper.rotate(-3, expand=True, resample=Image.Resampling.BICUBIC)
    _paste_paper(base, paper, (int(W * 0.34), int(H * 0.575)), angle=4, shadow=100)
    # Dust and damp.
    rng = np.random.default_rng(seed + 4)
    for _ in range(80):
        x, y = rng.uniform(0, W), rng.uniform(H * 0.3, H)
        draw.ellipse((x, y, x + 2, y + 2), fill=_rgb((220, 196, 160), int(rng.uniform(12, 45))))
    return base.convert("RGB")


def _newsprint_macro(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, (17, 22, 22), (4, 7, 8)).convert("RGBA")
    paper = _newspaper(int(W * 1.08), int(H * 0.92), seed)
    paper = paper.rotate(-4, expand=True, resample=Image.Resampling.BICUBIC)
    base.paste(paper, (int(-W * 0.02), int(H * 0.03)), paper)
    draw = ImageDraw.Draw(base, "RGBA")
    # Red pencil circle around one column, and a fingertip shadow.
    center = (W * 0.56, H * 0.48)
    draw.ellipse(
        (center[0] - 210, center[1] - 145, center[0] + 210, center[1] + 170),
        outline=_rgb(RED_PENCIL, 185),
        width=7,
    )
    draw.arc(
        (center[0] - 198, center[1] - 132, center[0] + 198, center[1] + 158),
        5,
        300,
        fill=_rgb(RED_PENCIL, 120),
        width=3,
    )
    # A soft shadow from the reading hand, without an anatomical silhouette.
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    sdraw.ellipse((W * 0.58, H * 0.72, W * 0.98, H * 1.02), fill=(0, 0, 0, 130))
    base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(90)))
    base = _glow(base, (W * 0.44, H * 0.28), W * 0.72, (225, 167, 92), 0.50)
    draw = ImageDraw.Draw(base, "RGBA")
    draw.ellipse((W * 0.48, H * 0.18, W * 0.50, H * 0.185), fill=_rgb((255, 238, 201), 230))
    return base.convert("RGB")


def _hotel_room(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, (13, 24, 29), (5, 8, 10)).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    # Window with rain and city bokeh.
    window = (W * 0.46, H * 0.14, W * 0.88, H * 0.57)
    draw.rectangle(window, fill=_rgb((24, 45, 54)))
    draw.line((window[0], window[1], window[2], window[1]), fill=_rgb((73, 89, 91), 220), width=16)
    draw.line((window[0], window[1], window[0], window[3]), fill=_rgb((73, 89, 91), 220), width=16)
    draw.line((window[2], window[1], window[2], window[3]), fill=_rgb((73, 89, 91), 220), width=14)
    draw.line(((window[0] + window[2]) / 2, window[1], (window[0] + window[2]) / 2, window[3]), fill=_rgb((64, 78, 80), 210), width=10)
    draw.line((window[0], (window[1] + window[3]) / 2, window[2], (window[1] + window[3]) / 2), fill=_rgb((64, 78, 80), 210), width=10)
    rng = random.Random(seed)
    for _ in range(90):
        x = rng.uniform(window[0] + 15, window[2] - 15)
        y = rng.uniform(window[1] + 15, window[3] - 15)
        radius = rng.uniform(2, 10)
        color = (188, 151, 91) if rng.random() > 0.35 else (90, 131, 133)
        draw.ellipse((x, y, x + radius, y + radius), fill=_rgb(color, rng.randint(40, 150)))
    for _ in range(55):
        x = rng.uniform(window[0] + 10, window[2] - 10)
        y = rng.uniform(window[1] + 10, window[3] - 30)
        draw.line((x, y, x - 3, y + rng.uniform(20, 55)), fill=_rgb((155, 177, 175), 45), width=2)
    # Bed, lamp, clock.
    draw.rectangle((W * 0.02, H * 0.50, W * 0.43, H * 0.80), fill=_rgb((22, 25, 25)))
    draw.rectangle((W * 0.02, H * 0.46, W * 0.43, H * 0.53), fill=_rgb((37, 38, 34)))
    draw.rounded_rectangle((W * 0.31, H * 0.43, W * 0.43, H * 0.50), radius=15, fill=_rgb((58, 56, 48)))
    draw.rectangle((W * 0.06, H * 0.77, W * 0.38, H * 0.80), fill=_rgb((10, 15, 16)))
    # Lamp on nightstand, foreground left.
    base = _glow(base, (W * 0.18, H * 0.52), W * 0.30, (211, 143, 66), 0.75)
    draw = ImageDraw.Draw(base, "RGBA")
    draw.polygon([(W * 0.12, H * 0.60), (W * 0.24, H * 0.60), (W * 0.21, H * 0.52), (W * 0.15, H * 0.52)], fill=_rgb((234, 206, 158), 220))
    draw.line((W * 0.18, H * 0.60, W * 0.18, H * 0.70), fill=_rgb((60, 53, 41), 255), width=8)
    # Clock red digits.
    draw.rounded_rectangle((W * 0.46, H * 0.66, W * 0.64, H * 0.73), radius=12, fill=_rgb((8, 8, 8)))
    clock_font = _font("assets/fonts/Montserrat-Bold.ttf", int(H * 0.045))
    draw.text((W * 0.505, H * 0.665), "3:00", font=clock_font, fill=_rgb((213, 55, 42), 240))
    # Seated figure on bed edge, very dark.
    draw.ellipse((W * 0.33, H * 0.34, W * 0.39, H * 0.41), fill=_rgb((7, 10, 11)))
    draw.polygon([(W * 0.30, H * 0.40), (W * 0.42, H * 0.40), (W * 0.44, H * 0.65), (W * 0.28, H * 0.65)], fill=_rgb((9, 12, 13)))
    draw.line((W * 0.28, H * 0.48, W * 0.22, H * 0.60), fill=_rgb((8, 11, 12)), width=22)
    draw.line((W * 0.43, H * 0.48, W * 0.48, H * 0.60), fill=_rgb((8, 11, 12)), width=22)
    return base.convert("RGB")


def _reception_desk(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, (24, 38, 42), (5, 8, 9)).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    # Frosted dawn door.
    base = _glow(base, (W * 0.28, H * 0.34), W * 0.55, (177, 169, 135), 0.35)
    draw = ImageDraw.Draw(base, "RGBA")
    draw.rounded_rectangle((W * 0.04, H * 0.10, W * 0.43, H * 0.63), radius=8, fill=_rgb((49, 65, 65), 180), outline=_rgb((84, 83, 66), 220), width=9)
    for x in (W * 0.17, W * 0.30):
        draw.line((x, H * 0.11, x, H * 0.62), fill=_rgb((72, 83, 80), 170), width=5)
    # Key cubbies behind desk.
    for row in range(4):
        for column in range(7):
            x = W * 0.47 + column * W * 0.068
            y = H * 0.16 + row * H * 0.072
            draw.rectangle((x, y, x + W * 0.055, y + H * 0.050), fill=_rgb((20, 25, 24)), outline=_rgb((73, 62, 44), 130), width=2)
            draw.line((x + 5, y + 12, x + W * 0.047, y + 12), fill=_rgb((117, 100, 67), 120), width=2)
    # Clock above cubbies.
    draw.ellipse((W * 0.735, H * 0.075, W * 0.835, H * 0.165), fill=_rgb((28, 29, 25)), outline=_rgb((129, 104, 61), 230), width=5)
    draw.line((W * 0.785, H * 0.12, W * 0.785, H * 0.092), fill=_rgb((214, 198, 161), 220), width=4)
    draw.line((W * 0.785, H * 0.12, W * 0.813, H * 0.13), fill=_rgb((214, 198, 161), 220), width=4)
    # Desk.
    draw.rectangle((0, H * 0.62, W, H), fill=_rgb((34, 25, 18)))
    draw.rectangle((0, H * 0.62, W, H * 0.65), fill=_rgb((85, 63, 38)))
    draw.rectangle((W * 0.52, H * 0.67, W * 0.90, H * 0.96), outline=_rgb((20, 15, 11), 160), width=4)
    # Brass bell, newspaper, lamp.
    glow = _glow(base, (W * 0.22, H * 0.60), W * 0.28, (211, 144, 65), 0.5)
    draw = ImageDraw.Draw(glow, "RGBA")
    draw.ellipse((W * 0.18, H * 0.70, W * 0.27, H * 0.735), fill=_rgb((184, 139, 64), 225))
    draw.arc((W * 0.17, H * 0.675, W * 0.28, H * 0.735), 180, 360, fill=_rgb((238, 194, 111), 230), width=7)
    draw.ellipse((W * 0.215, H * 0.665, W * 0.235, H * 0.680), fill=_rgb((238, 194, 111), 220))
    paper = _newspaper(int(W * 0.29), int(H * 0.14), seed + 3)
    _paste_paper(glow, paper, (int(W * 0.42), int(H * 0.635)), angle=-5, shadow=110)
    # Clerk silhouette.
    draw.ellipse((W * 0.18, H * 0.32, W * 0.26, H * 0.41), fill=_rgb((10, 14, 14)))
    draw.polygon([(W * 0.15, H * 0.42), (W * 0.29, H * 0.42), (W * 0.31, H * 0.64), (W * 0.13, H * 0.64)], fill=_rgb((12, 16, 16)))
    return glow.convert("RGB")


def _paper_floor(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, (13, 17, 18), (4, 6, 7)).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")
    rng = random.Random(seed)
    # Floorboards.
    for y in range(int(H * 0.05), H, 150):
        draw.line((0, y, W, y), fill=_rgb((27, 34, 35), 120), width=3)
    for x in range(0, W, 270):
        draw.line((x, 0, x, H), fill=_rgb((22, 28, 29), 70), width=2)
    # Grid of papers, each slightly rotated.
    for row in range(5):
        for column in range(4):
            width = int(W * 0.27)
            height = int(H * 0.15)
            paper = _newspaper(width, height, seed + row * 7 + column, masthead=(row == 0))
            x = int(W * 0.04 + column * W * 0.245 + rng.uniform(-12, 12))
            y = int(H * 0.16 + row * H * 0.145 + rng.uniform(-10, 10))
            _paste_paper(base, paper, (x, y), angle=rng.uniform(-7, 7), shadow=70)
    # Single hard lamp pool over the centre.
    base = _glow(base, (W * 0.52, H * 0.45), W * 0.42, (221, 161, 83), 0.62)
    draw = ImageDraw.Draw(base, "RGBA")
    # Kneeling figure silhouette.
    cx = W * 0.52
    draw.ellipse((cx - 52, H * 0.33, cx + 52, H * 0.40), fill=_rgb((7, 10, 11)))
    draw.polygon(
        [(cx - 105, H * 0.40), (cx + 105, H * 0.40), (cx + 140, H * 0.58), (cx - 140, H * 0.58)],
        fill=_rgb((8, 11, 12)),
    )
    draw.polygon(
        [(cx - 140, H * 0.58), (cx + 140, H * 0.58), (cx + 190, H * 0.66), (cx - 190, H * 0.66)],
        fill=_rgb((9, 12, 13)),
    )
    draw.ellipse((cx - 125, H * 0.55, cx - 45, H * 0.61), fill=_rgb((11, 14, 15)))
    draw.ellipse((cx + 45, H * 0.55, cx + 125, H * 0.61), fill=_rgb((11, 14, 15)))
    return base.convert("RGB")


def _crossword_photo(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, (25, 34, 34), (6, 9, 10)).convert("RGBA")
    # Window light streak.
    base = _glow(base, (W * 0.22, H * 0.18), W * 0.55, (159, 170, 157), 0.35)
    draw = ImageDraw.Draw(base, "RGBA")
    # Desk surface, raised so the props sit in the middle of the vertical frame.
    draw.rectangle((0, H * 0.43, W, H), fill=_rgb((35, 27, 19)))
    draw.line((0, H * 0.43, W, H * 0.43), fill=_rgb((88, 67, 43), 160), width=5)
    # Crossword sheet.
    sheet = _paper_texture(int(W * 0.49), int(H * 0.33), seed)
    sdraw = ImageDraw.Draw(sheet)
    margin = int(W * 0.035)
    cell = int(W * 0.055)
    for row in range(8):
        for column in range(8):
            x = margin + column * cell
            y = margin + row * cell
            filled = (row * 7 + column * 5 + seed) % 4 == 0
            sdraw.rectangle((x, y, x + cell, y + cell), fill=_rgb((70, 65, 56), 210) if filled else None, outline=_rgb((96, 89, 76), 120), width=1)
            if not filled and (row + column) % 3 == 0:
                sdraw.line((x + 8, y + 18, x + cell - 8, y + 18), fill=_rgb((105, 98, 84), 120), width=2)
    # Three erased grey blocks.
    for row, column in ((2, 3), (4, 1), (5, 5)):
        x = margin + column * cell
        y = margin + row * cell
        sdraw.rectangle((x + 2, y + 2, x + cell - 2, y + cell - 2), fill=_rgb(GREY, 220))
    _paste_paper(base, sheet, (int(W * 0.07), int(H * 0.44)), angle=-4, shadow=90)
    # Framed photograph.
    frame = (W * 0.54, H * 0.37, W * 0.94, H * 0.66)
    draw = ImageDraw.Draw(base, "RGBA")
    draw.rectangle((frame[0] + 12, frame[1] + 18, frame[2] + 12, frame[3] + 18), fill=_rgb((0, 0, 0), 110))
    draw.rectangle(frame, fill=_rgb((56, 46, 32)), outline=_rgb((140, 112, 70), 220), width=12)
    inner = (frame[0] + 34, frame[1] + 34, frame[2] - 34, frame[3] - 34)
    draw.rectangle(inner, fill=_rgb((77, 78, 70)))
    draw.ellipse((inner[0] + 42, inner[1] + 55, inner[0] + 112, inner[1] + 130), fill=_rgb((45, 48, 44)))
    draw.polygon([(inner[0] + 20, inner[3] - 35), (inner[0] + 180, inner[3] - 35), (inner[0] + 140, inner[1] + 145), (inner[0] + 50, inner[1] + 145)], fill=_rgb((49, 51, 46)))
    draw.rectangle((inner[0] + 165, inner[1] + 55, inner[0] + 240, inner[1] + 135), fill=_rgb(GREY))
    # Pencil shavings.
    rng = random.Random(seed + 2)
    for _ in range(30):
        x, y = rng.uniform(W * 0.10, W * 0.52), rng.uniform(H * 0.80, H * 0.91)
        draw.arc((x, y, x + 22, y + 10), 0, 180, fill=_rgb((190, 157, 105), 130), width=2)
    return base.convert("RGB")


def _blank_page(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, (7, 12, 14), (2, 4, 5)).convert("RGBA")
    # Bare bulb and cone.
    base = _glow(base, (W * 0.52, H * 0.15), W * 0.65, (236, 191, 123), 0.55)
    draw = ImageDraw.Draw(base, "RGBA")
    draw.line((W * 0.52, 0, W * 0.52, H * 0.13), fill=_rgb((28, 27, 22)), width=4)
    draw.ellipse((W * 0.485, H * 0.125, W * 0.555, H * 0.185), fill=_rgb((255, 228, 174), 240))
    draw.ellipse((W * 0.502, H * 0.137, W * 0.538, H * 0.171), fill=_rgb((255, 248, 220), 245))
    # Table and glowing broadsheet.
    draw.rectangle((0, H * 0.64, W, H), fill=_rgb((25, 20, 15)))
    paper = Image.new("RGBA", (int(W * 0.82), int(H * 0.56)), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(paper)
    pdraw.rectangle((0, 0, paper.width, paper.height), fill=_rgb(PAPER_BRIGHT, 255))
    pdraw.rectangle((0, 0, paper.width, paper.height), outline=_rgb((255, 250, 232), 255), width=6)
    font, tracking = _fit_tracking_text(
        pdraw,
        "THE MIDNIGHT ARCHIVE",
        "assets/fonts/Montserrat-Bold.ttf",
        int(H * 0.033),
        paper.width * 0.86,
        3,
    )
    _text(pdraw, (paper.width * 0.07, paper.height * 0.055), "THE MIDNIGHT ARCHIVE", font, _rgb((33, 30, 25)), tracking=tracking)
    pdraw.line((paper.width * 0.07, paper.height * 0.115, paper.width * 0.93, paper.height * 0.115), fill=_rgb((56, 50, 40), 170), width=2)
    _paste_paper(base, paper, (int(W * 0.08), int(H * 0.68)), angle=2, shadow=120)
    # Paper glow.
    base = _glow(base, (W * 0.50, H * 0.78), W * 0.44, (225, 213, 176), 0.22)
    return base.convert("RGB")


def _face_dark(scene: Scene, seed: int, settings: Settings) -> Image.Image:
    base = _gradient(W, H, (5, 9, 11), (1, 2, 3)).convert("RGBA")
    # Dying lamp from the left.
    base = _glow(base, (W * 0.16, H * 0.49), W * 0.42, (204, 132, 55), 0.72)
    draw = ImageDraw.Draw(base, "RGBA")
    # Chair and body mass.
    draw.rectangle((W * 0.24, H * 0.72, W * 0.76, H * 0.80), fill=_rgb((12, 12, 11)))
    draw.polygon([(W * 0.28, H * 0.80), (W * 0.72, H * 0.80), (W * 0.68, H), (W * 0.32, H)], fill=_rgb((7, 8, 8)))
    # Head and shoulders; warm rim on the left only.
    head = (W * 0.38, H * 0.26, W * 0.60, H * 0.49)
    draw.rectangle((W * 0.455, H * 0.475, W * 0.535, H * 0.535), fill=_rgb((9, 10, 10)))
    draw.ellipse(head, fill=_rgb((9, 10, 10)))
    # A narrow left-facing profile: nose, lips, chin.
    draw.polygon([(W * 0.386, H * 0.355), (W * 0.365, H * 0.392), (W * 0.386, H * 0.405)], fill=_rgb((7, 8, 8)))
    draw.line((W * 0.386, H * 0.405, W * 0.401, H * 0.417), fill=_rgb((137, 94, 58), 120), width=3)
    draw.line((W * 0.401, H * 0.417, W * 0.410, H * 0.438), fill=_rgb((91, 66, 49), 100), width=2)
    draw.polygon([(W * 0.30, H * 0.52), (W * 0.68, H * 0.52), (W * 0.74, H * 0.77), (W * 0.24, H * 0.77)], fill=_rgb((8, 9, 9)))
    # Rim light crescents.
    draw.arc(head, 105, 255, fill=_rgb((208, 146, 77), 190), width=8)
    draw.line((W * 0.32, H * 0.54, W * 0.28, H * 0.70), fill=_rgb((180, 120, 59), 120), width=6)
    # Eye glint and brow.
    draw.line((W * 0.43, H * 0.365, W * 0.48, H * 0.36), fill=_rgb((153, 119, 82), 160), width=3)
    draw.ellipse((W * 0.455, H * 0.372, W * 0.462, H * 0.379), fill=_rgb((224, 190, 145), 190))
    # Blank paper in lap.
    paper = Image.new("RGBA", (int(W * 0.34), int(H * 0.16)), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(paper)
    pdraw.rectangle((0, 0, paper.width, paper.height), fill=_rgb((190, 186, 168), 255))
    for line_index in range(5):
        pdraw.rectangle(
            (
                paper.width * 0.08,
                paper.height * (0.15 + line_index * 0.09),
                paper.width * (0.70 - line_index * 0.07),
                paper.height * (0.15 + line_index * 0.09 + 0.025),
            ),
            fill=_rgb((89, 85, 74), 150),
        )
    _paste_paper(base, paper, (int(W * 0.40), int(H * 0.66)), angle=-7, shadow=80)
    # Most of the frame falls away.
    rgb = base.convert("RGB")
    arr = np.asarray(rgb, dtype=np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    distance = np.sqrt(((xx - W * 0.42) / (W * 0.55)) ** 2 + ((yy - H * 0.46) / (H * 0.55)) ** 2)
    mask = np.clip(1.0 - 0.80 * distance**1.7, 0.06, 1.0)[..., None]
    return Image.fromarray((arr * mask).clip(0, 255).astype(np.uint8), "RGB")


_COMPOSITIONS = (
    _corridor_doormat,
    _newsprint_macro,
    _hotel_room,
    _reception_desk,
    _paper_floor,
    _crossword_photo,
    _blank_page,
    _face_dark,
)

_KEYWORDS = (
    ("corridor", 0),
    ("doormat", 0),
    ("newsprint", 1),
    ("page nine", 1),
    ("hotel room", 2),
    ("reception", 3),
    ("front desk", 3),
    ("floor", 4),
    ("crossword", 5),
    ("photograph", 5),
    ("blank", 6),
    ("masthead", 6),
    ("face", 7),
    ("dark", 7),
)


def choose_composition(scene: Scene) -> int:
    haystack = f"{scene.visual} {scene.environment} {scene.camera}".lower()
    scores: dict[int, tuple[int, int]] = {}
    for keyword, index in _KEYWORDS:
        position = haystack.find(keyword)
        if position < 0:
            continue
        count, earliest = scores.get(index, (0, len(haystack)))
        scores[index] = (count + 1, min(earliest, position))
    if scores:
        # Prefer the composition with the most matching cues; break ties by
        # which cue appears first in the storyboard description.
        return max(scores.items(), key=lambda item: (item[1][0], -item[1][1]))[0]
    return (scene.scene - 1) % len(_COMPOSITIONS)


def _wordmark(image: Image.Image, settings: Settings) -> Image.Image:
    image = image.convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    font = _font(str(settings.path("assets/fonts/Montserrat-Bold.ttf")), 24)
    text = settings.name.upper()
    tracking = 7
    total = sum(draw.textlength(char, font=font) + tracking for char in text) - tracking
    _text(
        draw,
        ((W - total) / 2, H * 0.055),
        text,
        font,
        (229, 216, 188, 105),
        tracking=tracking,
    )
    draw.line((W * 0.44, H * 0.075, W * 0.56, H * 0.075), fill=(180, 143, 79, 70), width=2)
    return image.convert("RGB")


def generate_still(scene: Scene, settings: Settings, seed: int) -> Image.Image:
    composition = _COMPOSITIONS[choose_composition(scene)]
    image = composition(scene, seed, settings).convert("RGB")
    image = _vignette(image, 0.66)
    image = _grain(image, seed, 5.0)
    image = _wordmark(image, settings)
    return image


def generate_storyboard_stills(
    storyboard: Storyboard,
    settings: Settings,
    output_dir: Path,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for scene in storyboard.scenes:
        seed = 1000 + scene.scene * 97
        image = generate_still(scene, settings, seed).resize((W, H), Image.Resampling.LANCZOS)
        path = output_dir / f"scene-{scene.scene:02d}.png"
        image.save(path, "PNG", optimize=True)
        paths.append(path)
    return paths
