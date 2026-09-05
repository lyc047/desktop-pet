import json
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


INK = QColor("#514943")
INK_SOFT = QColor("#857972")
PAPER = QColor("#faf5e9")
PAPER_LIGHT = QColor("#fffaf1")
TEAL = QColor("#7faea3")
ROSE = QColor("#d8a2a4")
GOLD = QColor("#d5b36a")


@dataclass
class Ball:
    center: QPointF
    radius: float
    color: QColor


class AimField(QWidget):
    """Compact click-to-hit field that always keeps three targets alive."""

    hit = Signal(int)
    miss = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(610, 370)
        self.setMouseTracking(True)
        self._rng = random.Random()
        self._balls = []
        self._running = False
        self._hovered = -1
        self._hit_marks = []
        self._palette = [TEAL, ROSE, GOLD]

    def start(self):
        self._running = True
        self._hovered = -1
        self._hit_marks.clear()
        self._balls.clear()
        while len(self._balls) < 3:
            self._spawn_ball()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()

    def stop(self):
        self._running = False
        self._hovered = -1
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def _play_rect(self):
        return QRectF(18, 18, max(1, self.width() - 36), max(1, self.height() - 36))

    def _spawn_ball(self):
        area = self._play_rect()
        radius = self._rng.uniform(18.0, 24.0)
        for _ in range(160):
            center = QPointF(
                self._rng.uniform(area.left() + radius + 8, area.right() - radius - 8),
                self._rng.uniform(area.top() + radius + 8, area.bottom() - radius - 8),
            )
            if all(
                math.hypot(center.x() - ball.center.x(), center.y() - ball.center.y())
                >= radius + ball.radius + 20
                for ball in self._balls
            ):
                color = QColor(self._palette[len(self._balls) % len(self._palette)])
                self._rng.shuffle(self._palette)
                self._balls.append(Ball(center, radius, color))
                return

        # Very small resized windows can make the spacing rule impossible.
        center = QPointF(area.center())
        center += QPointF((len(self._balls) - 1) * 58, (len(self._balls) % 2) * 46)
        self._balls.append(Ball(center, radius, QColor(self._palette[len(self._balls) % 3])))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._running:
            area = self._play_rect()
            if any(not area.contains(ball.center) for ball in self._balls):
                self._balls.clear()
                while len(self._balls) < 3:
                    self._spawn_ball()

    def mouseMoveEvent(self, event):
        self._hovered = -1
        if self._running:
            point = event.position()
            for index, ball in enumerate(self._balls):
                if math.hypot(point.x() - ball.center.x(), point.y() - ball.center.y()) <= ball.radius:
                    self._hovered = index
                    break
        self.update()

    def leaveEvent(self, event):
        self._hovered = -1
        self.update()

    def mousePressEvent(self, event):
        if not self._running or event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        for index in range(len(self._balls) - 1, -1, -1):
            ball = self._balls[index]
            if math.hypot(point.x() - ball.center.x(), point.y() - ball.center.y()) <= ball.radius:
                self._hit_marks.append((QPointF(ball.center), time.monotonic()))
                self._balls.pop(index)
                self._spawn_ball()
                self._hovered = -1
                self.hit.emit(1)
                self.update()
                return
        self.miss.emit(1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), PAPER)

        field = self._play_rect()
        path = QPainterPath()
        path.addRoundedRect(field, 20, 20)
        painter.fillPath(path, PAPER_LIGHT)
        painter.setPen(QPen(QColor("#b5a79c"), 2.0, Qt.PenStyle.DashLine))
        painter.drawPath(path)

        now = time.monotonic()
        self._hit_marks = [mark for mark in self._hit_marks if now - mark[1] < 0.24]
        for center, created_at in self._hit_marks:
            progress = (now - created_at) / 0.24
            painter.setPen(QPen(QColor(216, 162, 164, int(210 * (1.0 - progress))), 3.0))
            radius = 16 + progress * 25
            painter.drawEllipse(center, radius, radius)

        for index, ball in enumerate(self._balls):
            radius = ball.radius + (2.5 if index == self._hovered else 0.0)
            glow = QRadialGradient(ball.center - QPointF(radius * 0.25, radius * 0.3), radius * 1.2)
            glow.setColorAt(0.0, ball.color.lighter(155))
            glow.setColorAt(0.72, ball.color)
            glow.setColorAt(1.0, ball.color.darker(112))
            painter.setBrush(glow)
            painter.setPen(QPen(INK_SOFT, 2.2))
            painter.drawEllipse(ball.center, radius, radius)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 251, 238, 185), 2.0))
            painter.drawEllipse(ball.center, radius * 0.56, radius * 0.56)
            painter.setBrush(QColor(255, 248, 230, 210))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(ball.center, radius * 0.17, radius * 0.17)

        if not self._running:
            painter.setPen(INK_SOFT)
            painter.setFont(QFont("KaiTi", 17, QFont.Weight.Bold))
            painter.drawText(field, Qt.AlignmentFlag.AlignCenter, "选好时间，开始练习吧")


