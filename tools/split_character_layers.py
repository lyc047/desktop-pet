"""按 Photopea 导引边界，从 pet.png 生成第一版 P0 分层 PNG。

这些图层只保留母版中原本可见的像素，绝不调用生成式图片工具。
运行：python split_character_layers.py
"""

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


BASE_DIR = Path(__file__).parent
SOURCE_PATH = BASE_DIR / "pet.png"
OUTPUT_DIR = BASE_DIR / "assets" / "character" / "layers"
CANVAS_WIDTH = 1086
CANVAS_HEIGHT = 1448


# 这里的路径与 guides/ 中的可视化套索导引图一致。
# 面部左右按角色自身命名：画面右侧是角色左侧。
PATHS = {
    "hair_back": '<path fill="white" fill-rule="evenodd" d="M294 551 C213 469 197 350 224 238 C250 132 339 48 451 29 C573 7 702 36 790 113 C866 181 892 289 865 401 C853 456 822 508 782 553 L728 512 C757 455 776 395 771 322 C765 226 678 159 569 150 C445 140 339 212 320 332 C308 408 336 474 373 522 Z"/>',
    "hair_front": '<path fill="white" d="M310 209 C367 92 549 56 690 121 C756 151 797 214 797 292 C764 270 735 260 703 257 C666 253 640 272 612 302 C579 335 545 360 508 365 C465 373 422 352 391 367 C356 384 334 411 322 451 C289 400 282 302 310 209 Z"/>',
    "head_base": '<path fill="white" d="M337 347 C370 283 446 250 540 252 C635 252 716 294 748 356 L746 464 C741 530 684 584 618 605 L607 647 L478 647 L464 605 C397 581 343 530 337 459 Z"/>',
    "torso_base": '<path fill="white" d="M396 597 C437 566 475 556 543 556 C610 556 650 567 691 599 L744 708 L720 986 C673 1021 614 1038 544 1037 C470 1038 407 1023 366 986 L344 708 Z"/>',
    "arm_r": '<path fill="white" d="M389 650 C334 676 278 739 237 807 C208 854 196 911 213 950 C228 982 263 997 292 976 L350 928 C379 899 399 861 417 808 L446 701 Z"/>',
    "arm_l": '<path fill="white" d="M696 650 C751 676 808 739 849 807 C878 854 890 911 873 950 C858 982 823 997 794 976 L736 928 C707 899 687 861 669 808 L640 701 Z"/>',
    "braid_r": '<path fill="white" d="M374 472 C333 503 322 560 335 612 C345 654 321 693 342 737 C354 762 342 794 358 828 C376 862 405 873 431 854 C452 837 440 807 430 782 C415 744 439 715 419 675 C399 637 428 607 408 565 C397 537 410 503 401 482 Z"/>',
    "braid_l": '<path fill="white" d="M712 472 C753 503 764 560 751 612 C741 654 765 693 744 737 C732 762 744 794 728 828 C710 862 681 873 655 854 C634 837 646 807 656 782 C671 744 647 715 667 675 C687 637 658 607 678 565 C689 537 676 503 685 482 Z"/>',
    "leg_r": '<path fill="white" d="M434 1009 L540 1009 L536 1205 C536 1250 559 1295 546 1360 C538 1404 499 1426 448 1417 C411 1411 390 1389 398 1355 L422 1266 C429 1224 426 1170 426 1118 Z"/>',
    "leg_l": '<path fill="white" d="M546 1009 L652 1009 L660 1118 C660 1170 657 1224 664 1266 L688 1355 C696 1389 675 1411 638 1417 C587 1426 548 1404 540 1360 C527 1295 550 1250 550 1205 Z"/>',
    "eye_r": '<path fill="white" d="M367 413 C394 382 454 380 487 413 C468 468 405 478 367 430 Z"/>',
    "eye_l": '<path fill="white" d="M591 413 C624 380 684 382 711 413 L711 430 C673 478 610 468 591 413 Z"/>',
    "pupil_r": '<ellipse fill="white" cx="432" cy="429" rx="33" ry="37"/>',
    "pupil_l": '<ellipse fill="white" cx="646" cy="429" rx="33" ry="37"/>',
    "eyelid_r": '<path fill="none" stroke="white" stroke-width="14" stroke-linecap="round" d="M368 411 C399 382 452 382 487 412"/>',
    "eyelid_l": '<path fill="none" stroke="white" stroke-width="14" stroke-linecap="round" d="M591 412 C626 382 679 382 711 411"/>',
    "mouth_neutral": '<path fill="white" d="M510 515 C530 504 556 504 576 515 C558 537 529 538 510 515 Z"/>',
}


def svg_mask(svg_shape):
    """将一个 SVG 形状渲染成带抗锯齿 Alpha 的画布大小蒙版。"""
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}">{svg_shape}</svg>'''
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        raise ValueError("无效的 SVG 蒙版")
    mask = QImage(CANVAS_WIDTH, CANVAS_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(QColor(0, 0, 0, 0))
    painter = QPainter(mask)
    renderer.render(painter)
    painter.end()
    return mask


def cut_layer(source, mask):
    """将透明 PNG 的原始像素保留在蒙版白色区域。"""
    result = QImage(CANVAS_WIDTH, CANVAS_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(QColor(0, 0, 0, 0))
    painter = QPainter(result)
    painter.drawImage(0, 0, source)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()
    return result


def make_ground_shadow():
    """地面阴影是程序可替换的基础辅助层，不从角色图中截取。"""
    image = QImage(CANVAS_WIDTH, CANVAS_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setBrush(QColor(67, 47, 38, 52))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QRectF(383, 1394, 320, 34))
    painter.end()
    return image


def save_png(image, path):
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"无法保存 {path.name}")


def build_preview(layers):
    """按默认前后关系合成预览，便于人工检查是否有明显缺口。"""
    order = [
        "ground_shadow", "hair_back", "leg_l", "leg_r", "torso_base",
        "arm_l", "arm_r", "head_base", "eye_l", "eye_r", "pupil_l",
        "pupil_r", "eyelid_l", "eyelid_r", "mouth_neutral", "hair_front",
        "braid_l", "braid_r",
    ]
    preview = QImage(CANVAS_WIDTH, CANVAS_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    preview.fill(QColor(0, 0, 0, 0))
    painter = QPainter(preview)
    for name in order:
        painter.drawImage(0, 0, layers[name])
    painter.end()
    return preview


def main():
    source = QImage(str(SOURCE_PATH))
    if source.isNull():
        raise FileNotFoundError(f"无法读取母版：{SOURCE_PATH}")
    if (source.width(), source.height()) != (CANVAS_WIDTH, CANVAS_HEIGHT):
        raise ValueError("母版尺寸与 manifest 约定不一致")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    layers = {"ground_shadow": make_ground_shadow()}
    for name, shape in PATHS.items():
        layers[name] = cut_layer(source, svg_mask(shape))

    for name, image in layers.items():
        save_png(image, OUTPUT_DIR / f"{name}.png")
    save_png(build_preview(layers), OUTPUT_DIR.parent / "preview_p0_layers.png")
    print(f"已导出 {len(layers)} 个 P0 图层到：{OUTPUT_DIR}")
    print("已生成预览：assets/character/preview_p0_layers.png")


if __name__ == "__main__":
    from PySide6.QtCore import Qt

    main()
