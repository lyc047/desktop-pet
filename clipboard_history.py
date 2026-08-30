"""桌宠剪贴板历史：持久保存最近 5 条文字、链接、图片或文件。"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QBuffer,
    QIODevice,
    QMimeData,
    QObject,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


MAX_HISTORY_ITEMS = 5


def _font_family():
    for font_path in (
        Path("C:/Windows/Fonts/SIMYOU.TTF"),
        Path("C:/Windows/Fonts/msyh.ttc"),
    ):
        if not font_path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            return families[0]
    return "Microsoft YaHei UI"


class ClipboardHistoryManager(QObject):
    history_changed = Signal()
    item_copied = Signal(str)

    def __init__(self, clipboard, parent=None, data_dir=None):
        super().__init__(parent)
        app_data = Path(data_dir) if data_dir else (
            Path(os.environ.get("APPDATA", Path.home())) / "DesktopPet"
        )
        self.data_path = app_data / "clipboard_history.json"
        self.image_dir = app_data / "clipboard_images"
        self.clipboard = clipboard
        self.entries = []
        self._suppress_until = 0.0
        self._capture_timer = QTimer(self)
        self._capture_timer.setSingleShot(True)
        self._capture_timer.timeout.connect(self._capture_current)
        self._load()
        self.clipboard.dataChanged.connect(self._schedule_capture)
        # 把启动时剪贴板里已有的内容也纳入历史。
        QTimer.singleShot(300, self._capture_current)

    def _load(self):
        try:
            loaded = json.loads(self.data_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                self.entries = [entry for entry in loaded if self._valid_entry(entry)][
                    :MAX_HISTORY_ITEMS
                ]
        except (OSError, ValueError, TypeError):
            self.entries = []

    @staticmethod
    def _valid_entry(entry):
        return (
            isinstance(entry, dict)
            and entry.get("kind") in {"text", "link", "image", "files"}
            and isinstance(entry.get("id"), str)
            and isinstance(entry.get("signature"), str)
        )

    def _save(self):
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.data_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self.entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self.data_path)
        except OSError:
            pass

    def _schedule_capture(self):
        if time.perf_counter() < self._suppress_until:
            return
        self._capture_timer.start(120)

    @staticmethod
    def _image_bytes(image):
        array = QByteArray()
        buffer = QBuffer(array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        buffer.close()
        return bytes(array)

    def _capture_current(self):
        if time.perf_counter() < self._suppress_until:
            return
        mime = self.clipboard.mimeData()
        if mime is None:
            return

        entry = None
        if mime.hasImage():
            image_data = mime.imageData()
            if isinstance(image_data, QPixmap):
                image = image_data.toImage()
            elif isinstance(image_data, QImage):
                image = image_data
            else:
                image = QImage()
            if not image.isNull():
                payload = self._image_bytes(image)
                signature = "image:" + hashlib.sha256(payload).hexdigest()
                self.image_dir.mkdir(parents=True, exist_ok=True)
                image_path = self.image_dir / f"{uuid.uuid4().hex}.png"
                if image.save(str(image_path), "PNG"):
                    entry = self._new_entry(
                        "image",
                        signature,
                        image_path=str(image_path),
                        width=image.width(),
                        height=image.height(),
                    )

        if entry is None and mime.hasUrls():
            local_files = [
                url.toLocalFile()
                for url in mime.urls()
                if url.isLocalFile() and url.toLocalFile()
            ]
            if local_files:
                normalized = [str(Path(path)) for path in local_files]
                signature = "files:" + hashlib.sha256(
                    "\0".join(normalized).encode("utf-8", errors="replace")
                ).hexdigest()
                entry = self._new_entry(
                    "files",
                    signature,
                    paths=normalized,
                )

        if entry is None and mime.hasText():
            text = mime.text()
            if text and text.strip():
                # 限制单条持久化体积，日常长文仍绰绰有余。
                text = text[:500_000]
                stripped = text.strip()
                parsed = QUrl(stripped)
                is_link = (
                    "\n" not in stripped
                    and parsed.isValid()
                    and parsed.scheme().lower() in ("http", "https")
                )
                kind = "link" if is_link else "text"
                signature = kind + ":" + hashlib.sha256(
                    text.encode("utf-8", errors="replace")
                ).hexdigest()
                entry = self._new_entry(kind, signature, text=text)

        if entry is not None:
            self._add_entry(entry)

    @staticmethod
    def _new_entry(kind, signature, **content):
        return {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "signature": signature,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            **content,
        }

    def _add_entry(self, entry):
        old_same = next(
            (item for item in self.entries if item["signature"] == entry["signature"]),
            None,
        )
        if old_same is not None:
            self._remove_image_file(old_same)
        retained = [
            item for item in self.entries if item["signature"] != entry["signature"]
        ]
        retained.insert(0, entry)
        removed = retained[MAX_HISTORY_ITEMS:]
        self.entries = retained[:MAX_HISTORY_ITEMS]
        for item in removed:
            self._remove_image_file(item)
        self._save()
        self.history_changed.emit()

    @staticmethod
    def _remove_image_file(entry):
        if entry.get("kind") != "image":
            return
        try:
            Path(entry.get("image_path", "")).unlink(missing_ok=True)
        except OSError:
            pass

    def copy_entry(self, entry_id):
        entry = next((item for item in self.entries if item["id"] == entry_id), None)
        if entry is None:
            return False
        self._suppress_until = time.perf_counter() + 0.8
        kind = entry["kind"]
        if kind in ("text", "link"):
            self.clipboard.setText(entry.get("text", ""))
        elif kind == "image":
            image = QImage(entry.get("image_path", ""))
            if image.isNull():
                return False
            self.clipboard.setImage(image)
        elif kind == "files":
            mime = QMimeData()
            mime.setUrls(
                [QUrl.fromLocalFile(path) for path in entry.get("paths", [])]
            )
            self.clipboard.setMimeData(mime)
        else:
            return False
        self.item_copied.emit(kind)
        return True

    def delete_entry(self, entry_id):
        entry = next((item for item in self.entries if item["id"] == entry_id), None)
        if entry is None:
            return
        self._remove_image_file(entry)
        self.entries = [item for item in self.entries if item["id"] != entry_id]
        self._save()
        self.history_changed.emit()

    def clear(self):
        for entry in self.entries:
            self._remove_image_file(entry)
        self.entries = []
        self._save()
        self.history_changed.emit()


class ClipboardHistoryDialog(QDialog):
    TYPE_NAMES = {
        "text": "文字",
        "link": "链接",
        "image": "图片",
        "files": "文件",
    }

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.setWindowTitle("剪贴板历史")
        self.setMinimumSize(500, 430)
        self.resize(540, 500)
        self.setFont(QFont(_font_family(), 10))

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)
        title = QLabel("最近 5 条剪贴板")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #5f4744;")
        subtitle = QLabel("文字、链接、图片和文件都可以一键复制回去")
        subtitle.setStyleSheet("color: #8b716d;")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self.scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.clear_button = QPushButton("清空历史")
        self.clear_button.clicked.connect(self._confirm_clear)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.accept)
        footer.addWidget(self.clear_button)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self.setStyleSheet(
            "QDialog { background: #fffaf7; }"
            "QPushButton { background: #fff; border: 1px solid #dfbbb4; "
            "border-radius: 9px; padding: 7px 13px; color: #6d4f4b; }"
            "QPushButton:hover { background: #fff0ec; border-color: #cd9188; }"
        )
        self.manager.history_changed.connect(self.refresh)
        self.refresh()

    @staticmethod
    def _time_label(value):
        try:
            stamp = datetime.fromisoformat(value)
            if stamp.date() == datetime.now().date():
                return stamp.strftime("今天 %H:%M")
            return stamp.strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _preview_text(entry):
        kind = entry["kind"]
        if kind in ("text", "link"):
            text = " ".join(entry.get("text", "").split())
            return text if len(text) <= 110 else text[:110] + "…"
        if kind == "files":
            names = [Path(path).name for path in entry.get("paths", [])]
            preview = "、".join(names[:3])
            if len(names) > 3:
                preview += f" 等 {len(names)} 个文件"
            return preview
        return f"{entry.get('width', '?')} × {entry.get('height', '?')} 像素"

    def refresh(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        if not self.manager.entries:
            empty = QLabel("还没有记录\n复制一段文字、一张图片或一个文件试试吧")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #a88e89; padding: 70px 20px;")
            layout.addWidget(empty)
        else:
            for entry in self.manager.entries:
                layout.addWidget(self._entry_card(entry))
        layout.addStretch(1)
        self.scroll.setWidget(container)
        self.clear_button.setEnabled(bool(self.manager.entries))

    def _entry_card(self, entry):
        card = QFrame()
        card.setStyleSheet(
            "QFrame#historyCard { background: white; border: 1px solid #ead6d1; "
            "border-radius: 13px; }"
        )
        card.setObjectName("historyCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(13, 11, 11, 11)
        row.setSpacing(12)

        if entry["kind"] == "image":
            preview = QLabel()
            pixmap = QPixmap(entry.get("image_path", ""))
            if not pixmap.isNull():
                preview.setPixmap(
                    pixmap.scaled(
                        74,
                        58,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            preview.setFixedSize(78, 62)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setStyleSheet("background: #fff5f1; border-radius: 8px;")
            row.addWidget(preview)

        information = QVBoxLayout()
        heading = QHBoxLayout()
        kind_label = QLabel(self.TYPE_NAMES[entry["kind"]])
        kind_label.setStyleSheet(
            "background: #f8ddd7; color: #8b5148; border-radius: 7px; "
            "font-weight: 700; padding: 3px 8px;"
        )
        time_label = QLabel(self._time_label(entry.get("created_at")))
        time_label.setStyleSheet("color: #ad9691;")
        heading.addWidget(kind_label, 0)
        heading.addWidget(time_label, 0)
        heading.addStretch(1)
        information.addLayout(heading)
        content = QLabel(self._preview_text(entry))
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setStyleSheet("color: #544440; padding-top: 3px;")
        information.addWidget(content)
        row.addLayout(information, 1)

        buttons = QVBoxLayout()
        copy_button = QPushButton("复制")
        copy_button.clicked.connect(
            lambda checked=False, item_id=entry["id"], button=copy_button:
            self._copy(item_id, button)
        )
        delete_button = QPushButton("删除")
        delete_button.setStyleSheet("color: #a78984;")
        delete_button.clicked.connect(
            lambda checked=False, item_id=entry["id"]:
            self.manager.delete_entry(item_id)
        )
        buttons.addWidget(copy_button)
        buttons.addWidget(delete_button)
        buttons.addStretch(1)
        row.addLayout(buttons)
        return card

    def _copy(self, entry_id, button):
        if not self.manager.copy_entry(entry_id):
            button.setText("失败")
            return
        button.setText("已复制 ✓")
        QTimer.singleShot(1200, lambda: button.setText("复制"))

    def _confirm_clear(self):
        if not self.manager.entries:
            return
        answer = QMessageBox.question(
            self,
            "清空剪贴板历史",
            "确定要删除这 5 条以内的历史记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.manager.clear()
