"""Store AI-generated fill plates on the character's fixed animation canvas."""

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parent
GENERATED = Path(r"C:\Users\Lenovo\.codex\generated_images\01a015af-a021-74c1-b0bc-c2c0f547cade")
OUTPUT = ROOT / "assets" / "character" / "backfill"
CANVAS = (1086, 1448)


def copy_canvas(source_name: str, output_name: str) -> None:
    image = Image.open(GENERATED / source_name).convert("RGBA")
    if image.size != CANVAS:
        raise ValueError(f"{source_name} is {image.size}; expected {CANVAS}")
    image.save(OUTPUT / output_name)


def align_torso() -> None:
    """Fit the model's full hoodie cutout to the original hoodie envelope."""
    source = Image.open(
        GENERATED / "exec-51e6e25e-6f87-430d-b8b8-1ff4cd6abce9.png"
    ).convert("RGBA")
    alpha = source.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("generated torso has no visible pixels")

    # Envelope derived from the original torso + both original arm layers.
    target_box = (205, 548, 883, 1041)
    cropped = source.crop(bbox)
    target_size = (target_box[2] - target_box[0], target_box[3] - target_box[1])
    fitted = cropped.resize(target_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    canvas.alpha_composite(fitted, target_box[:2])
    canvas.save(OUTPUT / "torso_under_limbs_v1.png")


def render_preview() -> None:
    """Render the intended neutral stack without altering the original assets."""
    layers = ROOT / "assets" / "character" / "layers"
    ordered = [
        OUTPUT / "hair_back_complete_v1.png",
        OUTPUT / "torso_under_limbs_v1.png",
        layers / "leg_l.png",
        layers / "leg_r.png",
        layers / "torso_base.png",
        layers / "arm_l.png",
        layers / "arm_r.png",
        layers / "head_base.png",
        layers / "eye_l.png",
        layers / "eye_r.png",
        layers / "pupil_l.png",
        layers / "pupil_r.png",
        layers / "eyelid_l.png",
        layers / "eyelid_r.png",
        layers / "mouth_neutral.png",
        layers / "hair_front.png",
        layers / "braid_l.png",
        layers / "braid_r.png",
    ]
    preview = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    for path in ordered:
        preview.alpha_composite(Image.open(path).convert("RGBA"))
    preview.save(ROOT / "assets" / "character" / "preview_backfill_stack_v1.png")


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    copy_canvas("exec-fda19357-53b6-4027-a704-5d032e80d171.png", "head_under_hair_v1.png")
    copy_canvas("exec-19d4e70e-0d0a-411d-864a-1c419cce365e.png", "hair_back_complete_v1.png")
    align_torso()
    render_preview()
    print(f"Prepared fill plates in {OUTPUT}")


if __name__ == "__main__":
    main()
