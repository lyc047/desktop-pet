"""Prepare already-transparent edge-pose PNGs without redrawing their pixels."""

from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "assets" / "character" / "edge"
ASSETS = {
    "left": (ROOT / "left.png", "cling_left_v1.png"),
    "right": (ROOT / "right.png", "peek_right_v1.png"),
}


def prepare(source_path: Path) -> Image.Image:
    source = Image.open(source_path).convert("RGBA")
    rgba = np.array(source)
    alpha = rgba[:, :, 3]
    if alpha.max() == 0:
        raise RuntimeError(f"{source_path.name} has no visible alpha")

    # The generated files already contain a correct subject alpha mask. Their
    # fully transparent pixels still carry dark preview RGB, which some viewers
    # display as a black background. Zero those invisible RGB values and retain
    # the original soft edge alpha unchanged.
    rgba[alpha == 0, :3] = 0
    visible = np.argwhere(alpha > 0)
    y1, x1 = visible.min(axis=0)
    y2, x2 = visible.max(axis=0) + 1
    padding = 10
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(source.width, x2 + padding)
    y2 = min(source.height, y2 + padding)
    return Image.fromarray(rgba[y1:y2, x1:x2], "RGBA")


def checker_preview(image: Image.Image) -> Image.Image:
    pixels = np.empty((image.height, image.width, 4), dtype=np.uint8)
    yy, xx = np.indices((image.height, image.width))
    dark = ((xx // 32 + yy // 32) % 2) == 0
    pixels[:, :, 3] = 255
    pixels[:, :, :3] = (232, 232, 232)
    pixels[dark, :3] = (190, 190, 190)
    checker = Image.fromarray(pixels, "RGBA")
    checker.alpha_composite(image)
    return checker


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (source_path, output_name) in ASSETS.items():
        result = prepare(source_path)
        destination = OUTPUT_DIR / output_name
        result.save(destination)
        checker_preview(result).save(OUTPUT_DIR / f"preview_{name}_checker.png")
        print(f"{name}: {destination} {result.size}")


if __name__ == "__main__":
    main()
