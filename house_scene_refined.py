import json
import math
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
    QPolygonF,
    QRadialGradient,
    QTransform,
)
from PySide6.QtWidgets import QWidget

from house_scene_v2 import DrawingPadDialog, NumberPuzzleDialog
from reader_dialog import BookReaderDialog, BookshelfManagerDialog


PAPER = QColor("#faf5e9")
INK = QColor("#514943")


@dataclass(frozen=True)
class ItemSpec:
    rect: QRectF
    asset: str | None
    mode: str = "oneshot"
    duration: float = 0.8
    z: int = 30
    alpha_hit: bool = True


class HandDrawnHouse(QWidget):
    """Refined room base with true-RGBA independent object sprites."""

    returned_to_desktop = Signal()
    request_sleep = Signal()

    SCENE_W = 1586.0
    SCENE_H = 992.0

    def __init__(self, inbox_path, parent=None):
        super().__init__(parent)
        self.base_dir = Path(__file__).parent
        self.inbox_path = Path(inbox_path)
        self.notes_path = self.inbox_path / "桌宠便签.txt"
        self.asset_dir = self.base_dir / "assets" / "house" / "objects" / "refined"
        self._room = QPixmap(str(self.base_dir / "assets" / "house" / "room_base_master_v2.png"))
        # Sofa state is intentionally a complete room plate: this preserves
        # the person-to-cushion contact and floor-plane perspective that a
        # separately composited sprite cannot reliably reproduce.
        self._room_sofa = QPixmap(
            str(self.base_dir / "assets" / "house" / "room_base_sofa_rest_v7.png")
        )
        # Reading at the centre table is also a complete room plate.  Baking
        # the character into the room keeps her torso behind the tabletop and
        # her feet naturally grounded beneath it.
        self._room_chair = QPixmap(
            str(self.base_dir / "assets" / "house" / "room_base_chair_read_v1.png")
        )
        # The painting state uses one baked plate as well: its depth ordering
        # keeps the painter behind the table while her feet stay in front of
        # the easel, which a foreground-only sprite cannot express cleanly.
        self._room_canvas = QPixmap(
            str(self.base_dir / "assets" / "house" / "room_base_canvas_paint_v1.png")
        )
        # Shelf browsing needs the sofa to occlude the character correctly,
        # so it is likewise kept as a complete, depth-consistent room plate.
        self._room_bookshelf = QPixmap(
            str(self.base_dir / "assets" / "house" / "room_base_bookshelf_pick_v1.png")
        )
        # Only the two remaining foreground poses are separate RGBA cutouts.
        # Chair, sofa, canvas and bookshelf now use their complete room plates.
        pet_dir = self.base_dir / "assets" / "house" / "pet_positions"
        self._pet_positions = {
            "rug": QPixmap(str(pet_dir / "pet_rug.png")),
            "chest": QPixmap(str(pet_dir / "pet_chest_v2.png")),
        }
        # The sofa plate is generated as a complete foreground illustration.
        # Give it the room's slightly darker sepia paper tone without tinting
        # any transparent pixels or the surrounding furniture.
        self._pet_tone_overlays = {}
        # Keep the old asset as a safe fallback if a pose file is missing.
        self._pet = self._pet_positions["rug"]
        self._pet_location = "rug"
        tea_dir = self.base_dir / "assets" / "house" / "objects" / "tea_v2"
        self._tea_frames = [
            QPixmap(str(tea_dir / f"tea_pour_{index:02d}.png"))
            for index in range(1, 7)
        ]
        self._pixmaps = {}
        self._images = {}
        self._items = self._build_items()
        for spec in self._items.values():
            if spec.asset and spec.asset not in self._pixmaps:
                pixmap = QPixmap(str(self.asset_dir / spec.asset))
                self._pixmaps[spec.asset] = pixmap
                self._images[spec.asset] = pixmap.toImage() if not pixmap.isNull() else None
        self._state = {
            name: {"value": 0.0, "target": 0.0, "elapsed": 0.0, "active": False}
            for name in self._items
        }
        self._phase = 0.0
        self._pressed = ""
        self._scale = 1.0
        self._origin = QPointF()
        self._return_emitted = False
        self._puzzle_dialog = None
        self._drawing_dialog = None
        self._reader_dialog = None
        self._bookshelf_dialog = None

        self.setWindowTitle("桌宠的小屋")
        self.setMinimumSize(930, 590)
        self.resize(1120, 700)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#faf5e9;")

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _build_items(self):
        manifest = json.loads((self.asset_dir / "manifest.json").read_text(encoding="utf-8"))
        modes = {
            "hanging_plant": ("oneshot", 1.35),
            "picture_rose": ("oneshot", 0.90),
            "picture_lavender": ("oneshot", 0.90),
            "wall_clock": ("toggle", 0.35),
            "lamp": ("toggle", 0.40),
            "cushion_left": ("oneshot", 0.68),
            "cushion_right": ("oneshot", 0.68),
            "radio": ("toggle", 0.30),
            "toy_car": ("toggle", 0.90),
            "tea_set": ("oneshot", 1.00),
            "open_book": ("oneshot", 1.00),
            "number_puzzle": ("oneshot", 0.45),
        }
        result = {}
        for item in manifest["objects"]:
            x, y, width, height = item["rect"]
            mode, duration = modes[item["id"]]
            result[item["id"]] = ItemSpec(
                QRectF(x, y, width, height), item["asset"], mode, duration, int(item["z"]), True
            )

        # Temporary extracted sprites remain until their refined versions are ready.
        result.update({
            "notes": ItemSpec(QRectF(172, 337, 202, 74), "notes.png", "oneshot", 0.72, 12),
            "window_left": ItemSpec(QRectF(186, 18, 90, 329), "window_sashes_clean_v2.png", "toggle", 0.55, 5, False),
            "window_right": ItemSpec(QRectF(276, 18, 89, 329), "window_sashes_clean_v2.png", "toggle", 0.55, 5, False),
            "curtain_left": ItemSpec(QRectF(104, 0, 114, 432), "curtain_left_final_v1.png", "toggle", 0.72, 8),
            "curtain_right": ItemSpec(QRectF(345, 0, 100, 432), "curtain_right_final_v1.png", "toggle", 0.72, 8),
            "window_plant": ItemSpec(QRectF(199, 283, 70, 88), "window_plant_final_v1.png", "oneshot", 1.0, 15, False),
            "cabinet_books": ItemSpec(QRectF(489, 273, 129, 103), "cabinet_books.png", "oneshot", 0.9, 28),
            "canvas": ItemSpec(QRectF(1040, 132, 208, 284), "canvas.png", "oneshot", 0.45, 20),
            # Brushes beside the canvas are static room decoration; they are
            # not an interactive object.
            "brush_jar": ItemSpec(QRectF(1136, 269, 89, 130), "brush_jar.png", "static", 0.0, 42),
            "door_panel": ItemSpec(QRectF(1296, 17, 183, 587), "door_panel.png", "toggle", 0.65, 18),
            "chest_lid": ItemSpec(QRectF(1270, 576, 316, 130), "chest_lid_final_v1.png", "toggle", 0.72, 35),
            # The bedside drawer is intentionally part of the room plate only.
            # Its previous extracted face produced visible seams when pulled,
            # so it is now a static, non-interactive detail.
            "side_drawer": ItemSpec(QRectF(122, 665, 114, 96), None, "static", 0.0, 46, False),
            "sofa": ItemSpec(QRectF(175, 410, 405, 285), None, "oneshot", 0.55, 0, False),
        })
        return result

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
        return QPointF(
            (point.x() - self._origin.x()) / self._scale,
            (point.y() - self._origin.y()) / self._scale,
        )

    def _alpha_contains(self, spec, point):
        if not spec.rect.contains(point):
            return False
        if not spec.alpha_hit or not spec.asset:
            return True
        image = self._images.get(spec.asset)
        if image is None or image.isNull():
            return True
        u = (point.x() - spec.rect.x()) / max(1.0, spec.rect.width())
        v = (point.y() - spec.rect.y()) / max(1.0, spec.rect.height())
        px = min(image.width() - 1, max(0, int(u * image.width())))
        py = min(image.height() - 1, max(0, int(v * image.height())))
        return image.pixelColor(px, py).alpha() >= 24

    def _item_at(self, point):
        # Top-most and smallest items win. Sofa is deliberately last.
        ordered = sorted(self._items.items(), key=lambda pair: (pair[1].z, -pair[1].rect.width() * pair[1].rect.height()), reverse=True)
        for name, spec in ordered:
            if name in {"window_plant", "window_right", "side_drawer", "brush_jar"}:
                continue
            # The drawer overlaps the lower edge of the sofa hit rectangle;
            # keep clicks there inert instead of accidentally leaving the
            # house through the sofa action.
            if name == "sofa" and self._items["side_drawer"].rect.contains(point):
                continue
            if self._alpha_contains(spec, point):
                return name
        # Empty furniture/room areas are navigation hotspots for the static
        # character poses.  They are checked only after real object hitboxes,
        # so clicking a book, canvas, or chest still keeps its normal action.
        pet_spots = {
            "chair": QRectF(790, 285, 190, 175),
            "rug": QRectF(430, 560, 690, 390),
        }
        for location, rect in pet_spots.items():
            if rect.contains(point):
                return f"pet_spot:{location}"
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
        if name.startswith("pet_spot:"):
            self._pet_location = name.split(":", 1)[1]
            self.update()
            return

        # Object clicks also move the character to the most natural nearby
        # pose, then continue with the object's established interaction.
        location_for_item = {
            "open_book": "chair",
            "canvas": "canvas",
            "cabinet_books": "bookshelf",
            "chest_lid": "chest",
            "sofa": "sofa",
        }
        if name in location_for_item:
            self._pet_location = location_for_item[name]
            self.update()

        # Opening the note is navigation, not a physical animation.  Handle it
        # before triggering object state so the wall notes remain perfectly still.
        if name == "notes":
            self.inbox_path.mkdir(parents=True, exist_ok=True)
            if not self.notes_path.exists():
                self.notes_path.write_text("把文字拖给桌宠后，便签会出现在这里。\n", encoding="utf-8")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.notes_path)))
            return
        if name == "cabinet_books":
            # 书架只负责收藏、选择和删除，不再与阅读界面混在一起。
            self._open_bookshelf()
            return

        opened = self._trigger(name)
        if name == "number_puzzle":
            if self._puzzle_dialog is None:
                save_path = self.inbox_path / "小游戏存档" / "数字华容道.json"
                self._puzzle_dialog = NumberPuzzleDialog(self, save_path=save_path)
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
        elif name == "open_book":
            QTimer.singleShot(100, self._open_reader)
        elif name == "chest_lid" and opened:
            self.inbox_path.mkdir(parents=True, exist_ok=True)
            QTimer.singleShot(620, lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.inbox_path))))
        elif name == "sofa":
            # The sofa is now a stay-in-room character pose.  Sleep/leave is
            # intentionally not triggered by a single sofa click.
            return
        elif name == "door_panel" and opened:
            QTimer.singleShot(680, self._leave_house)

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
        if not self._return_emitted:
            self._return_emitted = True
            self.returned_to_desktop.emit()
        self.hide()

    def showEvent(self, event):
        self._return_emitted = False
        for name in ("door_panel", "chest_lid"):
            self._state[name].update(value=0.0, target=0.0, elapsed=0.0, active=False)
        super().showEvent(event)

    def closeEvent(self, event):
        if not self._return_emitted:
            self._return_emitted = True
            self.returned_to_desktop.emit()
        super().closeEvent(event)

    def _draw_sprite(self, painter, name, target=None, angle=0.0, opacity=1.0):
        spec = self._items[name]
        pixmap = self._pixmaps.get(spec.asset)
        if pixmap is None or pixmap.isNull():
            return
        target = QRectF(target or spec.rect)
        painter.save()
        painter.setOpacity(opacity)
        if abs(angle) > 0.001:
            centre = target.center()
            painter.translate(centre)
            painter.rotate(angle)
            target.moveCenter(QPointF(0, 0))
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.restore()

    def _draw_canvas_sprite(self, painter):
        """Draw only the physical canvas/brush silhouettes.

        ``canvas.png`` was extracted from the room with a low non-zero alpha
        wall baked into every pixel.  Drawing its full rectangle therefore
        repaints a patch of wall and makes the lower easel rail look broken.
        A geometry clip keeps only the canvas board and lower rail while
        letting the clean room plate supply the wall/easel legs and the
        dedicated brush-jar sprite supply the brushes.
        """
        spec = self._items["canvas"]
        pixmap = self._pixmaps.get(spec.asset)
        if pixmap is None or pixmap.isNull():
            return
        target = QRectF(spec.rect)
        sx = target.width() / max(1.0, float(pixmap.width()))
        sy = target.height() / max(1.0, float(pixmap.height()))

        def pt(x, y):
            return QPointF(target.left() + x * sx, target.top() + y * sy)

        clip = QPainterPath()
        # Main canvas board (slightly skewed in the room perspective).
        board = QPolygonF([pt(47, 56), pt(194, 45), pt(207, 217), pt(18, 231)])
        clip.addPolygon(board)
        # The wooden ledge and easel frame already exist cleanly in the room
        # plate.  Repainting the extracted ledge produced a doubled/cut rail,
        # so only the paper/canvas board is overlaid here.
        painter.save()
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
        painter.restore()

    def _draw_pixmap_around_pivot(self, painter, asset, target, pivot, angle=0.0):
        """Rotate one transparent part around a physical attachment point."""

        pixmap = self._pixmaps.get(asset)
        if pixmap is None or pixmap.isNull():
            return
        painter.save()
        painter.translate(pivot)
        painter.rotate(angle)
        painter.translate(-pivot)
        painter.drawPixmap(QRectF(target), pixmap, QRectF(pixmap.rect()))
        painter.restore()

    def _draw_curtain_deformed(self, painter, name, direction):
        """Gather fabric progressively instead of translating one flat rectangle."""

        spec = self._items[name]
        pixmap = self._pixmaps.get(spec.asset)
        if pixmap is None or pixmap.isNull():
            return
        amount = self._smooth(self._value(name))
        moving = 1.0 if self._state[name]["active"] else 0.0
        strips = 72
        source_h = pixmap.height() / strips
        target_h = spec.rect.height() / strips
        for index in range(strips):
            t = (index + 0.5) / strips
            # The rod line barely moves; the tie and lower folds gather more.
            tie_pull = math.exp(-((t - 0.57) / 0.30) ** 2)
            anchor_blend = self._smooth((t - 0.055) / 0.22)
            influence = anchor_blend * (0.72 * tie_pull + 0.22 * t)
            width_factor = 1.0 - amount * 0.28 * influence
            width = spec.rect.width() * width_factor
            pull = direction * amount * 31.0 * influence
            settle = direction * math.sin(self._phase * 1.7 + t * math.pi * 2.2) * moving * 1.4 * t
            if direction < 0:
                x = spec.rect.x() + pull + settle
            else:
                x = spec.rect.right() - width + pull + settle
            y = spec.rect.y() + index * target_h
            source = QRectF(0, index * source_h, pixmap.width(), source_h + 1.0)
            target = QRectF(x, y, width, target_h + 1.1)
            painter.drawPixmap(target, pixmap, source)

    def _draw_chest_lid(self, painter):
        """Project the lid through a real hinge arc instead of sliding it upward."""

        spec = self._items["chest_lid"]
        pixmap = self._pixmaps.get(spec.asset)
        if pixmap is None or pixmap.isNull():
            return
        amount = self._smooth(self._value("chest_lid"))
        angle = math.radians(132.0 * amount)
        rect = spec.rect
        hinge_y = rect.top()
        front_y = hinge_y + rect.height() * math.cos(angle)
        inset = 34.0 * math.sin(angle)
        source = QPolygonF([
            QPointF(0.0, 0.0),
            QPointF(float(pixmap.width()), 0.0),
            QPointF(float(pixmap.width()), float(pixmap.height())),
            QPointF(0.0, float(pixmap.height())),
        ])
        target = QPolygonF([
            QPointF(rect.left(), hinge_y),
            QPointF(rect.right(), hinge_y),
            QPointF(rect.right() - inset, front_y),
            QPointF(rect.left() + inset, front_y),
        ])
        painter.save()
        painter.setOpacity(max(0.25, min(1.0, abs(front_y - hinge_y) / 7.0)))
        transform = QTransform.quadToQuad(source, target)
        painter.setTransform(transform, True)
        painter.drawPixmap(0, 0, pixmap)
        painter.restore()

    def _draw_side_drawer(self, painter):
        """The drawer is baked into the clean room plate and never moves."""
        return

    def _draw_window_half(self, painter, name, left_half):
        spec = self._items[name]
        pixmap = self._pixmaps.get(spec.asset)
        if pixmap is None or pixmap.isNull():
            return
        # The right sash is intentionally locked closed.  Its perspective was
        # ambiguous in this flat source painting, so keeping it static is more
        # convincing than a panel that reads as opening inward.
        value = 0.0 if name == "window_right" else self._smooth(self._value(name))
        half_width = pixmap.width() // 2
        source_x = 0 if left_half else half_width
        part = pixmap.copy(source_x, 0, half_width, pixmap.height())
        visible_width = spec.rect.width() * (1.0 - value * 0.80)
        vertical_inset = 8.0 * value

        source_quad = QPolygonF([
            QPointF(0, 0),
            QPointF(part.width(), 0),
            QPointF(part.width(), part.height()),
            QPointF(0, part.height()),
        ])
        if left_half:
            # Left sash is hinged on the outside-left edge; its free edge folds
            # away toward that hinge.
            target_quad = QPolygonF([
                QPointF(spec.rect.left(), spec.rect.top()),
                QPointF(spec.rect.left() + visible_width, spec.rect.top() + vertical_inset),
                QPointF(spec.rect.left() + visible_width, spec.rect.bottom() - vertical_inset),
                QPointF(spec.rect.left(), spec.rect.bottom()),
            ])
        else:
            target_quad = QPolygonF([
                QPointF(spec.rect.right() - visible_width, spec.rect.top() + vertical_inset),
                QPointF(spec.rect.right(), spec.rect.top()),
                QPointF(spec.rect.right(), spec.rect.bottom()),
                QPointF(spec.rect.right() - visible_width, spec.rect.bottom() - vertical_inset),
            ])
        painter.save()
        painter.setTransform(QTransform.quadToQuad(source_quad, target_quad), True)
        painter.drawPixmap(0, 0, part)
        painter.restore()

    def _draw_independent_items(self, painter, sofa_mode=False):
        # The seated-sofa illustration already contains its own window and
        # The complete sofa-state plate already contains the curtains,
        # window, plant, and all furniture.  Drawing those independent pieces
        # over it would reintroduce seams around the character.
        if not sofa_mode:
            self._draw_window_half(painter, "window_left", True)
            self._draw_window_half(painter, "window_right", False)

        plant = self._value("hanging_plant")
        plant_angle = math.sin(plant * math.pi * 4.0) * (1.0 - plant) * 5.5 if plant else 0.0
        self._draw_sprite(painter, "hanging_plant", angle=plant_angle)

        if not sofa_mode:
            self._draw_sprite(painter, "notes")

        # Curtains are foreground fabric: they must stay above the sill, notes,
        # and windowsill plant while gathering.
        for name, direction in (("curtain_left", -1), ("curtain_right", 1)):
            self._draw_curtain_deformed(painter, name, direction)

        # One indivisible, non-interactive plant is drawn above the curtain.
        # Previously the curtain hid the stems while leaving the leaves and pot
        # visible, which made those two parts appear detached.
        if not sofa_mode:
            self._draw_sprite(painter, "window_plant")

        for name in ("picture_rose", "picture_lavender"):
            value = self._value(name)
            angle = math.sin(value * math.pi * 5.0) * (1.0 - value) * 5.0 if value else 0.0
            self._draw_sprite(painter, name, angle=angle)
        self._draw_sprite(painter, "wall_clock")

        self._draw_sprite(painter, "cabinet_books")
        self._draw_sprite(painter, "radio")
        car_spec = self._items["toy_car"]
        car_shift = self._smooth(self._value("toy_car")) * 19.0
        self._draw_sprite(painter, "toy_car", QRectF(car_spec.rect).translated(car_shift, 0))

        self._draw_sprite(painter, "lamp")

        # The sofa-resting pose includes its own two cushions.  Suppress the
        # independent cushions so no duplicate edges or drifting upholstery
        # appear beneath the complete sofa foreground plate.
        cushion_names = () if self._pet_location == "sofa" else ("cushion_left", "cushion_right")
        for name in cushion_names:
            spec = self._items[name]
            squash = math.sin(math.pi * self._value(name))
            width = spec.rect.width() * (1.0 + squash * 0.05)
            height = spec.rect.height() * (1.0 - squash * 0.10)
            target = QRectF(spec.rect.center().x() - width / 2, spec.rect.bottom() - height, width, height)
            self._draw_sprite(painter, name, target)

        tea_value = self._value("tea_set")
        tea_active = self._state["tea_set"]["active"] or tea_value > 0.001
        if tea_active and self._tea_frames and all(not frame.isNull() for frame in self._tea_frames):
            frame_index = min(len(self._tea_frames) - 1, int(tea_value * len(self._tea_frames)))
            # tea_v2 embeds the exact 1377x798 static tea set at (120, 180)
            # inside a 1600x1100 motion canvas.  This target maps the embedded
            # pixels back to the original [690, 376, 108, 62] scene rectangle.
            tea_target = QRectF(680.59, 362.02, 125.49, 85.46)
            painter.drawPixmap(tea_target, self._tea_frames[frame_index], QRectF(self._tea_frames[frame_index].rect()))
        else:
            self._draw_sprite(painter, "tea_set")
        self._draw_sprite(painter, "open_book")
        puzzle_spec = self._items["number_puzzle"]
        puzzle_lift = math.sin(math.pi * self._value("number_puzzle")) * 6
        self._draw_sprite(painter, "number_puzzle", QRectF(puzzle_spec.rect).translated(0, -puzzle_lift))

        self._draw_canvas_sprite(painter)
        self._draw_sprite(painter, "brush_jar")

        door_spec = self._items["door_panel"]
        door = self._smooth(self._value("door_panel"))
        door_width = max(24.0, door_spec.rect.width() * (1.0 - door * 0.82))
        self._draw_sprite(
            painter,
            "door_panel",
            QRectF(door_spec.rect.right() - door_width, door_spec.rect.y(), door_width, door_spec.rect.height()),
        )

        self._draw_chest_lid(painter)

    def _draw_effects(self, painter):
        radio = self._smooth(self._value("radio"))
        if radio > 0.01:
            painter.setFont(QFont("Segoe UI Symbol", 25))
            painter.setPen(QColor(91, 119, 111, int(205 * radio)))
            for index, symbol in enumerate(("♪", "♫", "♪")):
                x = 624 + index * 35
                y = 280 - index * 12 + math.sin(self._phase * 2.1 + index) * 9
                painter.drawText(QPointF(x, y), symbol)

        clock = self._smooth(self._value("wall_clock"))
        if clock > 0.01:
            painter.setPen(QPen(QColor(96, 84, 75, int(170 * clock)), 2.0))
            x = 911 + math.sin(self._phase * 2.5) * 13
            painter.drawLine(QPointF(911, 196), QPointF(x, 230))
            painter.setBrush(QColor(183, 148, 93, int(205 * clock)))
            painter.drawEllipse(QRectF(x - 7, 224, 14, 14))

    def _draw_lamp_atmosphere(self, painter):
        """Apply the warm, low-contrast paper mood while the lamp is on."""
        lamp = self._smooth(self._value("lamp"))
        if lamp <= 0.001:
            return

        painter.save()
        # A warm multiply grade creates the richer honey paper and brown
        # outlines of the lit mood without changing any scene geometry.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        painter.fillRect(
            QRectF(0, 0, self.SCENE_W, self.SCENE_H),
            QColor(198, 154, 98, int(115 * lamp)),
        )
        # A restrained paper tint adds the cream note seen in the reference
        # mood without flattening the original room's contrast.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.fillRect(
            QRectF(0, 0, self.SCENE_W, self.SCENE_H),
            QColor(250, 226, 181, int(16 * lamp)),
        )
        # Then add the localized falloff that makes the lamp feel like the
        # source of the room's warm cream-paper mood rather than a flat filter.
        glow = QRadialGradient(QPointF(105, 500), 930)
        glow.setColorAt(0.0, QColor(255, 224, 164, int(40 * lamp)))
        glow.setColorAt(0.42, QColor(251, 230, 185, int(18 * lamp)))
        glow.setColorAt(1.0, QColor(243, 219, 170, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(-800, -430, 1770, 1770))
        # A small core glow also makes the physical lamp read as switched on.
        core = QRadialGradient(QPointF(110, 500), 175)
        core.setColorAt(0.0, QColor(255, 226, 145, int(100 * lamp)))
        core.setColorAt(0.65, QColor(255, 237, 195, int(28 * lamp)))
        core.setColorAt(1.0, QColor(255, 239, 205, 0))
        painter.setBrush(core)
        painter.drawEllipse(QRectF(-65, 325, 350, 350))
        painter.restore()

    def _draw_pet(self, painter):
        pet = self._pet_positions.get(self._pet_location, self._pet)
        if pet.isNull():
            return
        targets = {
            # Character sizes are derived from the 587 px room door and the
            # local floor perspective.  Foreground poses are intentionally
            # larger than the old miniature sprites.
            "rug": QRectF(610, 330, 373, 560),
            # Full seated body: book aligns with the tabletop, feet continue
            # naturally below it, and the head overlaps the lower clock area.
            "chair": QRectF(720, 185, 360, 540),
            # Complete foreground sofa plate.  Its scale matches the original
            # left sofa while its top-most draw order keeps notes and curtains
            # from covering the character's head.
            "sofa": QRectF(38, 362, 640, 480),
            # The painting pose sits immediately to the left of the easel.
            # Its brush meets the lower half of the board while both feet stay
            # on the same floor plane as the easel.
            # Put both feet in the easel's foreground footprint, rather than
            # leaving the painter beside it.  Her raised hand then reaches the
            # board from directly in front of the canvas.
            "canvas": QRectF(925, 198, 347, 520),
            # Bent reaching pose stands on the floor in front of the cabinet.
            "bookshelf": QRectF(455, 190, 428, 500),
            # Crouching pose remains outside the lid arc; the extended hand
            # reaches toward, rather than through, the chest opening.
            "chest": QRectF(1015, 470, 302, 360),
        }
        target = QRectF(targets.get(self._pet_location, targets["rug"]))
        if self._pet_location == "rug":
            target.translate(0, math.sin(self._phase * 0.72) * 2.0)
        painter.save()
        painter.setOpacity(0.98)
        if self._pet_location == "canvas":
            # The generated sprite points left.  Mirroring it keeps this
            # independent asset facing the room's right-hand canvas without
            # altering the room plate or its interactive canvas layer.
            painter.translate(target.x() + target.width(), target.y())
            painter.scale(-1.0, 1.0)
            sprite_target = QRectF(0, 0, target.width(), target.height())
        else:
            sprite_target = target
        painter.drawPixmap(sprite_target, pet, QRectF(pet.rect()))
        tone_overlay = self._pet_tone_overlays.get(self._pet_location)
        if tone_overlay and not tone_overlay.isNull():
            painter.drawPixmap(sprite_target, tone_overlay, QRectF(tone_overlay.rect()))
        painter.restore()

    @staticmethod
    def _build_tone_overlay(pixmap, color):
        """Return an alpha-clipped paper-tone overlay for one RGBA sprite."""
        if pixmap.isNull():
            return QPixmap()
        overlay = QPixmap(pixmap.size())
        overlay.fill(Qt.GlobalColor.transparent)
        overlay_painter = QPainter(overlay)
        overlay_painter.drawPixmap(0, 0, pixmap)
        overlay_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        overlay_painter.fillRect(overlay.rect(), color)
        overlay_painter.end()
        return overlay

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), PAPER)
        self._scale = min(self.width() / self.SCENE_W, self.height() / self.SCENE_H)
        self._origin = QPointF(
            (self.width() - self.SCENE_W * self._scale) / 2,
            (self.height() - self.SCENE_H * self._scale) / 2,
        )
        painter.translate(self._origin)
        painter.scale(self._scale, self._scale)
        baked_rooms = {
            "sofa": self._room_sofa,
            "chair": self._room_chair,
            "canvas": self._room_canvas,
            "bookshelf": self._room_bookshelf,
        }
        baked_room = baked_rooms.get(self._pet_location)
        room = baked_room if baked_room and not baked_room.isNull() else self._room
        if not room.isNull():
            painter.drawPixmap(QRectF(0, 0, self.SCENE_W, self.SCENE_H), room, QRectF(room.rect()))
        # Sofa, chair, canvas and bookshelf use complete baked room plates. The
        # remaining positions are independent foreground character sprites.
        if self._pet_location not in {"sofa", "chair", "canvas", "bookshelf"}:
            self._draw_independent_items(painter)
        if self._pet_location in {"rug", "chest"}:
            self._draw_pet(painter)
        self._draw_lamp_atmosphere(painter)
        self._draw_effects(painter)
