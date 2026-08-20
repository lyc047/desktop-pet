"""Build deterministic blink variants for the two edge poses.

Only the eye areas are changed. The original alpha, eyebrows, hair, mouth and
body remain untouched so future expression layers can be added independently.
"""

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent
EDGE_DIR = ROOT / "assets" / "character" / "edge"


@dataclass(frozen=True)
class Eye:
    cx: int
    cy: int
    rx: int
    ry: int
    angle: float
    clean_dy: int = 0
    clean_rx_scale: float = 1.0
    clean_ry_scale: float = 1.0
    natural_lid: bool = False


# Coordinates are measured on the cleaned, cropped edge assets. Masks stop
# below the eyebrows so blinking can never create a duplicate/residual brow.
POSES = {
    "left": {
        "source": EDGE_DIR / "cling_left_v1.png",
        "eyes": (
            Eye(414, 385, 60, 55, 8),
            Eye(610, 435, 66, 59, 7),
        ),
    },
    "right": {
        "source": EDGE_DIR / "peek_right_v1.png",
        "eyes": (
            # The tilted eyes extend farther below their visual centres.  The
            # cleanup ellipse is shifted downward so no iris/eye-white remains,
            # while its upper edge stays clear of the brows and fringe.
            Eye(
                510,
                531,
                65,
                57,
                -22,
                clean_dy=30,
                clean_rx_scale=1.32,
                clean_ry_scale=1.55,
                natural_lid=True,
            ),
            Eye(
                705,
                425,
                65,
                58,
                -22,
                clean_dy=18,
                clean_rx_scale=1.12,
                clean_ry_scale=1.25,
                natural_lid=True,
            ),
        ),
    },
}

OPENNESS = {
    "open": 1.0,
    "half": 0.56,
    "almost": 0.22,
    "closed": 0.0,
}


def ellipse_mask(shape: tuple[int, int], eye: Eye, shrink: float = 1.0) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    axes = (round(eye.rx * shrink), round(eye.ry * shrink))
    cv2.ellipse(mask, (eye.cx, eye.cy), axes, eye.angle, 0, 360, 255, -1)
    return mask


def clean_eye_plate(rgb: np.ndarray, eyes: tuple[Eye, ...]) -> np.ndarray:
    result = rgb.copy()
    regular_remove = np.zeros(rgb.shape[:2], dtype=np.uint8)
    yy, xx = np.indices(rgb.shape[:2], dtype=np.float32)
    for eye in eyes:
        clean_eye = Eye(
            eye.cx,
            eye.cy + eye.clean_dy,
            round(eye.rx * eye.clean_rx_scale),
            round(eye.ry * eye.clean_ry_scale),
            eye.angle,
        )
        remove = ellipse_mask(rgb.shape[:2], clean_eye, 0.92)
        if eye.clean_dy:
            # The right-edge pose has hair immediately outside both eyes.
            # Generic inpainting pulls that dark hair into the eye socket, so
            # sample clean skin from the cheek along the eye's local downward
            # axis instead. This retains the existing face shading and blush.
            theta = np.deg2rad(eye.angle)
            axis = np.array((np.cos(theta), np.sin(theta)))
            normal = np.array((-np.sin(theta), np.cos(theta)))
            dx = xx - eye.cx
            dy = yy - eye.cy
            local_u = dx * axis[0] + dy * axis[1]
            local_v = dx * normal[0] + dy * normal[1]

            # Collapse the eye area onto a narrow cheek strip well below the
            # lower lashes. Keeping only a little horizontal variation retains
            # natural face shading without reaching the nearby hair.
            sample_u = np.clip(local_u * 0.45, -eye.rx * 0.48, eye.rx * 0.48)
            sample_v = eye.ry * 1.62 + local_v * 0.04
            map_x = (
                eye.cx + axis[0] * sample_u + normal[0] * sample_v
            ).astype(np.float32)
            map_y = (
                eye.cy + axis[1] * sample_u + normal[1] * sample_v
            ).astype(np.float32)
            cheek = cv2.remap(
                rgb,
                map_x,
                map_y,
                cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REFLECT_101,
            )
            cheek = cv2.GaussianBlur(cheek, (0, 0), 8.0)
            feather = cv2.GaussianBlur(remove, (0, 0), 3.2).astype(np.float32) / 255.0
            feather = feather[:, :, None]
            result = np.clip(
                result * (1.0 - feather) + cheek * feather,
                0,
                255,
            ).astype(np.uint8)
        else:
            regular_remove = cv2.max(regular_remove, remove)

    # A soft inpaint gives the compressed eye layers a clean skin-colored base.
    # Feathering is deliberately narrow so cheek shading and eyebrows stay exact.
    if regular_remove.max():
        filled = cv2.inpaint(rgb, regular_remove, 13, cv2.INPAINT_TELEA)
        feather = cv2.GaussianBlur(regular_remove, (0, 0), 3.2).astype(np.float32) / 255.0
        feather = feather[:, :, None]
        result = np.clip(
            result * (1.0 - feather) + filled * feather,
            0,
            255,
        ).astype(np.uint8)
    return result


