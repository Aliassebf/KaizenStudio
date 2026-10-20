from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "kaizen_studio.ico"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    scale = 4
    size = 256 * scale
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 10 * scale
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=54 * scale,
        fill="#173a5e",
        outline="#57c8b0",
        width=7 * scale,
    )

    font_path = Path(r"C:\Windows\Fonts\arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 104 * scale)
    letters = "KS"
    bounds = draw.textbbox((0, 0), letters, font=font, stroke_width=0)
    text_width = bounds[2] - bounds[0]
    text_height = bounds[3] - bounds[1]
    draw.text(
        ((size - text_width) / 2 - bounds[0], (size - text_height) / 2 - bounds[1] - 4 * scale),
        letters,
        font=font,
        fill="white",
    )
    image.resize((256, 256), Image.Resampling.LANCZOS).save(
        OUTPUT,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Icône créée : {OUTPUT}")


if __name__ == "__main__":
    main()
