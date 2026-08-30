# -*- coding: utf-8 -*-
"""桌宠小屋窗口入口。

当前小屋由 house_scene_refined.HandDrawnHouse 实现（底图 + 独立透明物件 + 代码绘制动画的分层方案），
本文件作为兼容入口转发该实现，main.py 通过 ``from house_window import HandDrawnHouse`` 导入。
早期的整层裁切实现（引用 lineart_* 素材）已随备选方案一并移除。
"""

from house_scene_refined import HandDrawnHouse as HandDrawnHouse

__all__ = ["HandDrawnHouse"]