class AimScoreStore:
    """Small JSON-backed top-ten table shared by the room and pet menu."""

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def _valid_record(record):
        required = {"recorded_at", "mode", "elapsed", "hits", "misses", "hpm", "accuracy"}
        return isinstance(record, dict) and required.issubset(record)

    def load(self):
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            records = payload.get("records", [])
        except (OSError, ValueError, AttributeError):
            return []
        if not isinstance(records, list):
            return []
        records = [record for record in records if self._valid_record(record)]
        return sorted(
            records,
            key=lambda item: (
                float(item.get("hpm", 0.0)),
                float(item.get("accuracy", 0.0)),
                int(item.get("hits", 0)),
            ),
            reverse=True,
        )[:10]

    def add(self, record):
        records = self.load()
        records.append(record)
        records = sorted(
            records,
            key=lambda item: (
                float(item.get("hpm", 0.0)),
                float(item.get("accuracy", 0.0)),
                int(item.get("hits", 0)),
            ),
            reverse=True,
        )[:10]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"version": 1, "records": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return records


class AimLeaderboardDialog(QDialog):
    def __init__(self, records_path, parent=None):
        super().__init__(parent)
        self.records_path = Path(records_path)
        self.store = AimScoreStore(self.records_path)
        self.setWindowTitle("打靶排行榜")
        self.setMinimumSize(780, 430)
        self.resize(860, 470)
        self.setStyleSheet(
            "QDialog{background:#faf5e9;color:#514943;}"
            "QTableWidget{background:#fffaf1;color:#514943;border:1px solid #cbbcaf;"
            "gridline-color:#ded2c7;selection-background-color:#dceae4;}"
            "QHeaderView::section{background:#eee3d2;color:#514943;border:0;"
            "border-right:1px solid #d4c5b8;padding:7px;font-weight:700;}"
            "QPushButton{background:#fffaf1;color:#514943;border:1.5px solid #857972;"
            "border-radius:10px;padding:7px 18px;font:15px 'Microsoft YaHei';}"
            "QPushButton:hover{background:#e9f2ed;border-color:#7faea3;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        title = QLabel("HPM 最高的十次记录")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("KaiTi", 20, QFont.Weight.Bold))
        root.addWidget(title)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["排名", "记录时间", "模式", "HPM", "命中率", "命中", "未命中"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in range(7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.empty_label = QLabel("还没有记录，去墙上的靶场试试吧。")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label)

        row = QHBoxLayout()
        row.addStretch()
        close_button = QPushButton("收起来")
        close_button.clicked.connect(self.close)
        row.addWidget(close_button)
        root.addLayout(row)
        self.refresh()

    def refresh(self):
        records = self.store.load()
        self.table.setRowCount(len(records))
        self.empty_label.setVisible(not records)
        self.table.setVisible(bool(records))
        for row, record in enumerate(records):
            values = [
                str(row + 1),
                str(record["recorded_at"]),
                str(record["mode"]),
                f"{float(record['hpm']):.1f}",
                f"{float(record['accuracy']):.1f}%",
                str(int(record["hits"])),
                str(int(record["misses"])),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)


class AimTrainerDialog(QDialog):
    DURATION_OPTIONS = {
        "30 秒": 30,
        "1 分钟": 60,
        "2 分钟": 120,
        "不限时": None,
    }

    def __init__(self, records_path, parent=None):
        super().__init__(parent)
        self.records_path = Path(records_path)
        self.score_store = AimScoreStore(self.records_path)
        self._leaderboard_dialog = None
        self.setWindowTitle("墙上的打靶练习")
        self.setMinimumSize(690, 555)
        self.resize(720, 585)
        self.setStyleSheet(
            "QDialog{background:#faf5e9;color:#514943;}"
            "QLabel{color:#514943;}"
            "QComboBox,QPushButton{background:#fffaf1;color:#514943;border:1.5px solid #857972;"
            "border-radius:10px;padding:7px 13px;font:15px 'Microsoft YaHei';}"
            "QPushButton:hover{background:#e9f2ed;border-color:#7faea3;}"
            "QPushButton:disabled{color:#aa9f98;background:#eee8dc;}"
        )

        self._hits = 0
        self._misses = 0
        self._started_at = None
        self._duration = 30
        self._running = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("小小打靶场")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("KaiTi", 21, QFont.Weight.Bold))
        root.addWidget(title)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.hit_label = QLabel("命中  0")
        self.accuracy_label = QLabel("命中率  0.0%")
        self.time_label = QLabel("剩余  30.0 秒")
        self.hpm_label = QLabel("HPM  0.0")
        for label in (self.hit_label, self.accuracy_label, self.time_label, self.hpm_label):
            label.setFont(QFont("Microsoft YaHei", 13, QFont.Weight.Bold))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "background:#fffaf1;border:1px solid #d3c4b8;border-radius:11px;padding:7px 12px;"
            )
            stats.addWidget(label)
        root.addLayout(stats)

        self.field = AimField(self)
        self.field.hit.connect(self._register_hit)
        self.field.miss.connect(self._register_miss)
        root.addWidget(self.field, 1)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("练习时间"))
        self.duration_box = QComboBox()
        self.duration_box.addItems(self.DURATION_OPTIONS)
        self.duration_box.currentTextChanged.connect(self._duration_changed)
        controls.addWidget(self.duration_box)
        self.start_button = QPushButton("开始")
        self.start_button.clicked.connect(self._start)
        controls.addWidget(self.start_button)
        self.finish_button = QPushButton("结束并结算")
        self.finish_button.setEnabled(False)
        self.finish_button.clicked.connect(self._finish)
        controls.addWidget(self.finish_button)
        leaderboard_button = QPushButton("排行榜")
        leaderboard_button.clicked.connect(self._open_leaderboard)
        controls.addWidget(leaderboard_button)
        controls.addStretch()
        close_button = QPushButton("收起来")
        close_button.clicked.connect(self.close)
        controls.addWidget(close_button)
        root.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._refresh_stats)
        self._duration_changed(self.duration_box.currentText())

    def _duration_changed(self, text):
        self._duration = self.DURATION_OPTIONS[text]
        if not self._running:
            self.time_label.setText(
                "时间  不限" if self._duration is None else f"剩余  {self._duration:.1f} 秒"
            )

    def _start(self):
        self._hits = 0
        self._misses = 0
        self._started_at = time.monotonic()
        self._duration = self.DURATION_OPTIONS[self.duration_box.currentText()]
        self._running = True
        self.duration_box.setEnabled(False)
        self.start_button.setEnabled(False)
        self.finish_button.setEnabled(True)
        self.field.start()
        self._timer.start()
        self._refresh_stats()

    def _register_hit(self, amount):
        if self._running:
            self._hits += amount
            self._refresh_stats()

    def _register_miss(self, amount):
        if self._running:
            self._misses += amount
            self._refresh_stats()

    def _elapsed(self):
        if self._started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    def _hpm(self, elapsed=None):
        elapsed = self._elapsed() if elapsed is None else elapsed
        return self._hits * 60.0 / max(0.001, elapsed)

    def _accuracy(self):
        attempts = self._hits + self._misses
        return self._hits * 100.0 / attempts if attempts else 0.0

    def _refresh_stats(self):
        if not self._running:
            return
        elapsed = self._elapsed()
        self.hit_label.setText(f"命中  {self._hits}")
        self.accuracy_label.setText(f"命中率  {self._accuracy():.1f}%")
        self.hpm_label.setText(f"HPM  {self._hpm(elapsed):.1f}")
        if self._duration is None:
            self.time_label.setText(f"用时  {elapsed:.1f} 秒")
        else:
            remaining = max(0.0, self._duration - elapsed)
            self.time_label.setText(f"剩余  {remaining:.1f} 秒")
            if remaining <= 0.0:
                self._finish()

    def _finish(self):
        if not self._running:
            return
        elapsed = self._elapsed()
        if self._duration is not None:
            elapsed = min(elapsed, float(self._duration))
        self._running = False
        self._timer.stop()
        self.field.stop()
        self.duration_box.setEnabled(True)
        self.start_button.setEnabled(True)
        self.finish_button.setEnabled(False)
        self.time_label.setText(f"用时  {elapsed:.1f} 秒")
        self.hit_label.setText(f"命中  {self._hits}")
        self.accuracy_label.setText(f"命中率  {self._accuracy():.1f}%")
        self.hpm_label.setText(f"HPM  {self._hpm(elapsed):.1f}")
        mode = self.duration_box.currentText()
        hpm = self._hpm(elapsed)
        accuracy = self._accuracy()
        record = {
            "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode,
            "elapsed": round(elapsed, 3),
            "hits": self._hits,
            "misses": self._misses,
            "hpm": round(hpm, 3),
            "accuracy": round(accuracy, 3),
        }
        try:
            self.score_store.add(record)
        except OSError as exc:
            QMessageBox.warning(self, "排行榜保存失败", str(exc))
        if self._leaderboard_dialog is not None:
            self._leaderboard_dialog.refresh()
        QMessageBox.information(
            self,
            "练习结果",
            f"命中：{self._hits} 次\n"
            f"未命中：{self._misses} 次\n"
            f"命中率：{accuracy:.1f}%\n"
            f"用时：{elapsed:.1f} 秒\n"
            f"Hit per minute：{hpm:.1f}",
        )

    def _open_leaderboard(self):
        if self._leaderboard_dialog is None:
            self._leaderboard_dialog = AimLeaderboardDialog(self.records_path, self)
            self._leaderboard_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self._leaderboard_dialog.destroyed.connect(
                lambda: setattr(self, "_leaderboard_dialog", None)
            )
        self._leaderboard_dialog.refresh()
        self._leaderboard_dialog.show()
        self._leaderboard_dialog.raise_()
        self._leaderboard_dialog.activateWindow()

    def closeEvent(self, event):
        self._timer.stop()
        self._running = False
        self.field.stop()
        super().closeEvent(event)
