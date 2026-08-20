"""Prepare a clean face plate and independent eyebrow layers."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
MASTER_PATH = ROOT / "pet.png"
CLEAN_GENERATED_PATH = Path(
    r"C:\Users\Lenovo\.codex\generated_images\01a015af-a021-74c1-b0bc-c2c0f547cade"
    r"\exec-e614b490-2b15-45ca-b40a-9f538de3d592.png"
)
OUTPUT_DIR = ROOT / "assets" / "character" / "face"


def align_to_master(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGB")
    if abs(image.width - size[0]) > 2 or abs(image.height - size[1]) > 2:
        raise ValueError(f"generated face canvas {image.size} differs too much from {size}")
    crop_left = max((image.width - size[0]) // 2, 0)
    crop_top = max((image.height - size[1]) // 2, 0)
    image = image.crop(
        (
            crop_left,
            crop_top,
            crop_left + min(image.width, size[0]),
            crop_top + min(image.height, size[1]),
        )
    )
    canvas = Image.new("RGB", size, (0, 0, 0))
    canvas.paste(image, (max((size[0] - image.width) // 2, 0), 0))
    return canvas


def rounded_mask(size: tuple[int, int], boxes: list[tuple[int, int, int, int]]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.rounded_rectangle(box, radius=28, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=1))


def draw_brow(
    size: tuple[int, int],
    start: tuple[float, float],
    control: tuple[float, float],
    end: tuple[float, float],
) -> Image.Image:
    """Draw a tapered, softly painted quadratic brow on a transparent canvas."""
    points = []
    for index in range(31):
        t = index / 30
        inv = 1 - t
        x = inv * inv * start[0] + 2 * inv * t * control[0] + t * t * end[0]
        y = inv * inv * start[1] + 2 * inv * t * control[1] + t * t * end[1]
        points.append((round(x), round(y)))

    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    main = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    main_draw = ImageDraw.Draw(main)
    for index, (first, second) in enumerate(zip(points, points[1:])):
        center_weight = 1 - abs((index + 0.5) / 30 - 0.5) * 2
        shadow_width = round(5 + center_weight * 13)
        main_width = round(3 + center_weight * 8)
        shadow_draw.line((first, second), fill=(74, 47, 43, 150), width=shadow_width)
        main_draw.line((first, second), fill=(112, 76, 66, 225), width=main_width)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=1.1))
    shadow.alpha_composite(main)
    return shadow


def main() -> None:
    master = Image.open(MASTER_PATH).convert("RGBA")
    clean_rgb = align_to_master(Image.open(CLEAN_GENERATED_PATH), master.size)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Covers all reusable facial-feature zones while leaving hair and face outline alone.
    face_mask = rounded_mask(
        master.size,
        [
            (322, 322, 525, 505),
            (545, 286, 755, 475),
            (438, 468, 648, 558),
        ],
    )
    clean_plate = clean_rgb.convert("RGBA")
    clean_plate.putalpha(face_mask)
    clean_plate.save(OUTPUT_DIR / "face_clean_plate_v1.png")

    clean_full_rgb = Image.composite(clean_rgb, master.convert("RGB"), face_mask)
    clean_full = Image.merge("RGBA", (*clean_full_rgb.split(), master.getchannel("A")))
    clean_full.save(OUTPUT_DIR / "pet_face_clean_v1.png")
    clean_full.crop((320, 285, 720, 445)).resize(
        (1200, 480), Image.Resampling.LANCZOS
    ).save(ROOT / "assets" / "character" / "preview_clean_brow_area_v1.png")

    brow_screen_left = draw_brow(
        master.size,
        (360, 385),
        (405, 335),
        (469, 363),
    )
    brow_screen_right = draw_brow(
        master.size,
        (552, 340),
        (608, 290),
        (674, 320),
    )
    brow_screen_left.save(OUTPUT_DIR / "brow_screen_left_v1.png")
    brow_screen_right.save(OUTPUT_DIR / "brow_screen_right_v1.png")
    brow_preview = clean_full.copy()
    brow_preview.alpha_composite(brow_screen_left)
    brow_preview.alpha_composite(brow_screen_right)
    brow_preview.save(ROOT / "assets" / "character" / "preview_face_brows_v1.png")

    print(f"Prepared clean face and eyebrow layers in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
