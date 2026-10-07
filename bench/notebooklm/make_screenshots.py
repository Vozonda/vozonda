"""Render the two screenshots of reference tray 3 (own data, no licence questions).

Deterministic: same files on every run. python3 make_screenshots.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def table_slide() -> None:
    im = Image.new("RGB", (1600, 900), "white")
    d = ImageDraw.Draw(im)
    d.text((80, 60), "Home inference: one 128 GB desktop, 35B MoE model", font=font(BOLD, 44), fill="black")
    rows = [
        ("Weights", "Decode tok/s", "First token", "Power"),
        ("BF16", "31", "1.9 s", "238 W"),
        ("FP8", "52", "1.2 s", "221 W"),
        ("NVFP4", "74", "0.8 s", "205 W"),
    ]
    y = 200
    for i, row in enumerate(rows):
        f = font(BOLD if i == 0 else FONT, 36)
        for j, cell in enumerate(row):
            d.text((80 + j * 370, y), cell, font=f, fill="black")
        y += 110
        d.line((80, y - 30, 1520, y - 30), fill=(180, 180, 180), width=2)
    d.text((80, 760), "Example figures for the comparison test: same prompts, 4k context, one user, 0.32 EUR/kWh.", font=font(FONT, 30), fill=(60, 60, 60))
    im.save(HERE / "tray3-table.png")


def bar_slide() -> None:
    im = Image.new("RGB", (1600, 900), "white")
    d = ImageDraw.Draw(im)
    d.text((80, 60), "Monthly cost: home box vs. cloud API (same 40M tokens)", font=font(BOLD, 44), fill="black")
    bars = [("Home box: power", 38), ("Home box: hardware / 36 months", 97), ("Cloud API, mid-size model", 120), ("Cloud API, frontier model", 610)]
    top, scale, x0 = 200, 1.25, 660
    for i, (label, eur) in enumerate(bars):
        y = top + i * 150
        d.rectangle((x0, y, x0 + int(eur * scale), y + 80), fill=(74, 115, 0) if i < 2 else (138, 66, 0))
        d.text((80, y + 20), label, font=font(FONT, 32), fill="black")
        d.text((x0 + 20 + int(eur * scale), y + 20), f"{eur} EUR", font=font(BOLD, 32), fill="black")
    d.text((80, 800), "Example figures for the comparison test, not a measurement.", font=font(FONT, 28), fill=(60, 60, 60))
    im.save(HERE / "tray3-costs.png")


if __name__ == "__main__":
    table_slide()
    bar_slide()
