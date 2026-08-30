import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl, Signal
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


INK = QColor("#514943")
INK_SOFT = QColor("#857972")
PAPER = QColor("#faf5e9")
PAPER_LIGHT = QColor("#fffaf1")
TEAL = QColor("#7faea3")
ROSE = QColor("#d8a2a4")
WOOD = QColor("#d9c1a3")
GLASS = QColor(205, 226, 225, 72)


class NumberPuzzleDialog(QDialog):
    """小屋桌面上的 4×4 数字华容道。"""

    def __init__(self, parent=None, save_path: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("桌上的数字华容道")
        self.setMinimumSize(430, 500)
        self.save_path = Path(save_path) if save_path else None
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
                "QPushButton{background:#fff8e9;color:#514943;border:2px solid #857972;"
                "border-radius:12px;font:700 22px 'KaiTi';}"
                "QPushButton:hover{background:#e5f2ed;border-color:#7faea3;}"
            )
            self.buttons.append(button)
            grid.addWidget(button, index // 4, index % 4)
        root.addLayout(grid)
        row = QHBoxLayout()
        shuffle = QPushButton("重新打乱")
        shuffle.clicked.connect(self._shuffle)
        save = QPushButton("保存当前局面")
        save.clicked.connect(self._save_state)
        close = QPushButton("收起来")
        close.clicked.connect(self.accept)
        row.addWidget(shuffle)
        row.addWidget(save)
        row.addStretch()
        row.addWidget(close)
        root.addLayout(row)
        if not self._load_state():
            self._shuffle()

    def _load_state(self):
        if self.save_path is None or not self.save_path.is_file():
            return False
        try:
            payload = json.loads(self.save_path.read_text(encoding="utf-8"))
            values = payload.get("values")
        except (OSError, ValueError, AttributeError):
            return False
        if (
            not isinstance(values, list)
            or len(values) != 16
            or sorted(values) != list(range(16))
        ):
            return False
        self.values = values
        self._refresh()
        return True

    def _save_state(self):
        if self.save_path is None:
            QMessageBox.warning(self, "没有保存位置", "暂时无法保存这个局面。")
            return
        try:
            self.save_path.parent.mkdir(parents=True, exist_ok=True)
            self.save_path.write_text(
                json.dumps({"values": self.values}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        QMessageBox.information(self, "已经保存", "下次打开数字华容道时，会继续这个局面。")

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
                    index = nr * 4 + nc
                    if index != previous:
                        choices.append(index)
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
        self.lines = []
        self.current = None
        self.color = INK
        self.width_value = 4.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.current = [event.position()]
            self.lines.append((QColor(self.color), self.width_value, self.current))

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
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for start, end in zip(points, points[1:]):
                painter.drawLine(start, end)


class DrawingPadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("画架上的画布")
        root = QVBoxLayout(self)
        self.canvas = DrawingCanvas(self)
        root.addWidget(self.canvas)
        controls = QHBoxLayout()
        for color in ("#514943", "#7faea3", "#d8a2a4", "#d29a62", "#fffaf1"):
            button = QPushButton()
            button.setFixedSize(34, 34)
            button.setStyleSheet(f"background:{color};border:2px solid #857972;border-radius:17px;")
            button.clicked.connect(lambda _checked=False, c=color: self._select(c))
            controls.addWidget(button)
        controls.addStretch()
        clear = QPushButton("清空")
        clear.clicked.connect(lambda: (self.canvas.lines.clear(), self.canvas.update()))
        save = QPushButton("保存画作…")
        save.clicked.connect(self._save)
        controls.addWidget(clear)
        controls.addWidget(save)
        root.addLayout(controls)

    def _select(self, color):
        self.canvas.color = QColor(color)
        self.canvas.width_value = 18.0 if color == "#fffaf1" else 4.0

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存画作", "桌宠的小画.png", "PNG 图片 (*.png)")
        if path and self.canvas.grab().save(path, "PNG"):
            QMessageBox.information(self, "保存完成", "画作已经收好啦。")


@dataclass(frozen=True)
class ItemSpec:
    rect: QRectF
    mode: str = "oneshot"
    duration: float = 0.8


class HandDrawnHouse(QWidget):
    """干净母版 + 独立物件的小屋；每件物品拥有互不干扰的动画状态。"""

    returned_to_desktop = Signal()
    request_sleep = Signal()

    SCENE_H = 700.0
    SCENE_W = 1586.0 / 992.0 * SCENE_H

    def __init__(self, inbox_path, parent=None):
        super().__init__(parent)
        self.base_dir = Path(__file__).parent
        self.inbox_path = Path(inbox_path)
        self.notes_path = self.inbox_path / "桌宠便签.txt"
        self._room = QPixmap(str(self.base_dir / "assets" / "house" / "room_base_master_v1.png"))
        tea_dir = self.base_dir / "assets" / "house" / "objects" / "tea"
        self._tea_frames = [QPixmap(str(tea_dir / f"tea_pour_{i:02d}_runtime.png")) for i in range(1, 7)]
        self.setWindowTitle("桌宠的小屋")
        self.setMinimumSize(930, 590)
        self.resize(1120, 700)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#faf5e9;")
        self._phase = 0.0
        self._pressed = ""
        self._scale = 1.0
        self._origin = QPointF()
        self._return_emitted = False
        self._puzzle_dialog = None
        self._drawing_dialog = None

        # 小物件优先登记，防止被沙发、桌子等大热区截走。
        self._items = {
            "notes": ItemSpec(QRectF(80, 218, 192, 50), "oneshot", 0.72),
            "window_left": ItemSpec(QRectF(82, 20, 86, 210), "toggle", 0.55),
            "window_right": ItemSpec(QRectF(170, 20, 86, 210), "toggle", 0.55),
            "curtain_left": ItemSpec(QRectF(58, 0, 45, 270), "toggle", 0.72),
            "curtain_right": ItemSpec(QRectF(244, 0, 42, 270), "toggle", 0.72),
            "hanging_plant": ItemSpec(QRectF(262, 28, 66, 126), "oneshot", 1.35),
            "window_plant": ItemSpec(QRectF(174, 180, 72, 82), "oneshot", 1.0),
            "picture_left": ItemSpec(QRectF(538, 82, 52, 66), "oneshot", 0.9),
            "picture_right": ItemSpec(QRectF(604, 58, 56, 72), "oneshot", 0.9),
            "wall_clock": ItemSpec(QRectF(472, 48, 44, 94), "toggle", 0.35),
            "side_lamp": ItemSpec(QRectF(30, 365, 74, 108), "toggle", 0.4),
            "side_drawer": ItemSpec(QRectF(0, 468, 155, 80), "toggle", 0.4),
            "cushion_left": ItemSpec(QRectF(110, 306, 91, 83), "oneshot", 0.68),
            "cushion_right": ItemSpec(QRectF(206, 312, 93, 80), "oneshot", 0.68),
            "sofa": ItemSpec(QRectF(45, 280, 360, 300), "oneshot", 0.55),
            "books": ItemSpec(QRectF(302, 247, 83, 52), "oneshot", 0.9),
            "radio": ItemSpec(QRectF(386, 238, 84, 55), "toggle", 0.3),
            "rear_drawer": ItemSpec(QRectF(304, 306, 184, 46), "toggle", 0.4),
            "toy_car": ItemSpec(QRectF(497, 238, 74, 42), "toggle", 0.9),
            "tea": ItemSpec(QRectF(466, 208, 112, 82), "oneshot", 2.4),
            "book": ItemSpec(QRectF(565, 245, 64, 40), "oneshot", 1.0),
            "puzzle": ItemSpec(QRectF(640, 247, 98, 50), "oneshot", 0.45),
            "paint_jar": ItemSpec(QRectF(780, 249, 56, 54), "oneshot", 0.8),
            "canvas": ItemSpec(QRectF(748, 94, 114, 156), "oneshot", 0.45),
            "chest": ItemSpec(QRectF(916, 392, 202, 265), "toggle", 0.6),
            "door": ItemSpec(QRectF(924, 18, 108, 382), "toggle", 0.65),
        }
        self._state = {
            name: {"value": 0.0, "target": 0.0, "elapsed": 0.0, "active": False}
            for name in self._items
        }
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @staticmethod
    def _smooth(value):
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def _tick(self):
        self._phase += 0.055
        dt = self._timer.interval() / 1000.0
        for name, state in self._state.items():
            spec = self._items[name]
            if spec.mode == "toggle":
                delta = state["target"] - state["value"]
                if abs(delta) > 0.001:
                    step = min(abs(delta), dt / spec.duration)
                    state["value"] += step if delta > 0 else -step
                    state["active"] = True
                else:
                    state["value"] = state["target"]
                    state["active"] = False
            elif state["active"]:
                state["elapsed"] += dt
                state["value"] = min(1.0, state["elapsed"] / spec.duration)
                if state["value"] >= 1.0:
                    state.update(value=0.0, elapsed=0.0, active=False)
        self.update()

    def _value(self, name):
        return self._state[name]["value"]

    def _trigger(self, name):
        state = self._state[name]
        spec = self._items[name]
        if spec.mode == "toggle":
            state["target"] = 0.0 if state["target"] >= 0.5 else 1.0
            state["active"] = True
            return state["target"] >= 0.5
        state.update(value=0.0, elapsed=0.0, active=True)
        return True

    def _scene_point(self, point):
        return QPointF((point.x() - self._origin.x()) / self._scale, (point.y() - self._origin.y()) / self._scale)

    def _item_at(self, point):
        for name, spec in self._items.items():
            if spec.rect.contains(point):
                return name
        return ""

    def mouseMoveEvent(self, event):
        item = self._item_at(self._scene_point(event.position()))
        self.setCursor(Qt.CursorShape.PointingHandCursor if item else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, event):
        self._pressed = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = self._item_at(self._scene_point(event.position()))

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        released = self._item_at(self._scene_point(event.position()))
        selected = self._pressed if released == self._pressed else ""
        self._pressed = ""
        if selected:
            self._activate(selected)

    def _activate(self, name):
        opened = self._trigger(name)
        if name == "puzzle":
            if self._puzzle_dialog is None:
                self._puzzle_dialog = NumberPuzzleDialog(self)
                self._puzzle_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                self._puzzle_dialog.destroyed.connect(lambda: setattr(self, "_puzzle_dialog", None))
            self._puzzle_dialog.show()
            self._puzzle_dialog.raise_()
        elif name == "canvas":
            if self._drawing_dialog is None:
                self._drawing_dialog = DrawingPadDialog(self)
                self._drawing_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                self._drawing_dialog.destroyed.connect(lambda: setattr(self, "_drawing_dialog", None))
            self._drawing_dialog.show()
            self._drawing_dialog.raise_()
        elif name == "notes":
            self.inbox_path.mkdir(parents=True, exist_ok=True)
            if not self.notes_path.exists():
                self.notes_path.write_text("把文字拖给桌宠后，便签会出现在这里。\n", encoding="utf-8")
            QTimer.singleShot(220, lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.notes_path))))
        elif name == "chest" and opened:
            self.inbox_path.mkdir(parents=True, exist_ok=True)
            QTimer.singleShot(620, lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.inbox_path))))
        elif name == "sofa":
            QTimer.singleShot(360, self.request_sleep.emit)
            QTimer.singleShot(390, self._leave_house)
        elif name == "door" and opened:
            QTimer.singleShot(680, self._leave_house)

    def _leave_house(self):
        if not self._return_emitted:
            self._return_emitted = True
            self.returned_to_desktop.emit()
        self.hide()

    def showEvent(self, event):
        self._return_emitted = False
        door = self._state["door"]
        door.update(value=0.0, target=0.0, elapsed=0.0, active=False)
        super().showEvent(event)

    def closeEvent(self, event):
        if not self._return_emitted:
            self._return_emitted = True
            self.returned_to_desktop.emit()
        super().closeEvent(event)

    @staticmethod
    def _seed(key):
        return sum((index + 1) * ord(char) for index, char in enumerate(key))

    def _line(self, p, a, b, key, width=1.7, color=INK):
        rng = random.Random(self._seed(key))
        for pass_index, alpha in ((0, 222), (1, 68)):
            mid = QPointF((a.x() + b.x()) / 2 + rng.uniform(-1.5, 1.5), (a.y() + b.y()) / 2 + rng.uniform(-1.5, 1.5))
            shade = QColor(color)
            shade.setAlpha(alpha)
            p.setPen(QPen(shade, max(0.65, width - pass_index * 0.45), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            path = QPainterPath(a)
            path.quadTo(mid, b)
            p.drawPath(path)

    def _rounded(self, p, rect, key, fill=PAPER_LIGHT, radius=6.0, width=1.7):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(rect, radius, radius)
        self._line(p, rect.topLeft(), rect.topRight(), key + "t", width)
        self._line(p, rect.topRight(), rect.bottomRight(), key + "r", width)
        self._line(p, rect.bottomRight(), rect.bottomLeft(), key + "b", width)
        self._line(p, rect.bottomLeft(), rect.topLeft(), key + "l", width)

    def _poly(self, p, points, fill, key, width=1.7):
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawPath(path)
        for index, (a, b) in enumerate(zip(points, points[1:] + points[:1])):
            self._line(p, a, b, f"{key}{index}", width)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), PAPER)
        self._scale = min(self.width() / self.SCENE_W, self.height() / self.SCENE_H)
        self._origin = QPointF((self.width() - self.SCENE_W * self._scale) / 2, (self.height() - self.SCENE_H * self._scale) / 2)
        p.translate(self._origin)
        p.scale(self._scale, self._scale)
        if not self._room.isNull():
            p.drawPixmap(QRectF(0, 0, self.SCENE_W, self.SCENE_H), self._room, QRectF(self._room.rect()))
        self._draw_back_wall_items(p)
        self._draw_sofa_items(p)
        self._draw_rear_cabinet_items(p)
        self._draw_table_items(p)
        self._draw_easel_items(p)
        self._draw_door_and_chest(p)

    def _draw_window_sash(self, p, rect, amount, side):
        amount = self._smooth(amount)
        visible_w = rect.width() * (1.0 - amount * 0.80)
        target = QRectF(rect.left() if side == "left" else rect.right() - visible_w, rect.top(), visible_w, rect.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(GLASS)
        p.drawRect(target.adjusted(3, 3, -3, -3))
        self._rounded(p, target, "sash" + side, QColor(247, 244, 235, 130), 1.5, 2.0)
        if visible_w > 25:
            self._line(p, QPointF(target.center().x(), target.top()), QPointF(target.center().x(), target.bottom()), "sashvm" + side, 1.3)
            self._line(p, QPointF(target.left(), target.center().y()), QPointF(target.right(), target.center().y()), "sashhm" + side, 1.3)

    def _draw_curtain(self, p, x, side, amount):
        amount = self._smooth(amount)
        width = 54 - amount * 30
        shift = (-amount * 22) if side == "left" else amount * 22
        p.save()
        p.translate(x + shift, 0)
        path = QPainterPath(QPointF(0, 0))
        path.lineTo(width, 0)
        path.cubicTo(width - 4, 75, width + 7, 165, width - 6, 256)
        path.quadTo(width / 2, 270, 1, 256)
        path.cubicTo(8, 165, -5, 80, 0, 0)
        path.closeSubpath()
        p.setBrush(QColor(226, 231, 220, 210))
        p.setPen(QPen(INK_SOFT, 1.5))
        p.drawPath(path)
        p.setPen(QPen(QColor(115, 124, 113, 65), 1.0))
        for ratio in (0.25, 0.5, 0.75):
            p.drawLine(QPointF(width * ratio, 5), QPointF(width * ratio + math.sin(self._phase + ratio) * 2, 252))
        p.restore()

    def _draw_back_wall_items(self, p):
        self._draw_window_sash(p, QRectF(84, 14, 84, 218), self._value("window_left"), "left")
        self._draw_window_sash(p, QRectF(171, 14, 84, 218), self._value("window_right"), "right")
        self._draw_curtain(p, 52, "left", self._value("curtain_left"))
        self._draw_curtain(p, 247, "right", self._value("curtain_right"))

        notes = self._value("notes")
        self._line(p, QPointF(83, 225), QPointF(270, 218), "noterope", 1.5, INK_SOFT)
        for i, (x, color) in enumerate(((98, "#efd69f"), (146, "#e6c1bf"), (194, "#c4ded5"), (241, "#e8d6ae"))):
            flutter = math.sin(notes * math.pi * 5 + i) * (1.0 - notes) * 5 if notes else 0
            p.save()
            p.translate(flutter, abs(flutter) * 0.25)
            self._rounded(p, QRectF(x, 214 + i % 2 * 5, 35, 42), "note" + str(i), QColor(color), 2, 1.1)
            p.setPen(QPen(QColor(105, 92, 84, 90), 0.8))
            p.drawLine(x + 7, 229 + i % 2 * 5, x + 28, 228 + i % 2 * 5)
            p.drawLine(x + 7, 238 + i % 2 * 5, x + 24, 239 + i % 2 * 5)
            p.restore()

        plant = self._value("hanging_plant")
        p.save()
        p.translate(292, 35)
        p.rotate(math.sin(plant * math.pi * 4) * (1 - plant) * 7 if plant else 0)
        self._line(p, QPointF(0, -44), QPointF(0, 12), "hangcord", 1.6)
        self._rounded(p, QRectF(-25, 12, 50, 28), "hangpot", QColor("#d9c1a3"), 9, 1.6)
        p.setBrush(QColor("#a9bda7"))
        p.setPen(QPen(INK_SOFT, 1.0))
        for i in range(9):
            angle = -1.25 + i * 0.31
            p.drawEllipse(QRectF(math.sin(angle) * 30 - 8, 34 + i % 3 * 12, 16, 34))
        p.restore()

        plant = self._value("window_plant")
        p.save()
        p.translate(209, 199)
        p.rotate(math.sin(plant * math.pi * 4) * (1 - plant) * 6 if plant else 0)
        self._rounded(p, QRectF(-24, 35, 48, 30), "windowpot", QColor("#d7baa0"), 5, 1.5)
        p.setPen(QPen(QColor("#748f75"), 2.0))
        for i in range(7):
            x = -22 + i * 7
            p.drawLine(QPointF(0, 36), QPointF(x, 1 + abs(i - 3) * 4))
            p.setBrush(QColor("#a8bfa7"))
            p.drawEllipse(QRectF(x - 7, -3 + abs(i - 3) * 4, 15, 25))
        p.restore()

        clock_on = self._smooth(self._value("wall_clock"))
        self._rounded(p, QRectF(472, 48, 44, 52), "clock", QColor("#f2e7d5"), 16, 1.5)
        p.setPen(QPen(INK, 1.3))
        p.drawLine(QPointF(494, 74), QPointF(494, 57))
        p.drawLine(QPointF(494, 74), QPointF(505, 79))
        self._line(p, QPointF(494, 100), QPointF(494 + math.sin(self._phase * 2.6) * 10 * clock_on, 131), "pendulum", 1.4)
        p.setBrush(QColor("#c6a577"))
        p.drawEllipse(QRectF(487 + math.sin(self._phase * 2.6) * 10 * clock_on, 126, 14, 14))

        for name, rect, color in (
            ("picture_left", QRectF(541, 85, 46, 58), "#dce4dd"),
            ("picture_right", QRectF(607, 61, 50, 66), "#ead8d3"),
        ):
            value = self._value(name)
            angle = math.sin(value * math.pi * 5) * (1 - value) * 6 if value else 0
            p.save()
            p.translate(rect.center())
            p.rotate(angle)
            local = QRectF(-rect.width() / 2, -rect.height() / 2, rect.width(), rect.height())
            self._rounded(p, local, name, QColor("#efe1c9"), 2, 1.6)
            self._rounded(p, local.adjusted(5, 5, -5, -5), name + "art", QColor(color), 1, 0.9)
            p.setPen(QPen(QColor(105, 128, 112, 110), 1.1))
            p.drawArc(local.adjusted(11, 12, -11, -10), 20 * 16, 140 * 16)
            p.restore()

    def _draw_lamp(self, p):
        on = self._smooth(self._value("side_lamp"))
        if on > 0.01:
            glow = QRadialGradient(QPointF(67, 395), 105)
            glow.setColorAt(0, QColor(255, 218, 139, int(98 * on)))
            glow.setColorAt(1, QColor(255, 235, 180, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(-38, 290, 210, 210))
        p.setPen(QPen(INK, 1.6))
        p.setBrush(QColor("#ead8b6"))
        shade = QPainterPath(QPointF(36, 389))
        shade.lineTo(QPointF(98, 389))
        shade.lineTo(QPointF(86, 348))
        shade.lineTo(QPointF(48, 348))
        shade.closeSubpath()
        p.drawPath(shade)
        self._line(p, QPointF(67, 389), QPointF(67, 453), "lamppole", 2.0)
        p.setBrush(QColor("#c9ac82"))
        p.drawEllipse(QRectF(48, 446, 38, 12))

    def _draw_cushion(self, p, name, rect, color):
        value = self._value(name)
        squash = math.sin(math.pi * value) if value else 0
        target = QRectF(rect.x() - rect.width() * squash * 0.035, rect.y() + rect.height() * squash * 0.05,
                        rect.width() * (1 + squash * 0.07), rect.height() * (1 - squash * 0.10))
        self._rounded(p, target, name, QColor(color), 18, 1.5)
        p.setPen(QPen(QColor(120, 107, 97, 48), 0.8))
        for i in range(4):
            p.drawArc(target.adjusted(8 + i * 8, 9, -10, -8), 30 * 16, 120 * 16)

    def _draw_sofa_items(self, p):
        self._draw_lamp(p)
        drawer = self._smooth(self._value("side_drawer"))
        drawer_rect = QRectF(17, 487 + 18 * drawer, 118, 42)
        self._rounded(p, drawer_rect, "sideDrawer", QColor("#eadcc7"), 3, 1.5)
        p.setBrush(QColor("#9b8977"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(71, drawer_rect.y() + 15, 10, 7))
        self._draw_cushion(p, "cushion_left", QRectF(110, 306, 91, 83), "#dbe7df")
        self._draw_cushion(p, "cushion_right", QRectF(206, 312, 93, 80), "#ead2d0")
        sofa = self._value("sofa")
        if sofa:
            pulse = math.sin(math.pi * sofa)
            p.setPen(QPen(QColor(216, 162, 164, int(115 * pulse)), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(75, 391 - pulse * 4, 280, 96 + pulse * 8), 20 * 16, 140 * 16)

    def _draw_rear_cabinet_items(self, p):
        drawer = self._smooth(self._value("rear_drawer"))
        rect = QRectF(309, 305 + 17 * drawer, 172, 40)
        self._rounded(p, rect, "rearDrawer", QColor("#ded0bd"), 2, 1.3)
        p.setBrush(QColor("#9c8875"))
        p.setPen(Qt.PenStyle.NoPen)
        for x in (350, 435):
            p.drawEllipse(QRectF(x, rect.y() + 14, 9, 6))

        book = self._value("books")
        lean = math.sin(math.pi * book) * 8 if book else 0
        colors = ("#d7b79b", "#bdcfc4", "#e6ccb0", "#c8b3aa")
        for i, color in enumerate(colors):
            p.save()
            p.translate(314 + i * 17, 244)
            p.rotate(lean * (i / 5))
            self._rounded(p, QRectF(0, 0, 15, 52), "shelfBook" + str(i), QColor(color), 1, 1.0)
            p.restore()

        radio = self._smooth(self._value("radio"))
        self._rounded(p, QRectF(390, 244, 76, 47), "radio", QColor("#d6c0a5"), 5, 1.6)
        p.setBrush(QColor("#b8aca0"))
        p.setPen(QPen(INK_SOFT, 1.0))
        p.drawEllipse(QRectF(398, 255, 27, 27))
        p.drawEllipse(QRectF(431, 255, 27, 27))
        if radio > 0.01:
            p.setFont(QFont("Segoe UI Symbol", 16))
            p.setPen(QColor(92, 129, 119, int(210 * radio)))
            for i, symbol in enumerate(("♪", "♫", "♪")):
                p.drawText(QPointF(401 + i * 25, 232 - i * 5 + math.sin(self._phase * 2 + i) * 5), symbol)

        car = self._smooth(self._value("toy_car"))
        car_x = 493 + car * 54
        p.save()
        p.translate(car_x, 250 - abs(math.sin(car * math.pi * 3)) * 2)
        self._rounded(p, QRectF(0, 0, 50, 24), "toyCar", QColor("#c9ded7"), 7, 1.3)
        p.setBrush(QColor("#6f6863"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(7, 18, 11, 11))
        p.drawEllipse(QRectF(34, 18, 11, 11))
        p.restore()

    def _draw_open_book(self, p):
        value = self._value("book")
        self._rounded(p, QRectF(562, 247, 70, 36), "bookbase", QColor("#f1e5d0"), 2, 1.3)
        p.setPen(QPen(INK_SOFT, 1.1))
        p.drawLine(QPointF(597, 249), QPointF(597, 281))
        if value:
            for i in range(3):
                local = max(0.0, min(1.0, value * 1.4 - i * 0.16))
                bend = math.sin(math.pi * local)
                page = QPainterPath(QPointF(597, 250))
                page.cubicTo(QPointF(616 - 34 * local, 240 - 10 * bend), QPointF(630 - 60 * local, 251 - 15 * bend), QPointF(631 - 66 * local, 280))
                page.lineTo(QPointF(597, 281))
                page.closeSubpath()
                p.setBrush(QColor(255, 250, 239, 238))
                p.setPen(QPen(INK_SOFT, 0.9))
                p.drawPath(page)

    def _draw_tea(self, p):
        value = self._value("tea")
        frame = 0 if value <= 0 else min(5, int(value * 6))
        pixmap = self._tea_frames[frame] if frame < len(self._tea_frames) else QPixmap()
        if not pixmap.isNull():
            p.drawPixmap(QRectF(449, 188, 138, 123), pixmap, QRectF(pixmap.rect()))
        else:
            self._rounded(p, QRectF(570, 228, 55, 54), "kettle", QColor("#eee2cf"), 22, 1.4)
            self._rounded(p, QRectF(650, 248, 38, 34), "cup", QColor("#f4eadd"), 9, 1.3)

    def _draw_puzzle(self, p):
        value = self._value("puzzle")
        lift = math.sin(math.pi * value) * 4 if value else 0
        p.save()
        p.translate(0, -lift)
        board = QRectF(640, 249, 98, 50)
        self._rounded(p, board, "puzzleBoard", QColor("#cfad86"), 4, 1.5)
        p.setFont(QFont("KaiTi", 8, QFont.Weight.Bold))
        p.setPen(INK)
        n = 1
        for row in range(3):
            for col in range(4):
                cell = QRectF(646 + col * 21, 255 + row * 13, 17, 11)
                self._rounded(p, cell, f"tile{n}", QColor("#fff4dd"), 1, 0.7)
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(n))
                n += 1
        p.restore()

    def _draw_table_items(self, p):
        self._draw_open_book(p)
        self._draw_tea(p)
        self._draw_puzzle(p)

    def _draw_easel_items(self, p):
        value = self._value("canvas")
        self._rounded(p, QRectF(748, 92, 114, 158), "canvas", QColor("#fffaf1"), 2, 1.6)
        p.setPen(QPen(QColor(111, 145, 125), 2.2))
        p.drawLine(QPointF(774, 224), QPointF(802, 151))
        p.drawLine(QPointF(802, 151), QPointF(835, 216))
        p.setPen(QPen(ROSE, 2.5))
        p.drawEllipse(QRectF(793, 138, 24, 24))
        if value:
            alpha = int(210 * math.sin(math.pi * value))
            p.setPen(QPen(QColor(92, 157, 142, alpha), 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            path = QPainterPath(QPointF(765, 130))
            path.cubicTo(785, 112, 824, 178, 847, 127)
            p.drawPath(path)

        jar = self._value("paint_jar")
        p.save()
        p.translate(801, 266)
        p.rotate(math.sin(jar * math.pi * 5) * (1 - jar) * 8 if jar else 0)
        self._rounded(p, QRectF(-21, 0, 42, 34), "paintJar", QColor("#c7ddd5"), 7, 1.3)
        for i, color in enumerate(("#7faea3", "#d8a2a4", "#d6a66b")):
            p.setPen(QPen(QColor(color), 2.0))
            p.drawLine(QPointF(-12 + i * 11, 2), QPointF(-16 + i * 12, -28 - i * 3))
        p.restore()

    def _draw_door_and_chest(self, p):
        door = self._smooth(self._value("door"))
        width = max(16.0, 93 * (1.0 - door * 0.82))
        rect = QRectF(1024 - width, 20, width, 380)
        self._rounded(p, rect, "doorPanel", QColor("#d9c1a3"), 3, 2.0)
        if width > 32:
            self._rounded(p, rect.adjusted(10, 18, -10, -205), "doorTop", QColor("#e5d2b8"), 2, 1.0)
            self._rounded(p, rect.adjusted(10, 192, -10, -18), "doorBottom", QColor("#e5d2b8"), 2, 1.0)
        p.setBrush(QColor("#9a8168"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(rect.left() + 7, 218, 8, 8))

        chest = self._smooth(self._value("chest"))
        closed = (QPointF(916, 407), QPointF(1117, 407), QPointF(1117, 475), QPointF(916, 475))
        opened = (QPointF(934, 356), QPointF(1100, 356), QPointF(1082, 395), QPointF(948, 395))
        points = [QPointF(a.x() + (b.x() - a.x()) * chest, a.y() + (b.y() - a.y()) * chest) for a, b in zip(closed, opened)]
        self._poly(p, points, QColor("#dfc8aa"), "chestLid", 1.8)
        p.setPen(QPen(QColor(115, 103, 94, 70), 0.8))
        for ratio in (0.24, 0.48, 0.72):
            left = QPointF(points[0].x() + (points[3].x() - points[0].x()) * ratio, points[0].y() + (points[3].y() - points[0].y()) * ratio)
            right = QPointF(points[1].x() + (points[2].x() - points[1].x()) * ratio, points[1].y() + (points[2].y() - points[1].y()) * ratio)
            p.drawLine(left, right)
