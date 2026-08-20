"""Build blink frames with independent, synchronised eyebrow layers."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parent
MASTER = ROOT / "pet.png"
GENERATED_DIR = Path(
    r"C:\Users\Lenovo\.codex\generated_images\01a015af-a021-74c1-b0bc-c2c0f547cade"
)
BLINK_SOURCES = {
    "pet_blink_open_v1.png": (None, 0),
    "pet_blink_half_v1.png": (
        GENERATED_DIR / "exec-14b1cec1-885a-4109-a226-d9452d2e90dd.png",
        3,
    ),
    "pet_blink_almost_v1.png": (
        GENERATED_DIR / "exec-084ab172-e87c-4adc-9685-61ba086cb9ff.png",
        6,
    ),
    "pet_blink_closed_v1.png": (
        GENERATED_DIR / "exec-f8edf3ff-a680-48bf-95be-a81247a880f9.png",
        8,
    ),
}
OUTPUT_DIR = ROOT / "assets" / "character" / "expressions"
FACE_DIR = ROOT / "assets" / "character" / "face"


def align_generated(master: Image.Image, generated_path: Path) -> Image.Image:
    generated = Image.open(generated_path).convert("RGB")
    if abs(generated.width - master.width) > 2 or abs(generated.height - master.height) > 2:
        raise ValueError(f"{generated_path.name} differs too much from the master canvas")

    # Built-in generation can differ by one or two edge pixels. Center-crop/pad the
    # canvas only; never resize the drawing, because resizing would make the eyes jump.
    crop_left = max((generated.width - master.width) // 2, 0)
    crop_top = max((generated.height - master.height) // 2, 0)
    generated = generated.crop(
        (
            crop_left,
            crop_top,
            crop_left + min(generated.width, master.width),
            crop_top + min(generated.height, master.height),
        )
    )
    aligned = Image.new("RGB", master.size, (0, 0, 0))
    paste_x = max((master.width - generated.width) // 2, 0)
    paste_y = max((master.height - generated.height) // 2, 0)
    aligned.paste(generated, (paste_x, paste_y))
    return aligned


def rounded_mask(
    size: tuple[int, int], boxes: list[tuple[int, int, int, int]], radius: int
) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.rounded_rectangle(box, radius=radius, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=1))


def brow_stroke_mask(size: tuple[int, int]) -> Image.Image:
    """Cover the complete original brow strokes without touching the eyes."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    curves = [
        ((356, 387), (405, 331), (472, 365)),
        ((548, 342), (608, 286), (678, 322)),
    ]
    for start, control, end in curves:
        points = []
        for index in range(31):
            t = index / 30
            inv = 1 - t
            points.append(
                (
                    round(inv * inv * start[0] + 2 * inv * t * control[0] + t * t * end[0]),
                    round(inv * inv * start[1] + 2 * inv * t * control[1] + t * t * end[1]),
                )
            )
        # A wider, softly feathered path removes the complete painted original
        # brow. Its curve stays above the eye envelopes, so no eye pixels are lost.
        draw.line(points, fill=255, width=42, joint="curve")
    # The screen-left source eyebrow has a soft upper wash extending beyond its
    # main stroke. Clear that complete patch so it cannot read as a second brow.
    # The lower edge remains safely above the upper eyelid.
    draw.rounded_rectangle((348, 330, 486, 390), radius=24, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=1.5))


def shifted_layer(layer: Image.Image, dy: int) -> Image.Image:
    shifted = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shifted.alpha_composite(layer, (0, dy))
    return shifted


def build_frame(
    master: Image.Image,
    clean_face: Image.Image,
    brow_left: Image.Image,
    brow_right: Image.Image,
    generated_path: Path | None,
    brow_dy: int,
    output_path: Path,
) -> None:
    master_rgb = master.convert("RGB")

    # Remove both original brows using the clean-face skin, then redraw both brows
    # from independent layers. The same dy is always applied to the pair.
    brow_clear_mask = brow_stroke_mask(master.size)
    combined_rgb = Image.composite(
        clean_face.convert("RGB"), master_rgb, brow_clear_mask
    )

    if generated_path is not None:
        generated = align_generated(master, generated_path)
        # Remove the original open screen-left eye before placing a blink state.
        # Otherwise its upper lid can remain visible above the animated eye and
        # resemble a stray eyebrow. This cleanup is limited to the left eye only.
        left_eye_clear_mask = rounded_mask(
            master.size,
            [(330, 385, 525, 510)],
            40,
        )
        combined_rgb = Image.composite(
            clean_face.convert("RGB"), combined_rgb, left_eye_clear_mask
        )
        # The face is tilted, so the two eye envelopes have different vertical
        # positions. Tailored masks avoid touching either eyebrow.
        eye_mask = rounded_mask(
            master.size,
            # Keep the screen-left patch below the eyebrow zone. The generated
            # eye-state sources contain a faint old-brow remnant above y=415.
            # The animated upper eyelid begins below this boundary.
            [(334, 415, 520, 500), (552, 337, 750, 470)],
            40,
        )
        combined_rgb = Image.composite(generated, combined_rgb, eye_mask)

    combined = Image.merge("RGBA", (*combined_rgb.split(), master.getchannel("A")))
    combined.alpha_composite(shifted_layer(brow_left, brow_dy))
    combined.alpha_composite(shifted_layer(brow_right, brow_dy))
    combined.save(output_path)


def main() -> None:
    master = Image.open(MASTER).convert("RGBA")
    clean_face = Image.open(FACE_DIR / "pet_face_clean_v1.png").convert("RGBA")
    brow_left = Image.open(FACE_DIR / "brow_screen_left_v1.png").convert("RGBA")
    brow_right = Image.open(FACE_DIR / "brow_screen_right_v1.png").convert("RGBA")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    face_crop = master.crop((300, 280, 780, 540))
    face_crop.resize((960, 520), Image.Resampling.LANCZOS).save(
        ROOT / "assets" / "character" / "preview_brow_reference.png"
    )
    for output_name, (generated_path, brow_dy) in BLINK_SOURCES.items():
        output_path = OUTPUT_DIR / output_name
        build_frame(
            master,
            clean_face,
            brow_left,
            brow_right,
            generated_path,
            brow_dy,
            output_path,
        )
        print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
