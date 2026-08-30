import math
import random
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from reader_dialog import BookReaderDialog, BookshelfManagerDialog


INK = QColor("#493f3a")
INK_SOFT = QColor("#766861")
PAPER = QColor("#fbf5e9")
PAPER_LIGHT = QColor("#fffaf1")
TEAL = QColor("#69aa9c")
ROSE = QColor("#d99a9f")
WOOD = QColor("#d9b997")


class NumberPuzzleDialog(QDialog):
    """无需图片的 4×4 数字华容道。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("桌上的数字华容道")
        self.setMinimumSize(430, 500)
        self.values = list(range(1, 16)) + [0]
        self.buttons = []

        root = QVBoxLayout(self)
        title = QLabel("把数字按顺序排好吧")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("KaiTi", 18, QFont.Weight.Bold))
        root.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(8)
        for index in range(16):
            button = QPushButton()
            button.setMinimumSize(82, 82)
            button.clicked.connect(lambda _checked=False, i=index: self._move(i))
            button.setStyleSheet(
                "QPushButton { background:#fff8e9; color:#493f3a; border:2px solid #766861; "
                "border-radius:12px; font:700 22px 'KaiTi'; }"
                "QPushButton:hover { background:#e5f2ed; border-color:#69aa9c; }"
                "QPushButton:pressed { padding-top:4px; }"
            )
            self.buttons.append(button)
            grid.addWidget(button, index // 4, index % 4)
        root.addLayout(grid)

        controls = QHBoxLayout()
        shuffle = QPushButton("重新打乱")
        shuffle.clicked.connect(self._shuffle)
        close = QPushButton("收起来")
        close.clicked.connect(self.accept)
        controls.addWidget(shuffle)
        controls.addStretch()
        controls.addWidget(close)
        root.addLayout(controls)
        self._shuffle()

    def _shuffle(self):
        self.values = list(range(1, 16)) + [0]
        empty = 15
        previous = -1
        for _ in range(220):
            row, col = divmod(empty, 4)
            choices = []
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = row + dr, col + dc
                if 0 <= nr < 4 and 0 <= nc < 4:
                    idx = nr * 4 + nc
                    if idx != previous:
                        choices.append(idx)
            move = random.choice(choices)
            self.values[empty], self.values[move] = self.values[move], self.values[empty]
            previous, empty = empty, move
        self._refresh()

    def _move(self, index):
        if self.values[index] == 0:
            return
        empty = self.values.index(0)
        r1, c1 = divmod(index, 4)
        r2, c2 = divmod(empty, 4)
        if abs(r1 - r2) + abs(c1 - c2) != 1:
            return
        self.values[empty], self.values[index] = self.values[index], self.values[empty]
        self._refresh()
        if self.values == list(range(1, 16)) + [0]:
            QMessageBox.information(self, "完成啦", "每一块都回到了正确的位置！")

    def _refresh(self):
        for button, value in zip(self.buttons, self.values):
            button.setText(str(value) if value else "")
            button.setEnabled(bool(value))


class DrawingCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(650, 430)
        self.setAttribute(Qt.WidgetAttribute.WA_StaticContents)
        self.lines = []
        self.current = None
        self.color = INK
        self.width_value = 4.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.current = [event.position()]
            self.lines.append((QColor(self.color), self.width_value, self.current))
            self.update()

    def mouseMoveEvent(self, event):
        if self.current is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.current.append(event.position())
            self.update()

    def mouseReleaseEvent(self, event):
        self.current = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), PAPER_LIGHT)
        painter.setPen(QPen(QColor(106, 150, 145, 28), 1.0))
        for y in range(30, self.height(), 30):
            painter.drawLine(0, y, self.width(), y)
        for color, width, points in self.lines:
            if len(points) < 2:
                continue
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for start, end in zip(points, points[1:]):
                painter.drawLine(start, end)

    def clear(self):
        self.lines.clear()
        self.update()


class DrawingPadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("窗边的小画板")
        root = QVBoxLayout(self)
        self.canvas = DrawingCanvas()
        root.addWidget(self.canvas)
        controls = QHBoxLayout()
        for label, color in (("铅笔", INK), ("青绿", TEAL), ("淡粉", ROSE), ("橡皮", PAPER_LIGHT)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, c=color: self._select(c))
            controls.addWidget(button)
        controls.addStretch()
        clear = QPushButton("清空")
        clear.clicked.connect(self.canvas.clear)
        save = QPushButton("保存画作…")
        save.clicked.connect(self._save)
        controls.addWidget(clear)
        controls.addWidget(save)
        root.addLayout(controls)

    def _select(self, color):
        self.canvas.color = QColor(color)
        self.canvas.width_value = 18.0 if color == PAPER_LIGHT else 4.0

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存画作", "桌宠的小画.png", "PNG 图片 (*.png)")
        if not path:
            return
        image = self.canvas.grab()
        if image.save(path, "PNG"):
            QMessageBox.information(self, "保存完成", "画作已经收好啦。")


class HandDrawnHouse(QWidget):
    """程序化线稿小屋：家具和桌宠分身全部由 QPainter 绘制。"""

    returned_to_desktop = Signal()
    request_sleep = Signal()

    SCENE_W = 1100.0
    SCENE_H = 700.0

    def __init__(self, inbox_path, parent=None):
        super().__init__(parent)
        self.base_dir = Path(__file__).parent
        self.inbox_path = Path(inbox_path)
        self.notes_path = self.inbox_path / "桌宠便签.txt"
        clean_room = self.base_dir / "assets" / "house" / "lineart_room_clean.png"
        original_room = self.base_dir / "assets" / "house" / "lineart_room_v2.png"
        self._room_art = QPixmap(str(clean_room if clean_room.exists() else original_room))
        self._items_art = QPixmap(str(self.base_dir / "assets" / "house" / "lineart_items_layer.png"))
        self._pet_art = QPixmap(str(self.base_dir / "assets" / "house" / "lineart_pet_v2.png"))
        self.setWindowTitle("桌宠的小屋")
        self.setMinimumSize(920, 590)
        self.resize(1100, 700)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#fbf5e9;")
        self._hovered = ""
        self._pressed = ""
        self._phase = 0.0
        self._return_emitted = False
        self._scale = 1.0
        self._origin = QPointF()
        # 小物件必须排在大物件前面，命中时才不会被桌子、画架等大区域截走。
        # 所有热区只负责命中，不再绘制悬停高光或文字标签。
        self._items = {
            "bookshelf": QRectF(350, 184, 52, 78),
            "book": QRectF(744, 318, 82, 48),
            "cup": QRectF(500, 234, 62, 58),
            "side_drawer": QRectF(68, 448, 88, 76),
            "drawer": QRectF(286, 239, 92, 48),
            "lamp": QRectF(286, 157, 72, 108),
            "radio": QRectF(402, 205, 78, 55),
            "toy_car": QRectF(642, 257, 72, 48),
            "curtain": QRectF(224, 22, 65, 276),
            "window_plant": QRectF(174, 191, 86, 92),
            "hanging_plant": QRectF(64, 73, 88, 145),
            "cushion": QRectF(275, 286, 92, 105),
            "picture": QRectF(548, 42, 120, 142),
            "notes": QRectF(4, 65, 64, 176),
            "sofa": QRectF(20, 292, 385, 330),
            "puzzle": QRectF(535, 252, 118, 72),
            "canvas": QRectF(716, 46, 170, 374),
            "chest": QRectF(895, 386, 200, 287),
            "door": QRectF(886, 12, 121, 376),
        }
        self._labels = {
            "notes": "窗边便签",
            "sofa": "软软的沙发",
            "puzzle": "数字华容道",
            "canvas": "小画板",
            "chest": "收纳箱",
            "door": "回到桌面",
            "bookshelf": "整理小屋书架",
            "book": "阅读选中的书",
            "cup": "给杯子倒水",
            "drawer": "拉开抽屉",
            "side_drawer": "拉开小抽屉",
            "lamp": "开关台灯",
            "radio": "打开收音机",
            "toy_car": "拨动玩具车",
            "curtain": "拨动窗帘",
            "window_plant": "碰碰窗边植物",
            "hanging_plant": "碰碰吊兰",
            "cushion": "拍拍靠垫",
            "picture": "扶正挂画",
        }
        # 精灵矩形按原画中的真实轮廓登记，与较宽松的鼠标命中区分开。
        # 新物件只需追加清单和透明素材，不必改动房间底图绘制流程。
        self._sprite_rects = {
            "drawer": QRectF(304, 254, 43, 31),
            "side_drawer": QRectF(76, 457, 69, 51),
            "cup": QRectF(512, 238, 38, 46),
            "puzzle": QRectF(553, 270, 77, 32),
            "toy_car": QRectF(645, 265, 61, 39),
            "curtain": QRectF(219, 0, 76, 312),
            "window_plant": QRectF(174, 186, 84, 90),
            "hanging_plant": QRectF(54, 65, 102, 155),
            "cushion": QRectF(274, 282, 98, 112),
            "picture": QRectF(544, 19, 128, 170),
            "chest": QRectF(892, 394, 208, 84),
            "door": QRectF(910, 14, 92, 378),
        }
        self._note_sprite_rects = (
            QRectF(32, 67, 35, 48),
            QRectF(15, 120, 39, 48),
            QRectF(41, 169, 34, 47),
            QRectF(0, 200, 35, 46),
        )
        self._motion_specs = {
            "book": ("oneshot", 0.95),
            "cup": ("oneshot", 1.35),
            "drawer": ("toggle", 0.34),
            "side_drawer": ("toggle", 0.34),
            "lamp": ("toggle", 0.42),
            "radio": ("toggle", 0.32),
            "toy_car": ("oneshot", 1.05),
            "curtain": ("oneshot", 1.25),
            "window_plant": ("oneshot", 1.05),
            "hanging_plant": ("oneshot", 1.45),
            "cushion": ("oneshot", 0.72),
            "picture": ("oneshot", 0.82),
            "notes": ("oneshot", 0.55),
            "puzzle": ("oneshot", 0.45),
            "canvas": ("oneshot", 0.45),
            "chest": ("toggle", 0.48),
            "door": ("toggle", 0.62),
            "sofa": ("oneshot", 0.55),
        }
        self._motions = {
            name: {"value": 0.0, "target": 0.0, "elapsed": 0.0, "active": False}
            for name in self._motion_specs
        }
        self._puzzle_dialog = None
        self._drawing_dialog = None
        self._reader_dialog = None
        self._bookshelf_dialog = None
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._phase += 0.055
        dt = self._timer.interval() / 1000.0
        for name, state in self._motions.items():
            kind, duration = self._motion_specs[name]
            if kind == "toggle":
                delta = state["target"] - state["value"]
                if abs(delta) > 0.001:
                    step = min(abs(delta), dt / duration)
                    state["value"] += step if delta > 0 else -step
                    state["active"] = True
                else:
                    state["value"] = state["target"]
                    state["active"] = False
            elif state["active"]:
                state["elapsed"] += dt
                state["value"] = min(1.0, state["elapsed"] / duration)
                if state["value"] >= 1.0:
                    state["active"] = False
                    state["value"] = 0.0
        # 桌宠呼吸和所有物件动画共享刷新循环，但各自保存状态，互不抢占。
        self.update()

    def _scene_point(self, point):
        return QPointF(
            (point.x() - self._origin.x()) / self._scale,
            (point.y() - self._origin.y()) / self._scale,
        )

    def _item_at(self, scene_point):
        for name, rect in self._items.items():
            if rect.contains(scene_point):
                return name
        return ""

    def mouseMoveEvent(self, event):
        hovered = self._item_at(self._scene_point(event.position()))
        self.setCursor(Qt.CursorShape.PointingHandCursor if hovered else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event):
        self._pressed = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self._item_at(self._scene_point(event.position()))
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        released = self._item_at(self._scene_point(event.position()))
        selected = self._pressed if self._pressed == released else ""
        self._pressed = ""
        self.update()
        if selected:
            self._activate(selected)

    def _activate(self, name):
        opened = self._trigger_motion(name)
        if name == "puzzle":
            if self._puzzle_dialog is None:
                self._puzzle_dialog = NumberPuzzleDialog(self)
                self._puzzle_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                self._puzzle_dialog.destroyed.connect(lambda: setattr(self, "_puzzle_dialog", None))
            self._puzzle_dialog.show()
            self._puzzle_dialog.raise_()
            self._puzzle_dialog.activateWindow()
        elif name == "canvas":
            if self._drawing_dialog is None:
                self._drawing_dialog = DrawingPadDialog(self)
                self._drawing_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                self._drawing_dialog.destroyed.connect(lambda: setattr(self, "_drawing_dialog", None))
            self._drawing_dialog.show()
            self._drawing_dialog.raise_()
            self._drawing_dialog.activateWindow()
        elif name == "bookshelf":
            self._open_bookshelf()
        elif name == "book":
            # 桌上的书只打开书架中已经选定的当前书籍。
            QTimer.singleShot(180, self._open_reader)
        elif name == "notes":
            self.inbox_path.mkdir(parents=True, exist_ok=True)
            if not self.notes_path.exists():
                self.notes_path.write_text("把文字拖给桌宠后，便签会出现在这里。\n", encoding="utf-8")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.notes_path)))
        elif name == "chest":
            if opened:
                self.inbox_path.mkdir(parents=True, exist_ok=True)
                QTimer.singleShot(
                    430,
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.inbox_path))),
                )
        elif name == "sofa":
            self.request_sleep.emit()
            self._leave_house()
        elif name == "door":
            if opened:
                QTimer.singleShot(620, self._leave_house)

    def _open_reader(self):
        library_dir = self.inbox_path / "小屋书架"
        if self._reader_dialog is not None and self._reader_dialog.library_dir != library_dir:
            self._reader_dialog.close()
            self._reader_dialog = None
        if self._reader_dialog is None:
            self._reader_dialog = BookReaderDialog(library_dir, self)
            self._reader_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._reader_dialog.destroyed.connect(lambda: setattr(self, "_reader_dialog", None))
        self._reader_dialog.refresh()
        self._reader_dialog.show()
        self._reader_dialog.raise_()
        self._reader_dialog.activateWindow()

    def _open_bookshelf(self):
        library_dir = self.inbox_path / "小屋书架"
        if self._bookshelf_dialog is not None and self._bookshelf_dialog.library_dir != library_dir:
            self._bookshelf_dialog.close()
            self._bookshelf_dialog = None
        if self._bookshelf_dialog is None:
            self._bookshelf_dialog = BookshelfManagerDialog(library_dir, self)
            self._bookshelf_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._bookshelf_dialog.destroyed.connect(lambda: setattr(self, "_bookshelf_dialog", None))
            self._bookshelf_dialog.currentBookChanged.connect(
                lambda _path: self._reader_dialog.refresh() if self._reader_dialog is not None else None
            )
        self._bookshelf_dialog.refresh()
        self._bookshelf_dialog.show()
        self._bookshelf_dialog.raise_()
        self._bookshelf_dialog.activateWindow()

    def _leave_house(self):
        """仅离开小屋，不关闭应用中的桌宠主窗口。"""
        if not self._return_emitted:
            self._return_emitted = True
            self.returned_to_desktop.emit()
        self.hide()

    def _trigger_motion(self, name):
        """启动单个物件的动画；返回 toggle 动画的新开合状态。"""
        if name not in self._motions:
            return False
        kind, _duration = self._motion_specs[name]
        state = self._motions[name]
        if kind == "toggle":
            state["target"] = 0.0 if state["target"] >= 0.5 else 1.0
            state["active"] = True
            return state["target"] >= 0.5
        state["elapsed"] = 0.0
        state["value"] = 0.0
        state["active"] = True
        return True

    def _motion_value(self, name):
        return self._motions.get(name, {}).get("value", 0.0)

    @staticmethod
    def _stable_seed(key):
        return sum((index + 1) * ord(char) for index, char in enumerate(key))

    def _sketch_line(self, painter, a, b, key, width=2.0, color=INK):
        rng = random.Random(self._stable_seed(key))
        for pass_index, alpha in ((0, 220), (1, 72)):
            ox = rng.uniform(-1.0, 1.0) * pass_index
            oy = rng.uniform(-1.0, 1.0) * pass_index
            mid = QPointF((a.x() + b.x()) / 2 + rng.uniform(-2.2, 2.2), (a.y() + b.y()) / 2 + rng.uniform(-2.2, 2.2))
            path = QPainterPath(QPointF(a.x() + ox, a.y() + oy))
            path.quadTo(mid, QPointF(b.x() + ox, b.y() + oy))
            shade = QColor(color)
            shade.setAlpha(alpha)
            painter.setPen(QPen(shade, width - pass_index * 0.45, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawPath(path)

    def _sketch_rect(self, painter, rect, key, fill=PAPER_LIGHT, radius=10.0, width=2.0):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, radius, radius)
        self._sketch_line(painter, rect.topLeft(), rect.topRight(), key + "t", width)
        self._sketch_line(painter, rect.topRight(), rect.bottomRight(), key + "r", width)
        self._sketch_line(painter, rect.bottomRight(), rect.bottomLeft(), key + "b", width)
        self._sketch_line(painter, rect.bottomLeft(), rect.topLeft(), key + "l", width)

    def _hover_lift(self, name):
        if name != self._hovered:
            return 0.0
        return -4.0 - math.sin(self._phase * 2.0) * 1.5

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), PAPER)
        self._scale = min(self.width() / self.SCENE_W, self.height() / self.SCENE_H)
        self._origin = QPointF((self.width() - self.SCENE_W * self._scale) / 2, (self.height() - self.SCENE_H * self._scale) / 2)
        painter.translate(self._origin)
        painter.scale(self._scale, self._scale)

        if not self._room_art.isNull():
            painter.drawPixmap(
                QRectF(0, 0, self.SCENE_W, self.SCENE_H),
                self._room_art,
                QRectF(self._room_art.rect()),
            )
        else:
            # 素材意外缺失时仍保留可操作的旧线框场景作为安全回退。
            self._draw_room(painter)
            self._draw_window_notes(painter)
            self._draw_sofa(painter)
            self._draw_table_and_puzzle(painter)
            self._draw_canvas(painter)
            self._draw_chest(painter)
            self._draw_door(painter)
        self._draw_layered_items(painter)
        self._draw_item_animations(painter)
        if not self._pet_art.isNull():
            self._draw_pet_art(painter)
        else:
            self._draw_pet(painter)

    @staticmethod
    def _smooth(value):
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def _motion_visible(self, name):
        state = self._motions.get(name)
        return bool(state and (state["active"] or state["value"] > 0.001))

    def _room_source_rect(self, scene_rect):
        if self._room_art.isNull():
            return QRectF()
        return QRectF(
            scene_rect.x() / self.SCENE_W * self._room_art.width(),
            scene_rect.y() / self.SCENE_H * self._room_art.height(),
            scene_rect.width() / self.SCENE_W * self._room_art.width(),
            scene_rect.height() / self.SCENE_H * self._room_art.height(),
        )

    def _draw_room_crop(self, p, source_scene_rect, target_scene_rect=None, clip_path=None):
        """从原始房间图裁出物件；可在补底后作为真正的独立图层重绘。"""
        if self._room_art.isNull():
            return
        target_scene_rect = target_scene_rect or source_scene_rect
        p.save()
        if clip_path is not None:
            p.setClipPath(clip_path)
        p.drawPixmap(target_scene_rect, self._room_art, self._room_source_rect(source_scene_rect))
        p.restore()

    def _draw_item_crop(self, p, source_scene_rect, target_scene_rect=None):
        """绘制透明物件层中的一件物品；底图中不存在它的静止残影。"""
        if self._items_art.isNull():
            return
        target_scene_rect = target_scene_rect or source_scene_rect
        source = QRectF(
            source_scene_rect.x() / self.SCENE_W * self._items_art.width(),
            source_scene_rect.y() / self.SCENE_H * self._items_art.height(),
            source_scene_rect.width() / self.SCENE_W * self._items_art.width(),
            source_scene_rect.height() / self.SCENE_H * self._items_art.height(),
        )
        p.drawPixmap(target_scene_rect, self._items_art, source)

    def _draw_layered_items(self, p):
        """逐件绘制独立本体；每件读取自己的状态，彼此不会覆盖动画。"""
        if self._items_art.isNull():
            return

        drawer = self._smooth(self._motion_value("drawer"))
        drawer_rect = self._sprite_rects["drawer"]
        self._draw_item_crop(p, drawer_rect, drawer_rect.translated(0, 17 * drawer))

        side_drawer = self._smooth(self._motion_value("side_drawer"))
        side_drawer_rect = self._sprite_rects["side_drawer"]
        self._draw_item_crop(
            p,
            side_drawer_rect,
            side_drawer_rect.translated(0, 18 * side_drawer),
        )

        cup_rect = self._sprite_rects["cup"]
        self._draw_item_crop(p, cup_rect)

        puzzle = self._motion_value("puzzle")
        puzzle_rect = self._sprite_rects["puzzle"]
        puzzle_lift = math.sin(math.pi * puzzle) * 4.0 if puzzle > 0.0 else 0.0
        self._draw_item_crop(p, puzzle_rect, puzzle_rect.translated(0, -puzzle_lift))

        toy = self._motion_value("toy_car")
        toy_rect = self._sprite_rects["toy_car"]
        shift = math.sin(math.pi * toy) * 26 if toy > 0.0 else 0.0
        bounce = abs(math.sin(math.pi * toy * 3.0)) * 2.5 if toy > 0.0 else 0.0
        self._draw_item_crop(p, toy_rect, toy_rect.translated(shift, -bounce))

        curtain = self._motion_value("curtain")
        curtain_rect = self._sprite_rects["curtain"]
        curtain_angle = math.sin(curtain * math.pi * 3.0) * (1.0 - curtain) * 3.2 if curtain > 0.0 else 0.0
        curtain_anchor = QPointF(256, 1)
        p.save()
        p.translate(curtain_anchor)
        p.rotate(curtain_angle)
        self._draw_item_crop(
            p,
            curtain_rect,
            curtain_rect.translated(-curtain_anchor.x(), -curtain_anchor.y()),
        )
        p.restore()

        for name, anchor in (("window_plant", QPointF(216, 267)), ("hanging_plant", QPointF(106, 73))):
            value = self._motion_value(name)
            angle = math.sin(value * math.pi * 4.0) * (1.0 - value) * (5.0 if name == "window_plant" else 7.5) if value > 0.0 else 0.0
            rect = self._sprite_rects[name]
            p.save()
            p.translate(anchor)
            p.rotate(angle)
            self._draw_item_crop(p, rect, rect.translated(-anchor.x(), -anchor.y()))
            p.restore()

        cushion = self._motion_value("cushion")
        cushion_rect = self._sprite_rects["cushion"]
        squash = math.sin(math.pi * cushion) if cushion > 0.0 else 0.0
        cw = cushion_rect.width() * (1.0 + squash * 0.055)
        ch = cushion_rect.height() * (1.0 - squash * 0.12)
        cushion_target = QRectF(cushion_rect.center().x() - cw / 2, cushion_rect.center().y() - ch / 2, cw, ch)
        self._draw_item_crop(p, cushion_rect, cushion_target)

        picture = self._motion_value("picture")
        picture_rect = self._sprite_rects["picture"]
        picture_angle = math.sin(picture * math.pi * 5.0) * (1.0 - picture) * 5.5 if picture > 0.0 else 0.0
        picture_anchor = QPointF(608, 23)
        p.save()
        p.translate(picture_anchor)
        p.rotate(picture_angle)
        self._draw_item_crop(
            p,
            picture_rect,
            picture_rect.translated(-picture_anchor.x(), -picture_anchor.y()),
        )
        p.restore()

        notes = self._motion_value("notes")
        for index, rect in enumerate(self._note_sprite_rects):
            flutter = math.sin(notes * math.pi * 4.0 + index) * (1.0 - notes) * 6 if notes > 0.0 else 0.0
            self._draw_item_crop(p, rect, rect.translated(flutter, 0))

        door = self._smooth(self._motion_value("door"))
        door_rect = self._sprite_rects["door"]
        door_width = max(15.0, door_rect.width() * (1.0 - door * 0.80))
        self._draw_item_crop(
            p,
            door_rect,
            QRectF(door_rect.right() - door_width, door_rect.y(), door_width, door_rect.height()),
        )

        chest = self._smooth(self._motion_value("chest"))
        chest_rect = self._sprite_rects["chest"]
        if chest <= 0.001:
            self._draw_item_crop(p, chest_rect)
        else:
            # The source crop also contains objects sitting on the cabinet. Once the
            # lid moves, replace it with a clean hand-drawn board whose exterior is
            # genuinely transparent instead of moving a rectangular paper patch.
            def mix(a, b):
                return a + (b - a) * chest

            closed = (
                QPointF(897, 399), QPointF(1098, 399),
                QPointF(1099, 472), QPointF(906, 474),
            )
            opened = (
                QPointF(916, 358), QPointF(1082, 358),
                QPointF(1067, 391), QPointF(928, 391),
            )
            points = tuple(
                QPointF(mix(a.x(), b.x()), mix(a.y(), b.y()))
                for a, b in zip(closed, opened)
            )
            lid = QPainterPath(points[0])
            for point in points[1:]:
                lid.lineTo(point)
            lid.closeSubpath()
            p.setPen(QPen(QColor(81, 72, 66, 225), 1.5))
            p.setBrush(QColor(239, 232, 220, 248))
            p.drawPath(lid)
            p.setPen(QPen(QColor(113, 101, 92, 92), 0.9))
            for ratio in (0.24, 0.48, 0.72):
                left = QPointF(
                    points[0].x() + (points[3].x() - points[0].x()) * ratio,
                    points[0].y() + (points[3].y() - points[0].y()) * ratio,
                )
                right = QPointF(
                    points[1].x() + (points[2].x() - points[1].x()) * ratio,
                    points[1].y() + (points[2].y() - points[1].y()) * ratio,
                )
                p.drawLine(left, right)

    @staticmethod
    def _rounded_clip(rect, radius=6.0):
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        return path

    def _draw_active_backfills(self, p):
        """先擦除底图中的原物件，再由独立物件层绘回，彻底避免残影。"""
        wall = QColor(249, 245, 236, 252)
        wood = QColor(224, 211, 193, 252)
        cloth = QColor(239, 233, 221, 252)

        def patch(rect, fill, lines=()):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawRect(rect)
            p.setPen(QPen(QColor(116, 103, 94, 72), 0.9))
            for start, end in lines:
                p.drawLine(start, end)

        if self._motion_visible("drawer"):
            rect = QRectF(292, 247, 70, 34)
            patch(rect, wood, ((QPointF(292, 249), QPointF(362, 249)), (QPointF(292, 279), QPointF(362, 279))))

        if self._motion_visible("book"):
            patch(QRectF(744, 316, 83, 51), QColor(233, 221, 203, 252), ((QPointF(744, 354), QPointF(827, 354)),))

        if self._motion_visible("toy_car"):
            rect = QRectF(646, 257, 72, 45)
            patch(rect, QColor(237, 226, 207, 252), ((QPointF(646, 294), QPointF(718, 294)),))

        if self._motion_visible("curtain"):
            rect = QRectF(224, 18, 64, 286)
            patch(
                rect,
                QColor(238, 241, 235, 252),
                ((QPointF(239, 18), QPointF(239, 304)), (QPointF(271, 18), QPointF(271, 304))),
            )

        if self._motion_visible("window_plant"):
            patch(QRectF(174, 190, 88, 96), QColor(241, 239, 226, 252), ((QPointF(174, 270), QPointF(262, 270)),))

        if self._motion_visible("hanging_plant"):
            patch(QRectF(60, 68, 101, 153), QColor(240, 242, 235, 252))

        if self._motion_visible("cushion"):
            rect = QRectF(275, 286, 96, 107)
            p.setPen(QPen(QColor(122, 109, 100, 82), 1.0))
            p.setBrush(cloth)
            p.drawRoundedRect(rect, 24, 24)
            for y in range(300, 390, 13):
                p.drawLine(QPointF(283, y), QPointF(363, y + 4))

        if self._motion_visible("picture"):
            patch(QRectF(549, 38, 118, 148), wall)

        if self._motion_visible("notes"):
            patch(QRectF(4, 63, 64, 181), wall)

        if self._motion_visible("puzzle"):
            patch(
                QRectF(533, 249, 121, 74),
                QColor(237, 226, 207, 252),
                ((QPointF(533, 310), QPointF(654, 310)),),
            )

        if self._motion_visible("chest"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(75, 65, 58, 238))
            p.drawRoundedRect(QRectF(915, 411, 184, 121), 8, 8)

        if self._motion_visible("door"):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(70, 65, 61, 245))
            p.drawRoundedRect(QRectF(913, 20, 87, 371), 4, 4)

    def _draw_item_animations(self, p):
        """在原始房间图上叠加各自独立的轻量手绘动画。"""
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 台灯：独立开关，暖光保持到再次点击。
        lamp = self._smooth(self._motion_value("lamp"))
        if lamp > 0.001:
            glow = QRadialGradient(QPointF(322, 211), 92)
            glow.setColorAt(0.0, QColor(255, 221, 145, int(92 * lamp)))
            glow.setColorAt(0.55, QColor(255, 228, 166, int(42 * lamp)))
            glow.setColorAt(1.0, QColor(255, 239, 195, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(230, 119, 184, 184))

        # 书：书脊不动，仅让纸页从右向左翻过。
        book = self._motion_value("book")
        if book > 0.001:
            wave = math.sin(math.pi * book)
            book_source = QRectF(744, 316, 83, 51)
            self._draw_room_crop(p, book_source, book_source, self._rounded_clip(book_source, 3))
            p.save()
            p.translate(780, 341)
            p.setPen(QPen(INK_SOFT, 1.3))
            for index in range(3):
                local = max(0.0, min(1.0, book * 1.35 - index * 0.17))
                bend = math.sin(math.pi * local)
                page = QPainterPath(QPointF(0, 0))
                page.cubicTo(
                    QPointF(18 - 34 * local, -12 - 11 * bend),
                    QPointF(30 - 57 * local, -7 - 18 * bend),
                    QPointF(30 - 60 * local, 2),
                )
                page.lineTo(QPointF(0, 7))
                page.closeSubpath()
                p.setBrush(QColor(255, 250, 239, int(210 + 35 * wave)))
                p.drawPath(page)
            p.restore()

        # 茶杯：短暂出现细水流，随后升起两缕蒸汽。
        cup = self._motion_value("cup")
        if cup > 0.001:
            pour = math.sin(math.pi * min(1.0, cup * 1.65)) if cup < 0.62 else 0.0
            if pour > 0.01:
                p.setPen(QPen(QColor(105, 170, 156, int(205 * pour)), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(531, 220 - 8 * pour), QPointF(531, 252))
                p.setBrush(QColor(105, 170, 156, int(170 * pour)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(528.5, 214 - 9 * pour, 5, 7))
            steam = max(0.0, (cup - 0.42) / 0.58)
            if steam > 0.0:
                p.setPen(QPen(QColor(118, 104, 97, int(135 * (1.0 - steam * 0.45))), 1.4))
                for offset in (-6, 5):
                    path = QPainterPath(QPointF(530 + offset, 252))
                    path.cubicTo(526 + offset, 243 - 11 * steam, 536 + offset, 238 - 18 * steam, 531 + offset, 227 - 23 * steam)
                    p.drawPath(path)

        # 收音机：开机后每个音符拥有自己的相位，持续但不影响其他物件。
        radio = self._smooth(self._motion_value("radio"))
        if radio > 0.01:
            p.setFont(QFont("Segoe UI Symbol", 17))
            p.setPen(QColor(85, 116, 108, int(210 * radio)))
            for index, symbol in enumerate(("♪", "♫", "♪")):
                x = 421 + index * 18
                y = 211 - index * 8 + math.sin(self._phase * 2.1 + index * 1.7) * 7
                p.drawText(QPointF(x, y), symbol)

        # 画布被点到时出现一笔短暂的青绿色弧线。
        canvas = self._motion_value("canvas")
        if canvas > 0.001:
            alpha = int(190 * math.sin(math.pi * canvas))
            p.setPen(QPen(QColor(105, 170, 156, alpha), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            path = QPainterPath(QPointF(771, 153))
            path.cubicTo(789, 126, 820, 182, 841, 145)
            p.drawPath(path)

        # 沙发仅做轻微按压反馈，真正的睡眠切换仍沿用原逻辑。
        sofa = self._motion_value("sofa")
        if sofa > 0.001:
            puff = math.sin(math.pi * sofa)
            p.setPen(QPen(QColor(217, 154, 159, int(125 * puff)), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(121, 335 - puff * 5, 214, 84 + puff * 10), 18 * 16, 144 * 16)

        p.restore()

    def _draw_image_hover(self, painter):
        if not self._hovered:
            return
        rect = self._items[self._hovered]
        pulse = 0.5 + 0.5 * math.sin(self._phase * 2.0)
        color = QColor(29, 173, 151, int(22 + pulse * 18))
        painter.setPen(QPen(QColor(29, 173, 151, 150), 2.0, Qt.PenStyle.DashLine))
        painter.setBrush(color)
        painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 14, 14)

    def _draw_pet_art(self, painter):
        """绘制高细节手绘桌宠；只做极轻呼吸，不拉伸原图。"""
        target_h = 282.0
        target_w = target_h * self._pet_art.width() / self._pet_art.height()
        x = 466.0
        y = 382.0 + math.sin(self._phase * 0.72) * 1.7
        painter.save()
        painter.setOpacity(0.97)
        painter.drawPixmap(
            QRectF(x, y, target_w, target_h),
            self._pet_art,
            QRectF(self._pet_art.rect()),
        )
        painter.restore()

    def _draw_room(self, p):
        p.fillRect(QRectF(30, 28, 1040, 632), QColor("#f7eddc"))
        p.fillRect(QRectF(30, 430, 1040, 230), QColor("#e8d4b8"))
        for y in range(65, 430, 58):
            self._sketch_line(p, QPointF(35, y), QPointF(1065, y + 1), f"wall{y}", 1.0, QColor("#b9a99d"))
        for x in range(60, 1060, 100):
            self._sketch_line(p, QPointF(x, 432), QPointF(x + 42, 657), f"floor{x}", 0.9, QColor("#b4977d"))
        self._sketch_line(p, QPointF(30, 430), QPointF(1070, 430), "baseboard", 3.0)
        p.setPen(QPen(QColor(110, 91, 78, 35), 14))
        p.drawRoundedRect(QRectF(360, 520, 390, 112), 55, 55)
        p.setPen(QPen(QColor("#9d8d80"), 1.4, Qt.PenStyle.DashLine))
        p.drawRoundedRect(QRectF(368, 528, 374, 96), 48, 48)

    def _draw_window_notes(self, p):
        name = "notes"
        lift = self._hover_lift(name)
        p.save(); p.translate(0, lift)
        if self._hovered == name:
            p.fillRect(QRectF(78, 84, 262, 240), QColor(105, 170, 156, 24))
        frame = QRectF(95, 102, 226, 188)
        self._sketch_rect(p, frame, "window", QColor("#dceae7"), 2, 3)
        self._sketch_line(p, QPointF(208, 103), QPointF(208, 289), "windowmidv", 2)
        self._sketch_line(p, QPointF(96, 194), QPointF(320, 194), "windowmidh", 2)
        # 便签绳与三张纸片
        self._sketch_line(p, QPointF(82, 292), QPointF(332, 278), "noterope", 2, QColor("#947a68"))
        for i, (x, y, color) in enumerate(((115, 268, "#f6d99b"), (187, 267, "#f0c1c4"), (261, 256, "#badbd2"))):
            p.save(); p.translate(0, math.sin(self._phase + i) * (1.0 if self._hovered == name else 0.25))
            self._sketch_rect(p, QRectF(x, y, 52, 42), f"note{i}", QColor(color), 3, 1.6)
            self._sketch_line(p, QPointF(x + 10, y + 14), QPointF(x + 41, y + 13), f"nt{i}1", 1, INK_SOFT)
            self._sketch_line(p, QPointF(x + 10, y + 25), QPointF(x + 35, y + 26), f"nt{i}2", 1, INK_SOFT)
            p.restore()
        p.restore()

    def _draw_sofa(self, p):
        name = "sofa"; lift = self._hover_lift(name)
        p.save(); p.translate(0, lift)
        if self._hovered == name:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(217, 154, 159, 24)); p.drawEllipse(QRectF(62, 430, 294, 192))
        self._sketch_rect(p, QRectF(92, 490, 230, 108), "sofaback", QColor("#ead9cb"), 34, 2.8)
        self._sketch_rect(p, QRectF(75, 520, 62, 84), "sofalarm", QColor("#e4cdbd"), 25, 2.4)
        self._sketch_rect(p, QRectF(278, 520, 62, 84), "sofarm", QColor("#e4cdbd"), 25, 2.4)
        self._sketch_rect(p, QRectF(118, 548, 178, 62), "sofaseat", QColor("#f2e5d9"), 22, 2.2)
        self._sketch_rect(p, QRectF(115, 472, 78, 62), "cushion1", QColor("#dfebe4"), 18, 1.6)
        self._sketch_rect(p, QRectF(220, 474, 70, 58), "cushion2", QColor("#efd3d0"), 18, 1.6)
        p.restore()

    def _draw_table_and_puzzle(self, p):
        self._sketch_rect(p, QRectF(385, 455, 380, 42), "tabletop", QColor(WOOD), 8, 3)
        self._sketch_line(p, QPointF(414, 496), QPointF(400, 615), "tableleg1", 6)
        self._sketch_line(p, QPointF(735, 496), QPointF(752, 615), "tableleg2", 6)
        name = "puzzle"; lift = self._hover_lift(name)
        p.save(); p.translate(0, lift)
        board = QRectF(466, 386, 142, 100)
        if self._hovered == name:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(105, 170, 156, 42)); p.drawRoundedRect(board.adjusted(-10, -10, 10, 10), 16, 16)
        self._sketch_rect(p, board, "puzzleboard", QColor("#cfa983"), 8, 2.5)
        p.setFont(QFont("KaiTi", 12, QFont.Weight.Bold)); p.setPen(INK)
        n = 1
        for row in range(3):
            for col in range(4):
                if n == 12:
                    break
                cell = QRectF(477 + col * 30, 397 + row * 27, 25, 22)
                self._sketch_rect(p, cell, f"tile{n}", QColor("#fff3d9"), 4, 1.1)
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(n))
                n += 1
        p.restore()
        # 桌上的细小摆件增加生活感
        self._sketch_rect(p, QRectF(650, 421, 50, 65), "mug", QColor("#d8ece6"), 12, 1.8)
        self._sketch_line(p, QPointF(700, 437), QPointF(716, 450), "mugh1", 2)
        self._sketch_line(p, QPointF(716, 450), QPointF(701, 464), "mugh2", 2)

    def _draw_canvas(self, p):
        name = "canvas"; lift = self._hover_lift(name)
        p.save(); p.translate(0, lift)
        if self._hovered == name:
            p.fillRect(QRectF(808, 78, 225, 270), QColor(105, 170, 156, 24))
        self._sketch_rect(p, QRectF(840, 104, 160, 180), "canvasframe", QColor("#f7dfb8"), 5, 3)
        self._sketch_rect(p, QRectF(851, 115, 138, 158), "canvaspaper", QColor("#fffaf1"), 2, 1.5)
        self._sketch_line(p, QPointF(875, 244), QPointF(911, 170), "paintstem", 4, QColor("#75a071"))
        self._sketch_line(p, QPointF(911, 170), QPointF(947, 230), "paintstem2", 4, QColor("#75a071"))
        p.setPen(QPen(ROSE, 4)); p.setBrush(QColor(217, 154, 159, 70)); p.drawEllipse(QRectF(895, 154, 34, 34))
        self._sketch_line(p, QPointF(875, 284), QPointF(830, 352), "easel1", 5)
        self._sketch_line(p, QPointF(965, 284), QPointF(1009, 352), "easel2", 5)
        self._sketch_line(p, QPointF(920, 284), QPointF(920, 363), "easel3", 5)
        p.restore()

    def _draw_chest(self, p):
        name = "chest"; lift = self._hover_lift(name)
        p.save(); p.translate(0, lift)
        if self._hovered == name:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(105, 170, 156, 30)); p.drawRoundedRect(QRectF(855, 420, 192, 188), 24, 24)
        self._sketch_rect(p, QRectF(884, 478, 134, 112), "chestbody", QColor("#c89e76"), 14, 3)
        lid = QPainterPath(); lid.moveTo(884, 495); lid.quadTo(950, 427, 1018, 495); lid.closeSubpath()
        p.fillPath(lid, QColor("#d6b28c")); p.setPen(QPen(INK, 3)); p.drawPath(lid)
        self._sketch_rect(p, QRectF(938, 514, 28, 34), "chestlock", QColor("#e7c974"), 5, 1.8)
        p.restore()

    def _draw_door(self, p):
        name = "door"; lift = self._hover_lift(name)
        p.save(); p.translate(0, lift)
        self._sketch_rect(p, QRectF(1023, 235, 58, 226), "door", QColor("#d5b48f"), 18, 3)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(TEAL if self._hovered == name else QColor("#ad8767")); p.drawEllipse(QRectF(1033, 344, 10, 10))
        p.restore()

    def _draw_pet(self, p):
        """小屋专用手绘分身：双辫、大眼、宽松白卫衣、厚底鞋。"""
        p.save(); p.translate(620, 225 + math.sin(self._phase * 0.75) * 2.0)
        # 头发后层与大头轮廓
        p.setPen(QPen(INK, 3)); p.setBrush(QColor("#5a4740")); p.drawEllipse(QRectF(-92, -96, 184, 166))
        p.setBrush(QColor("#f8d8c9")); p.drawEllipse(QRectF(-72, -75, 144, 132))
        # 刘海
        p.setBrush(QColor("#5a4740"));
        for i, x in enumerate((-55, -32, -8, 17, 40)):
            path = QPainterPath(QPointF(x - 17, -65)); path.quadTo(x, -98 + (i % 2) * 5, x + 16, -54); path.quadTo(x, -40, x - 17, -65); p.drawPath(path)
        # 大眼睛
        for x in (-33, 33):
            p.setBrush(QColor("#fffdf8")); p.setPen(QPen(INK, 2.3)); p.drawEllipse(QRectF(x - 18, -39, 36, 31))
            p.setBrush(QColor("#755845")); p.drawEllipse(QRectF(x - 10, -34, 21, 25))
            p.setBrush(QColor("#2f2725")); p.drawEllipse(QRectF(x - 5, -29, 11, 17))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("white")); p.drawEllipse(QRectF(x - 3, -30, 5, 5))
        p.setPen(QPen(ROSE, 2)); p.drawArc(QRectF(-13, 2, 26, 14), 205 * 16, 130 * 16)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(217, 154, 159, 55)); p.drawEllipse(QRectF(-62, -2, 26, 12)); p.drawEllipse(QRectF(36, -2, 26, 12))
        # 双辫子
        p.setPen(QPen(INK, 2)); p.setBrush(QColor("#57443d"))
        for side in (-1, 1):
            for i in range(4):
                p.drawEllipse(QRectF(side * 68 - 12, 25 + i * 21, 24, 29))
            p.setBrush(QColor("#2d2928")); p.drawRoundedRect(QRectF(side * 68 - 10, 108, 20, 8), 3, 3)
            p.setBrush(QColor("#57443d")); p.drawEllipse(QRectF(side * 68 - 12, 114, 24, 25))
        # 宽松连帽卫衣
        hoodie = QPainterPath(QPointF(-57, 58)); hoodie.quadTo(-78, 75, -67, 142); hoodie.quadTo(-55, 166, 0, 162); hoodie.quadTo(55, 166, 67, 142); hoodie.quadTo(78, 75, 57, 58); hoodie.closeSubpath()
        p.setPen(QPen(INK, 2.7)); p.setBrush(QColor("#fff8ee")); p.drawPath(hoodie)
        p.drawArc(QRectF(-35, 47, 70, 48), 10 * 16, 160 * 16)
        p.drawRoundedRect(QRectF(-28, 116, 56, 29), 10, 10)
        # 腿、袜子、厚底鞋
        p.setBrush(QColor("#f8d8c9")); p.drawRoundedRect(QRectF(-37, 150, 28, 68), 13, 13); p.drawRoundedRect(QRectF(9, 150, 28, 68), 13, 13)
        p.setBrush(QColor("#fffdf6")); p.drawRoundedRect(QRectF(-39, 199, 31, 34), 8, 8); p.drawRoundedRect(QRectF(8, 199, 31, 34), 8, 8)
        p.drawRoundedRect(QRectF(-52, 220, 46, 28), 12, 12); p.drawRoundedRect(QRectF(6, 220, 46, 28), 12, 12)
        p.setPen(QPen(INK_SOFT, 1.2));
        for x in (-44, 14):
            p.drawLine(x, 230, x + 28, 230); p.drawLine(x + 4, 224, x + 23, 237); p.drawLine(x + 23, 224, x + 4, 237)
        p.restore()

    def _draw_hover_label(self, p):
        if not self._hovered:
            return
        rect = self._items[self._hovered]
        text = self._labels[self._hovered]
        label = QRectF(rect.center().x() - 66, rect.top() - 38, 132, 30)
        if label.top() < 35:
            label.moveTop(rect.bottom() + 8)
        self._sketch_rect(p, label, "label" + self._hovered, QColor(255, 250, 241, 245), 12, 1.5)
        p.setPen(INK); p.setFont(QFont("KaiTi", 13, QFont.Weight.Bold)); p.drawText(label, Qt.AlignmentFlag.AlignCenter, text)

    def showEvent(self, event):
        self._return_emitted = False
        door = self._motions.get("door")
        if door is not None:
            door.update(value=0.0, target=0.0, elapsed=0.0, active=False)
        super().showEvent(event)

    def closeEvent(self, event):
        if not self._return_emitted:
            self._return_emitted = True
            self.returned_to_desktop.emit()
        super().closeEvent(event)


# The refined renderer reads genuine transparent object sprites. Keeping the
# legacy class above provides a safe fallback while the remaining temporary
# assets are progressively replaced.
from house_scene_refined import HandDrawnHouse as HandDrawnHouse
