"""Align and composite AI blink eyes onto the original left-edge pose."""

from pathlib import Path

import cv2
import numpy as np

from prepare_ai_edge_blink import (
    crop_like_edge_asset,
    estimate_alignment,
    make_preview,
    read_rgba,
    write_rgba,
)


ROOT = Path(__file__).resolve().parent
EDGE_DIR = ROOT / "assets" / "character" / "edge"
SOURCE_DIR = EDGE_DIR / "ai_sources"
BASE_PATH = ROOT / "left.png"

SOURCES = {
    "25": SOURCE_DIR / "left_blink_25_ai_v1.png",
    "60": SOURCE_DIR / "left_blink_60_ai_v1.png",
    "80": SOURCE_DIR / "left_blink_80_ai_v1.png",
    "100": SOURCE_DIR / "left_blink_100_ai_v1.png",
}

# Eye locations on the uncropped 1024x1536 left.png canvas. The masks include
# lids/lashes but stop below the eyebrows so expressions can be extended later.
EYES = (
    ((431, 401), (79, 65), 8),
    ((627, 451), (83, 68), 7),
)


def eye_mask(shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    for center, axes, angle in EYES:
        cv2.ellipse(mask, center, axes, angle, 0, 360, 255, -1, cv2.LINE_AA)
    return cv2.GaussianBlur(mask, (0, 0), 8.0).astype(np.float32) / 255.0


def composite_eyes(base: np.ndarray, aligned: np.ndarray) -> np.ndarray:
    blend = eye_mask(base.shape[:2])[:, :, None]
    blend *= aligned[:, :, 3:4].astype(np.float32) / 255.0
    result = base.copy()
    result[:, :, :3] = np.clip(
        base[:, :, :3] * (1.0 - blend) + aligned[:, :, :3] * blend,
        0,
        255,
    ).astype(np.uint8)
    result[:, :, 3] = base[:, :, 3]
    return result


def main() -> None:
    base = read_rgba(BASE_PATH)
    cropped_open = crop_like_edge_asset(base, base[:, :, 3])
    frames = [cropped_open]
    write_rgba(EDGE_DIR / "left_blink_open_ai_v1.png", cropped_open)

    for state, source_path in SOURCES.items():
        source = read_rgba(source_path)
        transform, inliers = estimate_alignment(source, base)
        aligned = cv2.warpAffine(
            source,
            transform,
            (base.shape[1], base.shape[0]),
            flags=cv2.INTER_LANCZOS4,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0),
        )
        combined = composite_eyes(base, aligned)
        cropped = crop_like_edge_asset(combined, base[:, :, 3])
        destination = EDGE_DIR / f"left_blink_{state}_ai_v1.png"
        write_rgba(destination, cropped)
        frames.append(cropped)
        scale = float(np.hypot(transform[0, 0], transform[0, 1]))
        print(
            f"{state}: {inliers} inliers, scale={scale:.4f}, "
            f"output={cropped.shape[1]}x{cropped.shape[0]}"
        )

    make_preview(frames, height=350).save(
        EDGE_DIR / "preview_left_blink_ai_v1.png"
    )


if __name__ == "__main__":
    main()
