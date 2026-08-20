"""Prepare AI-generated facial expressions for the locked pet master image.

The generated images are treated only as facial-detail donors.  Hair, silhouette,
clothes, pose and transparent edges always come from pet.png.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).parent
MASTER_PATH = ROOT / "pet.png"
OUT_DIR = ROOT / "assets" / "character" / "expressions"
SOURCE_DIR = OUT_DIR / "ai_sources"

INPUTS = {
    "curious": Path(
        r"C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-61bd10ba-2873-4f43-9c2c-d3267a05ed28.png"
    ),
    "annoyed": Path(
        r"C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-0a2d1e25-06ea-4e18-adac-5f4175809296.png"
    ),
    "sleepy": Path(
        r"C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-6c6cb2d0-3f92-40f2-8b39-605a3aa1375d.png"
    ),
}


def register_to_master(source: Image.Image, master: Image.Image) -> Image.Image:
    """Register a generated full-body image to the master using stable hair detail."""
    master_rgba = np.asarray(master.convert("RGBA"))
    source_rgba = np.asarray(source.convert("RGBA"))
    master_gray = cv2.cvtColor(master_rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
    source_gray = cv2.cvtColor(source_rgba[:, :, :3], cv2.COLOR_RGB2GRAY)

    sift = cv2.SIFT_create(nfeatures=5000)
    source_mask = (source_rgba[:, :, 3] > 32).astype(np.uint8) * 255
    master_mask = (master_rgba[:, :, 3] > 32).astype(np.uint8) * 255

    # Face details intentionally differ.  Use the hair and upper silhouette for
    # registration, where the generated variants retain many matching strands.
    sy, sx = source_gray.shape
    my, mx = master_gray.shape
    source_roi = np.zeros_like(source_mask)
    master_roi = np.zeros_like(master_mask)
    source_roi[: int(sy * 0.48)] = source_mask[: int(sy * 0.48)]
    master_roi[: int(my * 0.48)] = master_mask[: int(my * 0.48)]

    kp_s, des_s = sift.detectAndCompute(source_gray, source_roi)
    kp_m, des_m = sift.detectAndCompute(master_gray, master_roi)
    if des_s is None or des_m is None:
        raise RuntimeError("Not enough image detail for expression registration")

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    pairs = matcher.knnMatch(des_s, des_m, k=2)
    good = [a for a, b in pairs if a.distance < 0.7 * b.distance]
    if len(good) < 12:
        raise RuntimeError(f"Only {len(good)} reliable registration matches")

    src_pts = np.float32([kp_s[m.queryIdx].pt for m in good])
    dst_pts = np.float32([kp_m[m.trainIdx].pt for m in good])
    matrix, inliers = cv2.estimateAffinePartial2D(
        src_pts,
        dst_pts,
        method=cv2.RANSAC,
        ransacReprojThreshold=3.0,
        maxIters=5000,
        confidence=0.995,
    )
    if matrix is None or inliers is None or int(inliers.sum()) < 10:
        raise RuntimeError("Could not obtain a stable expression registration")

    warped = cv2.warpAffine(
        source_rgba,
        matrix,
        (master.width, master.height),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0),
    )
    return Image.fromarray(warped, "RGBA")


def face_mask(size: tuple[int, int]) -> Image.Image:
    """Soft mask that stays inside the face and away from hair/outer contour."""
    width, height = size
    mask = Image.new("L", size, 0)
    # Polygon follows the visible inner face of the 1086x1448 locked master.
    polygon = np.array(
        [
            (391, 337),
            (477, 315),
            (604, 311),
            (686, 340),
            (721, 407),
            (704, 493),
            (650, 553),
            (548, 579),
            (442, 558),
            (377, 505),
            (350, 424),
        ],
        dtype=np.int32,
    )
    canvas = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(canvas, [polygon], 255)
    # A narrow feather hides tiny color differences without ghosting features.
    return Image.fromarray(canvas, "L").filter(ImageFilter.GaussianBlur(5.0))


def reposition_curious_eyes(
    composite: Image.Image,
    aligned: Image.Image,
    clean_face: Image.Image,
) -> Image.Image:
    """Return curious eye sockets to the master height while keeping its gaze."""
    result = composite.copy()
    regions = (
        # screen-left eye: generated socket was about 4 px left / 16 px high
        (
            [(365, 348), (478, 338), (510, 370), (512, 458),
             (487, 491), (376, 492), (350, 442), (351, 385)],
            (4, 16),
        ),
        # screen-right eye: generated socket was about 2 px left / 12 px high
        (
            [(575, 326), (666, 319), (699, 350), (706, 423),
             (680, 459), (579, 458), (553, 414), (555, 360)],
            (2, 12),
        ),
    )

    for polygon, (dx, dy) in regions:
        source_mask = Image.new("L", result.size, 0)
        ImageDraw.Draw(source_mask).polygon(polygon, fill=255)
        source_mask = source_mask.filter(ImageFilter.GaussianBlur(4.0))

        shifted_mask = Image.new("L", result.size, 0)
        shifted_mask.paste(source_mask, (dx, dy))
        clear_mask = Image.fromarray(
            np.maximum(np.asarray(source_mask), np.asarray(shifted_mask)),
            "L",
        ).filter(ImageFilter.GaussianBlur(2.0))
        result = Image.composite(clean_face, result, clear_mask)

        shifted_donor = Image.new("RGBA", result.size, (0, 0, 0, 0))
        shifted_donor.paste(aligned, (dx, dy))
        result = Image.composite(shifted_donor, result, shifted_mask)

    return result


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    master = Image.open(MASTER_PATH).convert("RGBA")
    clean_face = Image.open(
        ROOT / "assets" / "character" / "face" / "pet_face_clean_v1.png"
    ).convert("RGBA")
    mask = face_mask(master.size)

    for name, incoming in INPUTS.items():
        if not incoming.exists():
            raise FileNotFoundError(incoming)
        source_copy = SOURCE_DIR / f"pet_{name}_ai_source_v1.png"
        shutil.copy2(incoming, source_copy)

        generated = Image.open(source_copy).convert("RGBA")
        aligned = register_to_master(generated, master)
        aligned_path = SOURCE_DIR / f"pet_{name}_ai_aligned_v1.png"
        aligned.save(aligned_path)

        composite = Image.composite(aligned, master, mask)
        if name == "curious":
            composite = reposition_curious_eyes(
                composite,
                aligned,
                clean_face,
            )
        # Preserve the master alpha exactly so no generated edge reaches runtime.
        composite.putalpha(master.getchannel("A"))
        output_path = OUT_DIR / f"pet_expression_{name}_v1.png"
        composite.save(output_path)
        print(f"{name}: {output_path}")


if __name__ == "__main__":
    main()
