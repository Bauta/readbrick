"""Render web/icons/icon.svg into the PWA raster outputs.

Outputs:
  icon-192.png            — transparent bg, full-bleed glyph (Android default)
  icon-512.png            — transparent bg, full-bleed glyph (Android splash)
  icon-maskable-512.png   — opaque cream bg, glyph at 80% size (Android adaptive)
  apple-touch-icon.png    — opaque cream bg, glyph at 88% size (iOS home screen)

Run: python scripts/build-icons.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

try:
    import cairosvg
    from PIL import Image
except ImportError as e:
    sys.stderr.write(
        f"Missing dep ({e.name}). Install the dev extra:\n"
        "  source .venv/bin/activate && pip install -e .[dev]\n"
    )
    raise SystemExit(1)

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "web" / "icons" / "icon.svg"
OUT_DIR = ROOT / "web" / "icons"

# Cream background for opaque variants — matches --bg in web/style.css light theme.
BG_CREAM = (251, 250, 247, 255)


def render_svg_to_image(size: int) -> Image.Image:
    """Render the SVG at `size`×`size` into a transparent-bg PIL Image."""
    png_bytes = cairosvg.svg2png(
        url=str(SVG_PATH), output_width=size, output_height=size,
    )
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def composite_on_cream(glyph: Image.Image, canvas_size: int, glyph_scale: float) -> Image.Image:
    """Paste the glyph (scaled) onto an opaque cream canvas."""
    canvas = Image.new("RGBA", (canvas_size, canvas_size), BG_CREAM)
    inner = int(canvas_size * glyph_scale)
    scaled = glyph.resize((inner, inner), Image.LANCZOS)
    offset = (canvas_size - inner) // 2
    canvas.paste(scaled, (offset, offset), scaled)
    return canvas.convert("RGB")  # drop alpha — opaque variants are RGB


def main() -> None:
    if not SVG_PATH.exists():
        sys.stderr.write(f"Source SVG not found: {SVG_PATH}\n")
        raise SystemExit(1)

    # Transparent-bg variants: render SVG directly at target size.
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png")]:
        img = render_svg_to_image(size)
        out = OUT_DIR / name
        img.save(out, "PNG")
        print(f"wrote {out.relative_to(ROOT)}")

    # Opaque-bg variants: render SVG at a high source size, scale + composite.
    glyph_hires = render_svg_to_image(1024)

    maskable = composite_on_cream(glyph_hires, canvas_size=512, glyph_scale=0.80)
    maskable.save(OUT_DIR / "icon-maskable-512.png", "PNG")
    print("wrote web/icons/icon-maskable-512.png")

    apple = composite_on_cream(glyph_hires, canvas_size=180, glyph_scale=0.88)
    apple.save(OUT_DIR / "apple-touch-icon.png", "PNG")
    print("wrote web/icons/apple-touch-icon.png")


if __name__ == "__main__":
    main()