def eye_transform(shape: tuple[int, int], eye: Eye, openness: float) -> np.ndarray:
    """Return an affine matrix that closes an eye along its local vertical axis."""
    theta = np.deg2rad(eye.angle)
    cosine = np.cos(theta)
    sine = np.sin(theta)
    rotate = np.array(((cosine, sine), (-sine, cosine)), dtype=np.float32)
    unrotate = rotate.T
    scale = np.array(((1.0, 0.0), (0.0, openness)), dtype=np.float32)
    linear = unrotate @ scale @ rotate
    center = np.array((eye.cx, eye.cy), dtype=np.float32)
    translation = center - linear @ center
    return np.column_stack((linear, translation)).astype(np.float32)


def draw_lid_curve(
    canvas: np.ndarray,
    eye: Eye,
    *,
    vertical_offset: float = 0.0,
    thickness: int = 5,
    curvature: float = 0.10,
    extent: float = 0.82,
    draw_lashes: bool = True,
) -> None:
    theta = np.deg2rad(eye.angle)
    axis = np.array((np.cos(theta), np.sin(theta)))
    normal = np.array((-np.sin(theta), np.cos(theta)))
    points = []
    for t in np.linspace(-1.0, 1.0, 31):
        # A gentle downward lid curve reads naturally at the final 350 px size.
        offset = axis * (t * eye.rx * extent) + normal * (
            vertical_offset + (1.0 - t * t) * eye.ry * curvature
        )
        points.append(np.rint(np.array((eye.cx, eye.cy)) + offset).astype(np.int32))
    color = (38, 39, 55)  # OpenCV BGR -> warm dark brown in the saved PNG.
    cv2.polylines(canvas, [np.array(points)], False, color, thickness, cv2.LINE_AA)

    if draw_lashes:
        # Two restrained lashes at the outside corner; no mark is drawn near brows.
        outside = np.array(points[0], dtype=np.float32)
        for length, shift in ((13, 0), (10, 7)):
            start = outside + axis * shift
            end = start - axis * length - normal * (length * 0.34)
            cv2.line(canvas, tuple(start.astype(int)), tuple(end.astype(int)), color, 3, cv2.LINE_AA)


def draw_closed_eye(canvas: np.ndarray, eye: Eye) -> None:
    draw_lid_curve(canvas, eye)


