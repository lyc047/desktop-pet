"""Persistent user settings and a compact, layered settings dialog."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QStandardPaths
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def default_inbox_path():
    documents = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation
    )
    base = Path(documents) if documents else Path.home() / "Documents"
    return str(base / "桌宠收纳箱")


DEFAULT_SETTINGS = {
    "appearance": {
        "pet_height": 350,
        "bubble_duration_ms": 3000,
        "always_on_top": True,
    },
    "storage": {
        "inbox_path": "",
    },
    "dialogues": {
        "manual": [
            "你好呀，我是你的桌宠！",
            "摸摸头~ 今天也要加油哦！",
            "工作累了吧？休息一下~",
            "我来陪你写代码啦！",
            "记得喝水，注意休息！",
            "嘿嘿，猜猜我现在在想什么？",
        ],
        "click": [],
        "annoyed": [
            "别一直戳我啦……",
            "好啦好啦，我知道你在这里……",
            "再戳就要生气了哦。",
        ],
        "dizzy": [
            "呜……世界在转……",
            "慢、慢一点啦……",
            "眼前好多星星……",
            "我有点站不稳了……",
        ],
        "curious": [
            "咦？你在看什么呀？",
            "让我也看看嘛。",
        ],
        "petted": [
            "嘿嘿，好舒服呀～",
            "再摸一会儿嘛。",
            "最喜欢这样啦～",
        ],
        "surprised": [
            "诶？怎么啦？",
            "呀！吓我一小跳。",
            "突然找我有什么事吗？",
        ],
        "hurt": [
            "唔……干嘛一直戳我……",
            "我也会觉得委屈的嘛。",
            "轻一点好不好……",
        ],
        "bored": [
            "好像有一点无聊……",
            "你还在忙吗？",
            "我再等你一会儿吧。",
        ],
        "sleepy": [
            "唔……有点困了……",
            "眼睛快睁不开啦……",
        ],
        "dream": [
            "唔……再睡一小会儿……",
            "这个云朵好软呀……",
            "梦里有好多小蛋糕……",
            "不要抢我的枕头嘛……",
        ],
        "wakeup": [
            "唔……醒啦……",
            "刚才睡得好舒服呀。",
        ],
        "edge": [
            "我躲在这里看看你～",
            "嘿，我在屏幕边上！",
        ],
        "inbox_success": [
            "收到啦，帮你收好啦！",
            "文件已经安全放进收纳箱啦。",
            "交给我吧，我替你保管好～",
        ],
        "note_success": [
            "记下来啦，不会忘记的！",
            "这段话已经放进便签本啦。",
        ],
        "link_success": [
            "这个链接我先替你收藏好啦。",
            "网页地址已经记住啦！",
        ],
        "image_success": [
            "图片已经放进收藏夹啦！",
            "这张图片我帮你收好啦。",
        ],
        "dream_receive": [
            "唄……梦里收到了{类型}……",
            "先把{类型}放进梦境口袋里……",
        ],
        "clipboard_copy": [
            "已经帮你复制回剪贴板啦！",
            "找回来了，这次别忘记粘贴哦～",
        ],
        "inbox_failure": [
            "这个文件没能收好，再试一次吧……",
            "收纳时遇到了一点问题。",
        ],
        "easter_ghost": [
            "再摸我就要吓哭你啦",
        ],
        "easter_dress": [
            "采臣，是你吗？",
        ],
    },
    "advanced": {
        "curious_enabled": True,
        "bored_enabled": True,
        "auto_sleep_enabled": True,
        "dizzy_enabled": True,
        "curious_hover_ms": 1800,
        "curious_exit_distance": 190,
        "long_press_ms": 800,
        "bored_idle_ms": 45000,
        "auto_sleep_idle_ms": 90000,
        "disturb_limit": 6,
        "shake_sensitivity": "normal",
        "speech_gap_ms": 600,
        "post_state_cooldown_ms": 3500,
    },
}


DIALOGUE_CATEGORIES = (
    ("manual", "手动“说句话”"),
    ("click", "普通轻触（默认不说话）"),
    ("annoyed", "连续点击后不耐烦"),
    ("dizzy", "摇晃后头晕"),
    ("curious", "触发好奇"),
    ("petted", "长按摸头开心"),
    ("surprised", "清醒时双击惊讶"),
    ("hurt", "连续打扰后的委屈"),
    ("bored", "长时间等待后无聊"),
    ("sleepy", "开始困倦"),
    ("dream", "睡觉时的梦话"),
    ("wakeup", "睡醒后"),
    ("edge", "屏幕边缘互动"),
    ("inbox_success", "文件收纳成功"),
    ("note_success", "文字记入便签"),
    ("link_success", "链接收藏成功"),
    ("image_success", "图片收藏成功"),
    ("dream_receive", "睡梦中接收（可用{类型}）"),
    ("clipboard_copy", "从剪贴板历史复制"),
    ("inbox_failure", "文件收纳失败"),
    ("easter_ghost", "连续点击彩蛋"),
    ("easter_dress", "持续摸头彩蛋"),
)


def _merge_defaults(defaults, loaded):
    """Deep merge while ignoring incompatible values from a damaged file."""
    if not isinstance(defaults, dict) or not isinstance(loaded, dict):
        return copy.deepcopy(defaults)
    result = copy.deepcopy(defaults)
    for key, value in loaded.items():
        if key not in defaults:
            continue
        if isinstance(defaults[key], dict):
            result[key] = _merge_defaults(defaults[key], value)
        elif isinstance(value, type(defaults[key])):
            result[key] = value
    return result


class SettingsStore:
    """JSON settings stored outside the installation directory."""

    def __init__(self, path: Path | None = None):
        if path is None:
            app_data = Path(os.environ.get("APPDATA", Path.home()))
            path = app_data / "DesktopPet" / "settings.json"
        self.path = Path(path)

    def load(self):
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return copy.deepcopy(DEFAULT_SETTINGS)
        merged = _merge_defaults(DEFAULT_SETTINGS, loaded)
        # 旧版本默认值是四次触发不满。升级后自动迁移到新的六次逻辑，
        # 避免已有 settings.json 继续覆盖新默认值。
        loaded_advanced = loaded.get("advanced", {})
        if loaded_advanced.get("disturb_limit") == 4:
            merged["advanced"]["disturb_limit"] = 6
        return merged

    def save(self, settings):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)


class SettingsDialog(QDialog):
    """Common options first; less visible behavior controls live in Advanced."""

    settings_applied = Signal(dict)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        family = "Microsoft YaHei UI"
        for font_path in (
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/SIMYOU.TTF"),
        ):
            if not font_path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                family = families[0]
                break
        self.setFont(QFont(family, 9))
        self.setWindowTitle("桌宠设置")
        self.setMinimumSize(500, 520)
        self.resize(540, 680)
        self._working = copy.deepcopy(settings)
        self._current_dialogue_key = None

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.addTab(self._build_common_tab(), "常用设置")
        self.tabs.addTab(self._build_dialogue_tab(), "自定义台词")
        self.tabs.addTab(self._build_advanced_tab(), "高级设置")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        self.buttons.accepted.connect(self._accept_settings)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._apply_settings
        )
        self.buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).clicked.connect(self._restore_defaults)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText("应用")
        self.buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        ).setText("恢复全部默认")
        root.addWidget(self.buttons)

        self.setStyleSheet(
            """
            QDialog { background: #fff9fb; color: #3d2e35; }
            QTabWidget::pane { border: 1px solid #e7ccd6; border-radius: 8px; }
            QTabBar::tab { padding: 9px 17px; margin-right: 2px; }
            QTabBar::tab:selected { background: #f6dce6; border-radius: 7px; }
            QGroupBox { font-weight: 600; margin-top: 12px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background: white; border: 1px solid #dcc4cd; border-radius: 6px;
                padding: 5px;
            }
            QPushButton { padding: 6px 12px; }
            """
        )

    def _build_common_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        appearance = QGroupBox("外观")
        form = QFormLayout(appearance)
        size_row = QHBoxLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(200, 600)
        self.size_slider.setSingleStep(10)
        self.size_slider.setPageStep(50)
        self.size_label = QLabel()
        self.size_label.setMinimumWidth(58)
        self.size_slider.valueChanged.connect(
            lambda value: self.size_label.setText(f"{value} px")
        )
        size_row.addWidget(self.size_slider, 1)
        size_row.addWidget(self.size_label)
        form.addRow("桌宠大小", size_row)

        self.bubble_seconds = QDoubleSpinBox()
        self.bubble_seconds.setRange(1.0, 12.0)
        self.bubble_seconds.setSingleStep(0.5)
        self.bubble_seconds.setSuffix(" 秒")
        form.addRow("气泡停留时间", self.bubble_seconds)

        self.always_on_top = QCheckBox("让桌宠保持在其他窗口上方")
        form.addRow("", self.always_on_top)
        layout.addWidget(appearance)

        storage = QGroupBox("文件收纳箱")
        storage_layout = QVBoxLayout(storage)
        path_row = QHBoxLayout()
        self.inbox_path = QLineEdit()
        self.inbox_path.setPlaceholderText(default_inbox_path())
        browse = QPushButton("选择文件夹…")
        browse.clicked.connect(self._choose_inbox_folder)
        path_row.addWidget(self.inbox_path, 1)
        path_row.addWidget(browse)
        storage_layout.addLayout(path_row)
        storage_hint = QLabel(
            "文件会安全复制；文字记入便签，链接和图片会自动分类收藏。"
        )
        storage_hint.setWordWrap(True)
        storage_hint.setStyleSheet("color: #806d75; padding: 2px;")
        storage_layout.addWidget(storage_hint)
        layout.addWidget(storage)

        hint = QLabel("这些设置会在点击“应用”或“确定”后立即生效。")
        hint.setStyleSheet("color: #806d75; padding: 6px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return page

    def _choose_inbox_folder(self):
        current = self.inbox_path.text().strip() or default_inbox_path()
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择桌宠收纳箱位置",
            current,
        )
        if selected:
            self.inbox_path.setText(selected)

    def _build_dialogue_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel("选择一个触发情境，每行填写一句话；触发时会随机选取。留空即可关闭该情境的台词。")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #6f5d65; padding: 4px;")
        layout.addWidget(intro)

        self.dialogue_combo = QComboBox()
        for key, label in DIALOGUE_CATEGORIES:
            self.dialogue_combo.addItem(label, key)
        layout.addWidget(self.dialogue_combo)

        self.dialogue_editor = QTextEdit()
        self.dialogue_editor.setPlaceholderText("每行一句，例如：\n今天也要加油呀！\n记得喝水哦。")
        layout.addWidget(self.dialogue_editor, 1)

        bottom = QHBoxLayout()
        self.dialogue_count = QLabel()
        restore_category = QPushButton("恢复当前分类默认台词")
        restore_category.clicked.connect(self._restore_current_dialogues)
        bottom.addWidget(self.dialogue_count)
        bottom.addStretch()
        bottom.addWidget(restore_category)
        layout.addLayout(bottom)

        self.dialogue_combo.currentIndexChanged.connect(self._change_dialogue_category)
        self.dialogue_editor.textChanged.connect(self._update_dialogue_count)
        self._change_dialogue_category(0)
        return page

    def _build_advanced_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        switches = QGroupBox("自动行为开关")
        switch_layout = QVBoxLayout(switches)
        self.curious_enabled = QCheckBox("启用鼠标靠近后的好奇状态")
        self.bored_enabled = QCheckBox("启用长时间等待后的无聊状态")
        self.auto_sleep_enabled = QCheckBox("启用长时间无操作后的自动睡眠")
        self.dizzy_enabled = QCheckBox("启用快速摇晃后的头晕状态")
        switch_layout.addWidget(self.curious_enabled)
        switch_layout.addWidget(self.bored_enabled)
        switch_layout.addWidget(self.auto_sleep_enabled)
        switch_layout.addWidget(self.dizzy_enabled)
        layout.addWidget(switches)

        timing = QGroupBox("触发参数")
        form = QFormLayout(timing)
        self.curious_hover_seconds = QDoubleSpinBox()
        self.curious_hover_seconds.setRange(0.5, 10.0)
        self.curious_hover_seconds.setSingleStep(0.1)
        self.curious_hover_seconds.setSuffix(" 秒")
        form.addRow("靠近多久后好奇", self.curious_hover_seconds)

        self.curious_exit_distance = QSpinBox()
        self.curious_exit_distance.setRange(80, 450)
        self.curious_exit_distance.setSuffix(" px")
        form.addRow("好奇保持范围", self.curious_exit_distance)

        self.long_press_seconds = QDoubleSpinBox()
        self.long_press_seconds.setRange(0.4, 3.0)
        self.long_press_seconds.setSingleStep(0.1)
        self.long_press_seconds.setSuffix(" 秒")
        form.addRow("长按多久后开心", self.long_press_seconds)

        self.bored_idle_minutes = QDoubleSpinBox()
        self.bored_idle_minutes.setRange(0.2, 120.0)
        self.bored_idle_minutes.setSingleStep(0.1)
        self.bored_idle_minutes.setSuffix(" 分钟")
        form.addRow("无操作多久后无聊", self.bored_idle_minutes)

        self.auto_sleep_minutes = QDoubleSpinBox()
        self.auto_sleep_minutes.setRange(0.5, 120.0)
        self.auto_sleep_minutes.setSingleStep(0.5)
        self.auto_sleep_minutes.setSuffix(" 分钟")
        form.addRow("无操作多久后困倦", self.auto_sleep_minutes)

        self.disturb_limit = QSpinBox()
        self.disturb_limit.setRange(2, 10)
        self.disturb_limit.setSuffix(" 次")
        form.addRow("连续点击后不耐烦", self.disturb_limit)

        self.shake_sensitivity = QComboBox()
        self.shake_sensitivity.addItem("容易触发", "easy")
        self.shake_sensitivity.addItem("标准", "normal")
        self.shake_sensitivity.addItem("不易触发", "hard")
        form.addRow("摇晃灵敏度", self.shake_sensitivity)

        self.speech_gap_seconds = QDoubleSpinBox()
        self.speech_gap_seconds.setRange(0.2, 5.0)
        self.speech_gap_seconds.setSingleStep(0.1)
        self.speech_gap_seconds.setSuffix(" 秒")
        form.addRow("两段台词之间间隔", self.speech_gap_seconds)

        self.post_state_seconds = QDoubleSpinBox()
        self.post_state_seconds.setRange(1.0, 10.0)
        self.post_state_seconds.setSingleStep(0.5)
        self.post_state_seconds.setSuffix(" 秒")
        form.addRow("动作结束后休息时间", self.post_state_seconds)
        layout.addWidget(timing)

        warning = QLabel("高级参数设置得过于灵敏时，普通操作也可能触发动作。")
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #8c6d78; padding: 6px;")
        layout.addWidget(warning)
        layout.addStretch()
        return page

    def _save_current_dialogues(self):
        if self._current_dialogue_key is None:
            return
        lines = [
            line.strip()
            for line in self.dialogue_editor.toPlainText().splitlines()
            if line.strip()
        ]
        self._working["dialogues"][self._current_dialogue_key] = lines

    def _change_dialogue_category(self, _index):
        self._save_current_dialogues()
        key = self.dialogue_combo.currentData()
        self._current_dialogue_key = key
        self.dialogue_editor.blockSignals(True)
        self.dialogue_editor.setPlainText("\n".join(self._working["dialogues"].get(key, [])))
        self.dialogue_editor.blockSignals(False)
        self._update_dialogue_count()

    def _update_dialogue_count(self):
        count = len([
            line for line in self.dialogue_editor.toPlainText().splitlines()
            if line.strip()
        ])
        self.dialogue_count.setText(f"当前 {count} 句")

    def _restore_current_dialogues(self):
        key = self.dialogue_combo.currentData()
        self.dialogue_editor.setPlainText("\n".join(DEFAULT_SETTINGS["dialogues"][key]))

    def _load_widgets(self):
        appearance = self._working["appearance"]
        storage = self._working["storage"]
        advanced = self._working["advanced"]
        self.size_slider.setValue(appearance["pet_height"])
        self.bubble_seconds.setValue(appearance["bubble_duration_ms"] / 1000.0)
        self.always_on_top.setChecked(appearance["always_on_top"])
        self.inbox_path.setText(storage["inbox_path"] or default_inbox_path())
        self.curious_enabled.setChecked(advanced["curious_enabled"])
        self.bored_enabled.setChecked(advanced["bored_enabled"])
        self.auto_sleep_enabled.setChecked(advanced["auto_sleep_enabled"])
        self.dizzy_enabled.setChecked(advanced["dizzy_enabled"])
        self.curious_hover_seconds.setValue(advanced["curious_hover_ms"] / 1000.0)
        self.curious_exit_distance.setValue(advanced["curious_exit_distance"])
        self.long_press_seconds.setValue(advanced["long_press_ms"] / 1000.0)
        self.bored_idle_minutes.setValue(advanced["bored_idle_ms"] / 60000.0)
        self.auto_sleep_minutes.setValue(advanced["auto_sleep_idle_ms"] / 60000.0)
        self.disturb_limit.setValue(advanced["disturb_limit"])
        index = self.shake_sensitivity.findData(advanced["shake_sensitivity"])
        self.shake_sensitivity.setCurrentIndex(max(0, index))
        self.speech_gap_seconds.setValue(advanced["speech_gap_ms"] / 1000.0)
        self.post_state_seconds.setValue(
            advanced["post_state_cooldown_ms"] / 1000.0
        )

    def _collect_widgets(self):
        self._save_current_dialogues()
        appearance = self._working["appearance"]
        storage = self._working["storage"]
        advanced = self._working["advanced"]
        appearance["pet_height"] = self.size_slider.value()
        appearance["bubble_duration_ms"] = round(self.bubble_seconds.value() * 1000)
        appearance["always_on_top"] = self.always_on_top.isChecked()
        storage["inbox_path"] = self.inbox_path.text().strip() or default_inbox_path()
        advanced["curious_enabled"] = self.curious_enabled.isChecked()
        advanced["bored_enabled"] = self.bored_enabled.isChecked()
        advanced["auto_sleep_enabled"] = self.auto_sleep_enabled.isChecked()
        advanced["dizzy_enabled"] = self.dizzy_enabled.isChecked()
        advanced["curious_hover_ms"] = round(self.curious_hover_seconds.value() * 1000)
        advanced["curious_exit_distance"] = self.curious_exit_distance.value()
        advanced["long_press_ms"] = round(self.long_press_seconds.value() * 1000)
        advanced["bored_idle_ms"] = round(
            self.bored_idle_minutes.value() * 60000
        )
        advanced["auto_sleep_idle_ms"] = round(self.auto_sleep_minutes.value() * 60000)
        advanced["disturb_limit"] = self.disturb_limit.value()
        advanced["shake_sensitivity"] = self.shake_sensitivity.currentData()
        advanced["speech_gap_ms"] = round(self.speech_gap_seconds.value() * 1000)
        advanced["post_state_cooldown_ms"] = round(
            self.post_state_seconds.value() * 1000
        )
        return copy.deepcopy(self._working)

    def _apply_settings(self):
        self.settings_applied.emit(self._collect_widgets())

    def _accept_settings(self):
        self._apply_settings()
        self.accept()

    def _restore_defaults(self):
        self._save_current_dialogues()
        self._working = copy.deepcopy(DEFAULT_SETTINGS)
        self._load_widgets()
        self._current_dialogue_key = self.dialogue_combo.currentData()
        self.dialogue_editor.setPlainText(
            "\n".join(self._working["dialogues"][self._current_dialogue_key])
        )

    def showEvent(self, event):
        self._load_widgets()
        super().showEvent(event)
