"""Align AI eye-expression references and composite only their eye regions.

The AI images redraw/zoom the whole character.  This script estimates a robust
similarity transform from hair/clothing features, aligns each image to the
original right-edge pose, then copies only two softly feathered eye patches.
Every other pixel and the original alpha channel remain from right.png.
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent
EDGE_DIR = ROOT / "assets" / "character" / "edge"
SOURCE_DIR = EDGE_DIR / "ai_sources"
BASE_PATH = ROOT / "right.png"

SOURCES = {
    "25": SOURCE_DIR / "right_blink_25_ai_v1.png",
    "60": SOURCE_DIR / "right_blink_60_ai_v1.png",
    "80": SOURCE_DIR / "right_blink_80_ai_v1.png",
    "100": SOURCE_DIR / "right_blink_100_ai_v1.png",
}

# Coordinates on the uncropped 1024x1536 right.png canvas.
EYES = (
    ((565, 634), (87, 72), -22),
    ((760, 528), (87, 72), -22),
)


def read_rgba(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise RuntimeError(f"Cannot read RGBA image: {path}")
    return image


def write_rgba(path: Path, image: np.ndarray) -> None:
    encoded, buffer = cv2.imencode(".png", image)
    if not encoded:
        raise RuntimeError(f"Cannot encode PNG: {path}")
    buffer.tofile(path)


def estimate_alignment(source: np.ndarray, base: np.ndarray) -> tuple[np.ndarray, int]:
    sift = cv2.SIFT_create(nfeatures=5000)
    source_gray = cv2.cvtColor(source[:, :, :3], cv2.COLOR_BGR2GRAY)
    base_gray = cv2.cvtColor(base[:, :, :3], cv2.COLOR_BGR2GRAY)
    source_mask = (source[:, :, 3] > 20).astype(np.uint8) * 255
    base_mask = (base[:, :, 3] > 20).astype(np.uint8) * 255
    source_points, source_desc = sift.detectAndCompute(source_gray, source_mask)
    base_points, base_desc = sift.detectAndCompute(base_gray, base_mask)
    pairs = cv2.BFMatcher().knnMatch(source_desc, base_desc, k=2)
    good = [first for first, second in pairs if first.distance < 0.72 * second.distance]
    if len(good) < 20:
        raise RuntimeError("Not enough matching features to align the AI frame")

    source_xy = np.float32([source_points[m.queryIdx].pt for m in good])
    base_xy = np.float32([base_points[m.trainIdx].pt for m in good])
    transform, inliers = cv2.estimateAffinePartial2D(
        source_xy,
        base_xy,
        method=cv2.RANSAC,
        ransacReprojThreshold=4.0,
        maxIters=5000,
        confidence=0.999,
    )
    inlier_count = int(inliers.sum()) if inliers is not None else 0
    if transform is None or inlier_count < 35:
        raise RuntimeError(f"Unstable AI frame alignment: {inlier_count} inliers")
    return transform, inlier_count


def eye_mask(shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    for center, axes, angle in EYES:
        cv2.ellipse(mask, center, axes, angle, 0, 360, 255, -1, cv2.LINE_AA)
    return cv2.GaussianBlur(mask, (0, 0), 8.0).astype(np.float32) / 255.0


def composite_eyes(base: np.ndarray, aligned: np.ndarray) -> np.ndarray:
    blend = eye_mask(base.shape[:2])[:, :, None]
    # The face is opaque here, but include aligned alpha as a final safety gate.
    blend *= aligned[:, :, 3:4].astype(np.float32) / 255.0
    result = base.copy()
    result[:, :, :3] = np.clip(
        base[:, :, :3] * (1.0 - blend) + aligned[:, :, :3] * blend,
        0,
        255,
    ).astype(np.uint8)
    result[:, :, 3] = base[:, :, 3]
    return result


def crop_like_edge_asset(image: np.ndarray, base_alpha: np.ndarray) -> np.ndarray:
    visible = np.argwhere(base_alpha > 0)
    y1, x1 = visible.min(axis=0)
    y2, x2 = visible.max(axis=0) + 1
    padding = 10
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(image.shape[1], x2 + padding)
    y2 = min(image.shape[0], y2 + padding)
    cropped = image[y1:y2, x1:x2].copy()
    cropped[cropped[:, :, 3] == 0, :3] = 0
    return cropped


def make_preview(frames: list[np.ndarray], height: int = 325) -> Image.Image:
    images = []
    for frame in frames:
        rgba = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA)
        image = Image.fromarray(rgba)
        width = round(image.width * height / image.height)
        images.append(image.resize((width, height), Image.Resampling.LANCZOS))
    preview = Image.new("RGBA", (sum(i.width for i in images), height), (0, 0, 0, 0))
    x = 0
    for image in images:
        preview.alpha_composite(image, (x, 0))
        x += image.width
    return preview


def main() -> None:
    base = read_rgba(BASE_PATH)
    cropped_open = crop_like_edge_asset(base, base[:, :, 3])
    frames = [cropped_open]
    write_rgba(EDGE_DIR / "right_blink_open_ai_v1.png", cropped_open)

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
        destination = EDGE_DIR / f"right_blink_{state}_ai_v1.png"
        write_rgba(destination, cropped)
        frames.append(cropped)
        scale = float(np.hypot(transform[0, 0], transform[0, 1]))
        print(f"{state}: {inliers} inliers, scale={scale:.4f}, output={cropped.shape[1]}x{cropped.shape[0]}")

    make_preview(frames).save(EDGE_DIR / "preview_right_blink_ai_v1.png")


if __name__ == "__main__":
    main()
