"""检查桌宠分层资产是否满足第一阶段的导出约定。

运行：python validate_character_assets.py
严格模式：python validate_character_assets.py --strict
"""

import json
import sys
from pathlib import Path

from PySide6.QtGui import QImage


BASE_DIR = Path(__file__).parent
MANIFEST_PATH = BASE_DIR / "assets" / "character" / "layers" / "manifest.json"


def image_info(path):
    """返回图片尺寸、Alpha 通道状态和加载错误。"""
    image = QImage(str(path))
    if image.isNull():
        return None, "无法读取图片"
    return {
        "width": image.width(),
        "height": image.height(),
        "has_alpha": image.hasAlphaChannel(),
    }, None


def main():
    strict = "--strict" in sys.argv
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    canvas = manifest["canvas"]
    layer_dir = MANIFEST_PATH.parent
    errors = []
    warnings = []

    master_path = (layer_dir / manifest["master_image"]).resolve()
    master, error = image_info(master_path)
    if error:
        errors.append(f"母版不可用：{master_path}（{error}）")
    else:
        expected_size = (canvas["width"], canvas["height"])
        actual_size = (master["width"], master["height"])
        if actual_size != expected_size:
            errors.append(f"母版尺寸为 {actual_size}，应为 {expected_size}")
        if not master["has_alpha"]:
            errors.append("母版没有透明通道")

    found = 0
    for layer in manifest["layers"]:
        path = layer_dir / layer["file"]
        if not path.exists():
            message = f"缺少图层：{layer['id']}（期待 {path.name}）"
            if layer["required"]:
                errors.append(message)
            else:
                warnings.append(message)
            continue

        found += 1
        image, error = image_info(path)
        if error:
            errors.append(f"图层 {layer['id']} 不可用：{error}")
            continue
        actual_size = (image["width"], image["height"])
        expected_size = (canvas["width"], canvas["height"])
        if actual_size != expected_size:
            errors.append(
                f"图层 {layer['id']} 尺寸为 {actual_size}，首版导出必须为 {expected_size}"
            )
        if not image["has_alpha"]:
            errors.append(f"图层 {layer['id']} 没有透明通道")

    print(f"母版：{master_path.name}")
    print(f"已发现图层：{found}/{len(manifest['layers'])}")
    if warnings:
        print("\n可选图层未就绪：")
        print("\n".join(f"- {message}" for message in warnings))
    if errors:
        print("\n需要处理：")
        print("\n".join(f"- {message}" for message in errors))
        if strict:
            return 1
    else:
        print("\n通过：所有必需图层均可加载、尺寸正确且保留透明通道。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
