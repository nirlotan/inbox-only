"""Draws the Inbox Only icon: a chat bubble on a calm gradient.

    python tools/make-icons.py

Writes the iOS app icon (full-bleed, no alpha; iOS rounds the corners) and
the Safari extension icons (rounded, transparent corners).
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SIZE = 1024
TOP, BOTTOM = (79, 70, 229), (20, 184, 166)  # indigo -> teal


def art() -> Image.Image:
    s = SIZE * 2  # draw at 2x, downsample for smooth edges
    img = Image.new("RGB", (s, s))
    px = img.load()
    for y in range(s):
        for x in range(s):
            t = (x * 0.35 + y * 0.65) / s
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))

    d = ImageDraw.Draw(img)
    white = (255, 255, 255)
    # Bubble body and tail.
    d.rounded_rectangle((0.20 * s, 0.24 * s, 0.80 * s, 0.68 * s), radius=0.14 * s, fill=white)
    d.polygon([(0.30 * s, 0.62 * s), (0.27 * s, 0.80 * s), (0.46 * s, 0.66 * s)], fill=white)
    # Typing dots.
    r = 0.045 * s
    for cx in (0.37, 0.50, 0.63):
        c = (cx * s, 0.46 * s)
        d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=(67, 97, 214))
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def rounded(img: Image.Image) -> Image.Image:
    s = img.width * 4
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=0.225 * s, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask.resize(img.size, Image.LANCZOS))
    return out


def main() -> None:
    base = art()
    app_icon = ROOT / "ios/App/Assets.xcassets/AppIcon.appiconset/icon-1024.png"
    app_icon.parent.mkdir(parents=True, exist_ok=True)
    base.save(app_icon)

    ext = rounded(base)
    for size in (48, 96, 128, 256, 512):
        ext.resize((size, size), Image.LANCZOS).save(ROOT / f"extension/icon-{size}.png")

    # Install page: the over-the-air manifest wants 57px and 512px images.
    for size in (57, 180, 512):
        base.resize((size, size), Image.LANCZOS).save(ROOT / f"docs/icon-{size}.png")
    print("icons written")


if __name__ == "__main__":
    main()