def make_variant(original: np.ndarray, eyes: tuple[Eye, ...], openness: float) -> np.ndarray:
    rgb = original[:, :, :3]
    alpha = original[:, :, 3]
    if openness >= 0.999:
        return original.copy()

    result = clean_eye_plate(rgb, eyes)
    if openness <= 0.001:
        for eye in eyes:
            draw_closed_eye(result, eye)
    else:
        for eye in eyes:
            source_mask = ellipse_mask(rgb.shape[:2], eye, 0.96)
            if eye.natural_lid:
                # A real blink is led by the upper eyelid. Keep the iris and
                # lower lid stationary, reveal only the pixels below the moving
                # upper-lid boundary, and cover the rest with the clean plate.
                theta = np.deg2rad(eye.angle)
                axis = np.array((np.cos(theta), np.sin(theta)))
                normal = np.array((-np.sin(theta), np.cos(theta)))
                yy, xx = np.indices(rgb.shape[:2], dtype=np.float32)
                local_v = (
                    (xx - eye.cx) * normal[0]
                    + (yy - eye.cy) * normal[1]
                )
                progress = 1.0 - openness
                lid_v = eye.ry * (-0.55 + 0.60 * progress)
                lower_lid_v = eye.ry * (0.68 - 0.62 * progress)
                upper_boundary = np.clip(
                    (local_v - lid_v + 2.0) / 4.0,
                    0.0,
                    1.0,
                )
                lower_boundary = np.clip(
                    (lower_lid_v - local_v + 2.0) / 4.0,
                    0.0,
                    1.0,
                )
                blend = (
                    source_mask.astype(np.float32) / 255.0
                ) * upper_boundary * lower_boundary
                blend = cv2.GaussianBlur(blend, (0, 0), 0.8)[:, :, None]
                result = np.clip(
                    result * (1.0 - blend) + rgb * blend,
                    0,
                    255,
                ).astype(np.uint8)
                draw_lid_curve(
                    result,
                    eye,
                    vertical_offset=lid_v,
                    thickness=3,
                    curvature=-0.08 * openness + 0.06 * progress,
                    extent=0.70,
                    draw_lashes=False,
                )
                continue

            transform = eye_transform(rgb.shape[:2], eye, openness)
            warped_rgb = cv2.warpAffine(
                rgb,
                transform,
                (rgb.shape[1], rgb.shape[0]),
                flags=cv2.INTER_LANCZOS4,
                borderMode=cv2.BORDER_REFLECT_101,
            )
            warped_mask = cv2.warpAffine(
                source_mask,
                transform,
                (rgb.shape[1], rgb.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
            )
            blend = cv2.GaussianBlur(warped_mask, (0, 0), 1.4).astype(np.float32) / 255.0
            blend = blend[:, :, None]
            result = np.clip(result * (1.0 - blend) + warped_rgb * blend, 0, 255).astype(np.uint8)

    return np.dstack((result, alpha))


def make_preview(frames: list[np.ndarray], height: int = 350) -> Image.Image:
    images = []
    for frame in frames:
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA))
        width = round(image.width * height / image.height)
        images.append(image.resize((width, height), Image.Resampling.LANCZOS))
    preview = Image.new("RGBA", (sum(image.width for image in images), height), (0, 0, 0, 0))
    x = 0
    for image in images:
        preview.alpha_composite(image, (x, 0))
        x += image.width
    return preview


def main() -> None:
    for side, pose in POSES.items():
        original = cv2.imdecode(
            np.fromfile(pose["source"], dtype=np.uint8),
            cv2.IMREAD_UNCHANGED,
        )
        if original is None or original.shape[2] != 4:
            raise RuntimeError(f"Cannot read RGBA source: {pose['source']}")

        frames = []
        for state, openness in OPENNESS.items():
            frame = make_variant(original, pose["eyes"], openness)
            frames.append(frame)
            destination = EDGE_DIR / f"{side}_blink_{state}_v1.png"
            encoded, buffer = cv2.imencode(".png", frame)
            if not encoded:
                raise RuntimeError(f"Cannot encode: {destination}")
            buffer.tofile(destination)

        make_preview(frames).save(EDGE_DIR / f"preview_{side}_blink_v1.png")
        print(f"prepared {side}: {len(frames)} blink states")


if __name__ == "__main__":
    main()
