import math
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QRunnable,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QMenu,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from settings_dialog import SettingsDialog, SettingsStore, default_inbox_path
from clipboard_history import ClipboardHistoryDialog, ClipboardHistoryManager
from house_window import HandDrawnHouse

SINGLE_INSTANCE_SERVER_NAME = "DesktopPet_SingleInstance_v1"
SINGLE_INSTANCE_MESSAGE = b"show-already-running-message"
SINGLE_INSTANCE_ACK = b"desktop-pet-ack"
NOTES_FILE_NAME = "桌宠便签.txt"
LINKS_FILE_NAME = "链接收藏.txt"
IMAGES_FOLDER_NAME = "图片收藏"
IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".ico",
}


class FileCopySignals(QObject):
    finished = Signal(object, object)


class InboxDropTask(QRunnable):
    """在后台分类保存文件、图片、文字与链接。"""

    def __init__(
        self,
        destination,
        files=None,
        image_files=None,
        remote_image_urls=None,
        note_text="",
        links=None,
        inline_image=None,
    ):
        super().__init__()
        self.destination = Path(destination)
        self.files = [Path(source) for source in (files or [])]
        self.image_files = [Path(source) for source in (image_files or [])]
        self.remote_image_urls = list(remote_image_urls or [])
        self.note_text = note_text.strip()
        self.links = list(links or [])
        self.inline_image = inline_image.copy() if inline_image is not None else None
        self.signals = FileCopySignals()

    @staticmethod
    def _unique_destination(folder, source):
        candidate = folder / source.name
        if not candidate.exists():
            return candidate
        counter = 2
        while True:
            candidate = folder / f"{source.stem} ({counter}){source.suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _append_text(path, heading, content):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"[{timestamp}] {heading}\n{content}\n\n")

    def _copy_sources(self, sources, folder, kind, successes, failures):
        folder.mkdir(parents=True, exist_ok=True)
        for source in sources:
            try:
                if not source.is_file():
                    raise OSError("当前版本暂不支持文件夹")
                if source.parent.resolve() == folder.resolve():
                    raise OSError("内容已经在收纳位置中")
                target = self._unique_destination(folder, source)
                shutil.copy2(source, target)
                successes.append((kind, str(target)))
            except (OSError, shutil.Error) as error:
                failures.append(f"{source.name}: {error}")

    @staticmethod
    def _remote_image_name(url, content_type):
        parsed = urllib.parse.urlparse(url)
        name = Path(urllib.parse.unquote(parsed.path)).name
        suffix = Path(name).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            suffix = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/gif": ".gif",
                "image/webp": ".webp",
                "image/bmp": ".bmp",
                "image/tiff": ".tif",
            }.get(content_type.split(";", 1)[0].lower(), ".png")
            stem = Path(name).stem or "网页图片"
            name = f"{stem}{suffix}"
        return name

    def _download_remote_images(self, folder, successes, failures):
        folder.mkdir(parents=True, exist_ok=True)
        max_bytes = 30 * 1024 * 1024
        for url in self.remote_image_urls:
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 DesktopPet/1.0",
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    },
                )
                with urllib.request.urlopen(request, timeout=18) as response:
                    content_type = response.headers.get("Content-Type", "")
                    data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise OSError("图片超过 30 MB")
                image = QImage.fromData(data)
                if image.isNull():
                    raise OSError("网址返回的内容不是有效图片")
                name = self._remote_image_name(url, content_type)
                target = self._unique_destination(folder, Path(name))
                if not image.save(str(target)):
                    # 某些网页图片的扩展名与实际编码不一致，
                    # 统一转存 PNG 可避免保存失败。
                    target = self._unique_destination(folder, Path(f"{Path(name).stem}.png"))
                    if not image.save(str(target), "PNG"):
                        raise OSError("图片编码失败")
                successes.append(("image", str(target)))
            except Exception as error:
                failures.append(f"{url}: {error}")

    def run(self):
        successes = []
        failures = []
        try:
            self.destination.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            failures.append(str(error))
            self.signals.finished.emit(successes, failures)
            return

        self._copy_sources(
            self.files,
            self.destination,
            "file",
            successes,
            failures,
        )
        images_folder = self.destination / IMAGES_FOLDER_NAME
        self._copy_sources(
            self.image_files,
            images_folder,
            "image",
            successes,
            failures,
        )
        self._download_remote_images(images_folder, successes, failures)

        if self.inline_image is not None and not self.inline_image.isNull():
            try:
                images_folder.mkdir(parents=True, exist_ok=True)
                name = datetime.now().strftime("拖入图片_%Y%m%d_%H%M%S.png")
                target = self._unique_destination(images_folder, Path(name))
                if not self.inline_image.save(str(target), "PNG"):
                    raise OSError("图片编码失败")
                successes.append(("image", str(target)))
            except OSError as error:
                failures.append(str(error))

        if self.note_text:
            try:
                notes_path = self.destination / NOTES_FILE_NAME
                self._append_text(notes_path, "便签", self.note_text)
                successes.append(("note", str(notes_path)))
            except OSError as error:
                failures.append(str(error))

        if self.links:
            try:
                links_path = self.destination / LINKS_FILE_NAME
                for link in self.links:
                    self._append_text(links_path, "链接", link)
                successes.append(("link", str(links_path)))
            except OSError as error:
                failures.append(str(error))

        self.signals.finished.emit(successes, failures)

# =====================================================================
# 素材配置
# 想改文件名/加表情，只需修改这里
# =====================================================================
MASTER_CHARACTER_IMAGE = "pet.png"                          # 锁定的角色母版
DEFAULT_IMAGE = MASTER_CHARACTER_IMAGE                       # 默认待机图

def _resource_dir():
    """素材目录；打包成 exe 后也能定位到打包内的素材。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包运行：素材随 exe 解压到 _MEIPASS 临时目录
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).parent
    return Path(__file__).parent


BASE_DIR = _resource_dir()          # 素材目录


def build_executable():
    """使用当前 Python 环境中的 PyInstaller 生成单文件 EXE。"""
    if getattr(sys, "frozen", False):
        print("已经打包的程序不能再次执行打包，请从项目源码运行此命令。")
        return 1

    project_dir = Path(__file__).resolve().parent
    try:
        import PyInstaller  # noqa: F401
    except ModuleNotFoundError:
        print("没有安装 PyInstaller，请先执行：")
        print(f'"{sys.executable}" -m pip install pyinstaller')
        return 1

    required_paths = [
        project_dir / "main.py",
        project_dir / MASTER_CHARACTER_IMAGE,
        project_dir / "assets",
    ]
    missing = [path for path in required_paths if not path.exists()]
    if missing:
        print("无法打包，缺少以下文件或目录：")
        for path in missing:
            print(f"- {path}")
        return 1

    data_files = [
        *((path, ".") for path in sorted(project_dir.glob("happy_*.png"))),
        *((path, ".") for path in sorted(project_dir.glob("walk*.png"))),
        (project_dir / MASTER_CHARACTER_IMAGE, "."),
        (project_dir / "assets", "assets"),
    ]
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "DesktopPet",
    ]
    for source, destination in data_files:
        command.extend(["--add-data", f"{source};{destination}"])
    command.append(str(project_dir / "main.py"))

    print("正在打包 DesktopPet.exe，请稍候……")
    result = subprocess.run(command, cwd=project_dir, check=False)
    if result.returncode == 0:
        output_path = project_dir / "dist" / "DesktopPet.exe"
        print(f"打包完成：{output_path}")
    else:
        print(f"打包失败，PyInstaller 返回代码：{result.returncode}")
    return result.returncode


def _mid_frame_key(name):
    """按中间帧序号排序：happy01_2.png -> 2"""
    stem = name.rsplit(".", 1)[0]        # happy01_2
    return int(stem.rsplit("_", 1)[1])


def _discover_frames(prefix, count):
    """自动发现 prefix01~prefix{count} 源帧及其中间帧。

    中间帧命名为「源帧名_序号.png」（如 happy01_1.png、happy01_2.png），
    放进素材目录即自动按顺序播放，无需改代码。
    """
    frames = []
    for i in range(1, count + 1):
        base = f"{prefix}{i:02d}.png"
        if not (BASE_DIR / base).exists():
            continue
        frames.append(base)
        mids = sorted(
            (p.name for p in BASE_DIR.glob(f"{prefix}{i:02d}_*.png")),
            key=_mid_frame_key,
        )
        frames.extend(mids)
    return frames


# 开心动画帧：happy_01~happy_20
# + 自动发现的中间帧（happy_01_1.png 等，放入即生效）
HAPPY_FRAMES = _discover_frames("happy_", 20)

# 行走动画帧：walk01~walk05 源帧 + 自动发现的中间帧
WALK_FRAMES = _discover_frames("walk", 5)

# 睡觉动画：完整呼吸循环 sleep0→sleep1→sleep2→sleep1→…（吸气→呼）
# 注：sleep3 尺寸不同已剔除
SLEEP0_IMAGE = "assets/character/sleep/sleep_00.png"
SLEEP_FRAMES = [
    SLEEP0_IMAGE,
    "assets/character/sleep/sleep_01.png",
    "assets/character/sleep/sleep_02.png",
    "assets/character/sleep/sleep_01.png",
]

# nuzzle 只使用与睡眠母版比例最接近的 1/2，优先保证整体稳定。
NUZZLE_FRAMES = [
    SLEEP0_IMAGE,
    "assets/character/nuzzle/runtime/blend_01.png",
    "assets/character/nuzzle/runtime/nuzzle1.png",
    "assets/character/nuzzle/runtime/blend_02.png",
    "assets/character/nuzzle/runtime/nuzzle2.png",
    "assets/character/nuzzle/runtime/blend_02.png",
    "assets/character/nuzzle/runtime/nuzzle1.png",
    "assets/character/nuzzle/runtime/blend_01.png",
    SLEEP0_IMAGE,
]

DRAG_HANG_IMAGES = {
    "left": "assets/character/drag/drag_hang_left.png",
    "center": "assets/character/drag/drag_hang_center.png",
    "right": "assets/character/drag/drag_hang_right.png",
}

EASTER_EGG_IMAGES = {
    "ghost": "assets/character/easter_eggs/ghost.png",
    "dress": "assets/character/easter_eggs/dress.png",
}
RECEIVE_BASE_IMAGE = "assets/character/receive/receive_base.png"
RECEIVE_LABELS = {
    "file": "文件",
    "note": "文字",
    "link": "链接",
    "image": "图片",
    "mixed": "多种内容",
}
RECEIVE_POSE_HOLD_MS = 1050
RECEIVE_DREAM_HOLD_MS = 2400
EASTER_CLICK_WINDOW_MS = 10000
EASTER_CLICK_COUNT = 10
EASTER_PET_HOLD_MS = 10000
EASTER_HOLD_MS = 5000
EASTER_FADE_INTERVAL = 70

PET_HEIGHT = 350            # 统一缩放高度
HAPPY_INTERVAL = 40         # 原帧和内存过渡帧交替播放，约 25FPS
WALK_INTERVAL = 120         # 行走动画每帧间隔毫秒（约 0.6s 播完 5 帧）
SLEEP_INTERVAL = 420        # 睡眠呼吸要慢，完整吸呼约 2.1 秒
# nuzzle 每帧停留时长（毫秒），与 NUZZLE_FRAMES 一一对应：
# sleep0 0.3s → nuzzle1 0.25s → nuzzle2 0.25s → nuzzle3 0.35s
# → nuzzle4 0.6s → nuzzle5 0.35s → nuzzle6 0.3s → sleep0 0.4s
NUZZLE_INTERVALS = [
    300, 70, 240, 80, 520, 80, 240, 70, 400,
]
NUZZLE_MIN_DELAY = 8000     # 睡觉时随机触发 nuzzle 的最小间隔 ms
NUZZLE_MAX_DELAY = 18000    # 睡觉时随机触发 nuzzle 的最大间隔 ms
IDLE_INTERVAL = 33          # 待机渲染约 30 FPS；仅对默认图生效
MOTION_INTERVAL = 20        # 拖拽/落地姿态约 50 FPS
TAP_DURATION_MS = 420       # 高频单击反馈：短促但有完整的注意与回稳过程
DRAG_DIRECTION_TRIGGER_SPEED = 120.0  # 超过此水平速度才切换悬挂方向
DRAG_LOCK_ROTATION = 2.8             # 方向触发后保持的倾斜角度
EXPRESSION_TRANSITION_INTERVAL = 45  # 借现有眨眼帧遮住表情切换
POST_EXPRESSION_BLINK_PAUSE = 3200    # 表情退出后先保持睁眼，避免连续眨眼
BEHAVIOR_TICK_MS = 250                 # 自动行为检查频率
CURIOUS_NEAR_DISTANCE = 70             # 鼠标距窗口多近时视为“靠近”
CURIOUS_HOVER_MS = 1800                # 靠近停留后触发好奇
CURIOUS_COOLDOWN_MS = 18000            # 好奇表情冷却
CURIOUS_EXIT_DISTANCE = 190            # 触发后允许鼠标移动得更远，避免很快退出
AUTO_SLEEP_IDLE_MS = 90000             # 90 秒无互动后开始犯困
AUTO_SLEEP_TRANSITION_MS = 3400        # 困倦表情完成后进入睡眠
DISTURB_WINDOW_MS = 10000              # 与十连击彩蛋共用自然连续点击窗口
HURT_CLICK_COUNT = 3                   # 第三次点击表现委屈
DISTURB_LIMIT = 6                      # 第六次点击表现生气/不满
ANNOYED_COOLDOWN_MS = 14000            # 不满表情冷却

# 台词优先级只用于“等待队列”取舍，不会打断当前正在显示的台词。
SPEECH_PRIORITIES = {
    "curious": 1,
    "bored": 1,
    "sleepy": 1,
    "dream": 1,
    "click": 1,
    "petted": 2,
    "surprised": 2,
    "edge": 2,
    "hurt": 3,
    "manual": 3,
    "wakeup": 3,
    "inbox_success": 3,
    "note_success": 3,
    "link_success": 3,
    "image_success": 3,
    "dream_receive": 3,
    "clipboard_copy": 3,
    "annoyed": 4,
    "dizzy": 4,
    "inbox_failure": 4,
    "easter_ghost": 5,
    "easter_dress": 5,
}
EDGE_SNAP_DISTANCE = 24     # 基本碰到屏幕左右边缘时才吸附
STAGE_PADDING = 12          # 给呼吸、轻摆和脚下阴影预留的透明边缘
SHADOW_IMAGE = "assets/character/layers/ground_shadow.png"
BLINK_OPEN_IMAGE = "assets/character/expressions/pet_blink_open_v1.png"
BLINK_HALF_IMAGE = "assets/character/expressions/pet_blink_half_v1.png"
BLINK_ALMOST_IMAGE = "assets/character/expressions/pet_blink_almost_v1.png"
BLINK_CLOSED_IMAGE = "assets/character/expressions/pet_blink_closed_v1.png"

# 睡眠中单击触发的醒来动画。眼睛不能使用相邻帧透明混合，否则两套
# 睫毛会同时出现形成重影；改用清晰单帧组成“半睁→哈欠→半睁→睁眼”。
# 最后四帧仍用整体淡出/淡入遮住“沙发躺姿 → 站立姿态”的场景切换。
WAKE_FRAMES = [
    SLEEP0_IMAGE,
    "assets/character/wakeup/runtime/wake_01.png",
    "assets/character/wakeup/runtime/wake_02.png",
    "assets/character/wakeup/runtime/wake_01.png",
    "assets/character/wakeup/runtime/wake_03.png",
    "assets/character/wakeup/runtime/wake_04.png",
    "assets/character/wakeup/runtime/wake_scene_fade_67.png",
    "assets/character/wakeup/runtime/wake_scene_fade_33.png",
    "assets/character/wakeup/runtime/wake_stand_fade_33.png",
    "assets/character/wakeup/runtime/wake_stand_fade_67.png",
    BLINK_OPEN_IMAGE,
]
WAKE_INTERVALS = [
    140, 180, 380, 100, 180, 260, 65, 65, 65, 65, 150,
]
EXPRESSION_IMAGES = {
    "curious": "assets/character/expressions/pet_expression_curious_v1.png",
    "petted": "assets/character/expressions/pet_expression_petted_v1.png",
    "surprised": "assets/character/expressions/pet_expression_surprised_v1.png",
    "hurt": "assets/character/expressions/pet_expression_hurt_v1.png",
    "bored": "assets/character/expressions/pet_expression_bored_v1.png",
    "annoyed": "assets/character/expressions/pet_expression_annoyed_v1.png",
    "sleepy": "assets/character/expressions/pet_expression_sleepy_v1.png",
}
EXPRESSION_DURATIONS = {
    "curious": 1800,
    "petted": 2500,
    "surprised": 1400,
    "hurt": 1800,
    "bored": 5000,
    "annoyed": 1900,
    "sleepy": 2400,
}
DIZZY_IMAGES = {
    "light": "assets/character/dizzy/runtime/dizzy_01_light.png",
    "peak": "assets/character/dizzy/runtime/dizzy_02_peak.png",
    "recover": "assets/character/dizzy/runtime/dizzy_03_recover.png",
}
DIZZY_TEXTS = [
    "呜……世界在转……",
    "慢、慢一点啦……",
    "眼前好多星星……",
    "我有点站不稳了……",
]
SHAKE_WINDOW_MS = 900
SHAKE_SPEED_THRESHOLD = 340.0
SHAKE_REVERSALS_REQUIRED = 3
SHAKE_MIN_DISTANCE = 210
DIZZY_DURATION_MS = 2850
EDGE_LEFT_IMAGE = "assets/character/edge/cling_left_v1.png"
EDGE_RIGHT_IMAGE = "assets/character/edge/peek_right_v1.png"

# 贴边图中“屏幕边界”所在的横向比例。渲染时让这一点与真实屏幕边缘重合，
# 这样不是简单把整张 PNG 靠边，而是真正以双手抓握的位置为锚点。
EDGE_CONTACT_X = {
    "left": 0.158,
    "right": 0.960,
}
EDGE_TARGET_HEIGHT = {
    "left": 350,
    "right": 325,
}
EDGE_BLINK_IMAGES = {
    "left": {
        "open": "assets/character/edge/left_blink_open_ai_v1.png",
        "quarter": "assets/character/edge/left_blink_25_ai_v1.png",
        "half": "assets/character/edge/left_blink_60_ai_v1.png",
        "almost": "assets/character/edge/left_blink_80_ai_v1.png",
        "closed": "assets/character/edge/left_blink_100_ai_v1.png",
    },
    "right": {
        "open": "assets/character/edge/right_blink_open_ai_v1.png",
        "quarter": "assets/character/edge/right_blink_25_ai_v1.png",
        "half": "assets/character/edge/right_blink_60_ai_v1.png",
        "almost": "assets/character/edge/right_blink_80_ai_v1.png",
        "closed": "assets/character/edge/right_blink_100_ai_v1.png",
    },
}

# 说话气泡台词（可随意增删）
BUBBLE_TEXTS = [
    "你好呀，我是你的桌宠！",
    "摸摸头~ 今天也要加油哦！",
    "工作累了吧？休息一下~",
    "我来陪你写代码啦！",
    "记得喝水，注意休息！",
    "嘿嘿，猜猜我现在在想什么？",
    "你专注的样子真好看！",
    "代码会有的，bug 也会解决的~",
]


class SpeechBubble(QWidget):
    """高对比、带阴影和尾巴的桌宠说话气泡。"""

    MAX_TEXT_WIDTH = 270
    MIN_TEXT_WIDTH = 132
    MIN_WIDTH = 202
    HORIZONTAL_PADDING = 28
    VERTICAL_PADDING = 17
    TAIL_HEIGHT = 19
    MAX_LINES = 2

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._text = ""

        # 显式加载 Windows 中文字体，避免透明工具窗口或离屏渲染时
        # Qt 字体数据库尚未枚举完成而出现方框字。优先幼圆，缺失则雅黑。
        family = ""
        for font_path in (
            Path("C:/Windows/Fonts/SIMYOU.TTF"),
            Path("C:/Windows/Fonts/msyh.ttc"),
        ):
            if not font_path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                family = families[0]
                break
        if not family:
            family = "Microsoft YaHei UI"
        self._font = QFont(family)
        self._font.setPointSizeF(10.5)
        self._font.setWeight(QFont.Weight.DemiBold)
        self._font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)

    @property
    def text_flags(self):
        return Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap

    @staticmethod
    def _take_line(text, metrics, width):
        """取出在指定宽度内能完整显示的最长前缀。"""
        if metrics.horizontalAdvance(text) <= width:
            return text, ""
        low, high = 1, len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if metrics.horizontalAdvance(text[:middle]) <= width:
                low = middle
            else:
                high = middle - 1
        split_at = max(1, low)
        # 英文句子尽量在空格处换行，中文则可按字符自然换行。
        whitespace = text.rfind(" ", 0, split_at + 1)
        if whitespace >= max(1, split_at // 2):
            split_at = whitespace
        return text[:split_at].rstrip(), text[split_at:].lstrip()

    def _limit_to_two_lines(self, text, metrics, width):
        """所有台词统一限制为最多两行，超长在第二行末尾省略。"""
        normalized = " ".join(str(text).split())
        if not normalized:
            return ""
        first, remaining = self._take_line(normalized, metrics, width)
        if not remaining:
            return first
        second = metrics.elidedText(
            remaining,
            Qt.TextElideMode.ElideRight,
            width,
        )
        return f"{first}\n{second}"

    def set_message(self, text):
        metrics = QFontMetrics(self._font)
        normalized = " ".join(str(text).split())
        natural_width = metrics.horizontalAdvance(normalized)
        text_width = min(
            self.MAX_TEXT_WIDTH,
            max(self.MIN_TEXT_WIDTH, natural_width),
        )
        self._text = self._limit_to_two_lines(text, metrics, text_width)
        line_count = min(self.MAX_LINES, self._text.count("\n") + 1)
        # 使用实际行高预留完整两行空间，不再依赖
        # boundingRect 在不同中文字体下的偏小估算。
        text_height = metrics.lineSpacing() * max(2, line_count)
        body_height = max(
            72,
            text_height + self.VERTICAL_PADDING * 2 + 5,
        )
        width = max(
            self.MIN_WIDTH,
            text_width + self.HORIZONTAL_PADDING * 2 + 14,
        )
        height = body_height + self.TAIL_HEIGHT + 8
        self.resize(width, height)
        self.update()

    def _bubble_path(self):
        body = QRectF(
            7.0,
            5.0,
            self.width() - 14.0,
            self.height() - self.TAIL_HEIGHT - 8.0,
        )
        body_path = QPainterPath()
        body_path.addRoundedRect(body, 17.0, 17.0)

        center_x = self.width() / 2.0
        tail = QPainterPath()
        tail.moveTo(center_x - 13.0, body.bottom() - 1.0)
        tail.cubicTo(
            center_x - 8.0,
            body.bottom() + 4.0,
            center_x - 6.0,
            self.height() - 5.0,
            center_x,
            self.height() - 3.0,
        )
        tail.cubicTo(
            center_x + 5.0,
            self.height() - 7.0,
            center_x + 9.0,
            body.bottom() + 3.0,
            center_x + 14.0,
            body.bottom() - 1.0,
        )
        tail.closeSubpath()
        return body_path.united(tail), body

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path, body = self._bubble_path()

        # 深色柔和阴影让气泡在浅色或复杂桌面上仍能分离出来。
        painter.save()
        painter.translate(2.0, 3.0)
        painter.fillPath(path, QColor(45, 27, 36, 72))
        painter.restore()

        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        gradient.setColorAt(0.0, QColor(255, 255, 255, 250))
        gradient.setColorAt(1.0, QColor(255, 240, 245, 248))
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(126, 80, 96, 245), 2.1))
        painter.drawPath(path)

        # 一道淡色内边线和两个小圆点，增加轻盈感但不过度装饰。
        painter.setPen(QPen(QColor(255, 255, 255, 185), 1.0))
        painter.drawRoundedRect(body.adjusted(3.0, 3.0, -3.0, -3.0), 14.0, 14.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(229, 154, 180, 185))
        painter.drawEllipse(body.left() + 13.0, body.top() + 11.0, 5.0, 5.0)
        painter.setBrush(QColor(246, 193, 211, 165))
        painter.drawEllipse(body.left() + 20.0, body.top() + 8.0, 3.0, 3.0)

        painter.setFont(self._font)
        painter.setPen(QColor(55, 38, 45, 255))
        text_rect = body.adjusted(
            self.HORIZONTAL_PADDING,
            self.VERTICAL_PADDING - 2,
            -self.HORIZONTAL_PADDING,
            -(self.VERTICAL_PADDING - 2),
        )
        painter.drawText(text_rect, self.text_flags, self._text)
        painter.end()


# =====================================================================
# 桌面宠物
# =====================================================================
class DesktopPet(QWidget):
    def __init__(self):
        super().__init__()

        self.base_dir = Path(__file__).parent
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.pet_height = int(self.settings["appearance"]["pet_height"])

        # -------------------------
        # 1. 窗口设置
        # -------------------------
        window_flags = (
            Qt.WindowType.FramelessWindowHint      # 无标题栏边框
            | Qt.WindowType.Tool                   # 不占任务栏
        )
        if self.settings["appearance"]["always_on_top"]:
            window_flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(window_flags)
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True
        )
        self.setAcceptDrops(True)
        self._copy_pool = QThreadPool(self)
        # 同一时间只复制一批，彻底避免不同批次争抢同名目标文件。
        self._copy_pool.setMaxThreadCount(1)
        self._copy_tasks = set()
        self._dream_receive_kind = ""
        self.receive_timer = QTimer(self)
        self.receive_timer.setSingleShot(True)
        self.receive_timer.timeout.connect(self._finish_dream_receive_feedback)

        # -------------------------
        # 2. 加载图片
        # -------------------------
        self.label = QLabel(self)
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True
        )
        self._images = {}      # 文件名 -> 缩放后的 QPixmap 缓存
        self._load_all_images()
        self._prepare_stage()

        # -------------------------
        # 3. 动画状态
        # -------------------------
        self.anim_frames = []      # 当前动画帧图列表
        self.anim_index = 0        # 当前帧下标
        self.anim_name = ""        # 当前动画名称（用于状态判断）
        self.anim_looping = False  # 是否循环播放
        self.anim_on_finish = None # 播完后的回调
        self.anim_intervals = None # 每帧自定义停留时长（毫秒），None=统一间隔
        self._sleep_mode = False   # 睡觉持久模式：点击/拖拽后仍保持睡觉
        self.anim_timer = QTimer(self)
        self.anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.anim_timer.setInterval(WALK_INTERVAL)
        self.anim_timer.timeout.connect(self._on_anim_tick)

        # -------------------------
        # 3.1 待机生命感（不改变任何原始帧文件）
        # -------------------------
        self._idle_elapsed_ms = 0
        self._blink_start_ms = self._next_blink_start()
        self.idle_timer = QTimer(self)
        self.idle_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.idle_timer.setInterval(IDLE_INTERVAL)
        self.idle_timer.timeout.connect(self._on_idle_tick)

        # 睡觉呼吸循环待机时，随机间隔触发一次 nuzzle（蹭蹭）动画
        self.nuzzle_timer = QTimer(self)
        self.nuzzle_timer.setSingleShot(True)
        self.nuzzle_timer.timeout.connect(self._play_nuzzle)
        # 睡眠中的单击需要等双击判定结束后再执行，否则双击的第一下
        # 会先误触 nuzzle。
        self.sleep_click_timer = QTimer(self)
        self.sleep_click_timer.setSingleShot(True)
        self.sleep_click_timer.timeout.connect(self._play_sleep_touch)
        self.long_press_timer = QTimer(self)
        self.long_press_timer.setSingleShot(True)
        self.long_press_timer.timeout.connect(self._trigger_petted)
        self._long_press_triggered = False
        self.easter_hold_timer = QTimer(self)
        self.easter_hold_timer.setSingleShot(True)
        self.easter_hold_timer.timeout.connect(self._trigger_dress_easter_egg)
        self._easter_click_events = []
        self._easter_active = False

        # -------------------------
        # 3.2 可组合表情（目前从右键菜单手动预览）
        # -------------------------
        self._expression_name = ""
        self.expression_timer = QTimer(self)
        self.expression_timer.setSingleShot(True)
        self.expression_timer.timeout.connect(self._begin_expression_exit)

        # -------------------------
        # 3.3 自动行为：好奇 / 困倦 / 打扰记忆
        # -------------------------
        now = time.perf_counter()
        self._last_interaction_at = now
        self._automatic_behavior_block_until = 0.0
        self._near_hover_started_at = None
        self._last_curious_at = now - CURIOUS_COOLDOWN_MS / 1000.0
        self._bored_shown_for_idle = False
        self._bored_manual_preview_until = 0.0
        self._disturb_events = []
        self._annoyed_cooldown_until = 0.0
        self._pending_annoyed = False
        self._auto_sleep_pending = False
        self._woke_on_press = False
        self.behavior_timer = QTimer(self)
        self.behavior_timer.setInterval(BEHAVIOR_TICK_MS)
        self.behavior_timer.timeout.connect(self._on_behavior_tick)
        self.behavior_timer.start()
        self.auto_sleep_timer = QTimer(self)
        self.auto_sleep_timer.setSingleShot(True)
        self.auto_sleep_timer.timeout.connect(self._finish_auto_sleep)

        # -------------------------
        # 4. 说话气泡
        # -------------------------
        self.bubble = SpeechBubble()
        if not self.settings["appearance"]["always_on_top"]:
            self.bubble.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self._on_bubble_timeout)
        self.speech_gap_timer = QTimer(self)
        self.speech_gap_timer.setSingleShot(True)
        self.speech_gap_timer.timeout.connect(self._show_pending_speech)
        self._current_speech_category = ""
        self._current_speech_priority = 0
        self._pending_speech = None

        # -------------------------
        # 4.1 剪贴板历史（文字/链接/图片/文件）
        # -------------------------
        self.clipboard_history = ClipboardHistoryManager(
            QApplication.clipboard(),
            self,
        )
        self.clipboard_history.item_copied.connect(
            lambda _kind: self.say_category("clipboard_copy")
        )
        self._clipboard_dialog = None
        self._house_window = None

        # -------------------------
        # 5. 拖拽状态
        # -------------------------
        self.dragging = False
        self.drag_offset = QPoint()
        self.drag_moved = False   # 是否发生了实际位移（区分点击/拖拽）
        self._motion_state = ""
        self._edge_side = ""       # "left" / "right" / ""
        self._drag_rotation = 0.0
        self._drag_target_rotation = 0.0
        self._drag_hang_pose = "center"
        self._drag_last_global = QPoint()
        self._drag_last_time = time.perf_counter()
        self._drop_started_at = 0.0
        self._tap_direction = 0.0
        self._shake_last_direction = 0
        self._shake_reversals = []
        self._shake_distance = 0.0
        self._dizzy_pending = False
        self._dizzy_started_at = 0.0
        self.motion_timer = QTimer(self)
        self.motion_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.motion_timer.setInterval(MOTION_INTERVAL)
        self.motion_timer.timeout.connect(self._on_motion_tick)

        # -------------------------
        # 6. 显示默认图 & 初始位置
        # -------------------------
        self._show_default()
        self.idle_timer.start()

        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - self.width() - 40
        y = screen.bottom() - self.height() - 40
        self.move(x, y)

    # =================================================================
    # 图片加载
    # =================================================================
    def apply_settings(self, settings):
        """保存设置，并立即应用外观与行为参数。"""
        old_height = self.pet_height
        old_always_on_top = self.settings["appearance"]["always_on_top"]
        old_geometry = self.frameGeometry()
        self.settings = settings
        self.settings_store.save(settings)
        self.pet_height = int(settings["appearance"]["pet_height"])
        self._near_hover_started_at = None
        if not settings["advanced"]["auto_sleep_enabled"]:
            self._auto_sleep_pending = False
            self.auto_sleep_timer.stop()
        if not settings["advanced"]["dizzy_enabled"]:
            self._dizzy_pending = False

        if self.pet_height != old_height:
            self._edge_side = ""
            self._load_all_images()
            self._prepare_stage()
            self.move(
                old_geometry.center().x() - self.width() // 2,
                old_geometry.bottom() - self.height() + 1,
            )
            self._settle()
            if self.bubble.isVisible():
                self._position_bubble()

        always_on_top = settings["appearance"]["always_on_top"]
        if always_on_top != old_always_on_top:
            position = self.pos()
            was_visible = self.isVisible()
            bubble_was_visible = self.bubble.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, always_on_top)
            self.bubble.setWindowFlag(
                Qt.WindowType.WindowStaysOnTopHint,
                always_on_top,
            )
            if was_visible:
                self.show()
                self.move(position)
            if bubble_was_visible:
                self.bubble.show()
                self._position_bubble()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.settings_applied.connect(self.apply_settings)
        self.behavior_timer.stop()
        try:
            dialog.exec()
        finally:
            self._mark_activity()
            self.behavior_timer.start()

    def open_house(self):
        """让桌宠暂时离开桌面，进入程序绘制的手绘小屋。"""
        if self._house_window is None:
            self._house_window = HandDrawnHouse(self._inbox_path())
            self._house_window.returned_to_desktop.connect(self._return_from_house)
            self._house_window.request_sleep.connect(self._sleep_from_house)
        else:
            self._house_window.inbox_path = self._inbox_path()
            self._house_window.notes_path = self._inbox_path() / NOTES_FILE_NAME

        self.bubble_timer.stop()
        self.bubble.hide()
        self.idle_timer.stop()
        self.behavior_timer.stop()
        self.hide()
        self._house_window.show()
        self._house_window.raise_()
        self._house_window.activateWindow()

    def _return_from_house(self):
        """关闭小屋后，让原桌宠回到先前的桌面位置。"""
        self.show()
        self.raise_()
        self._mark_activity()
        if not self.idle_timer.isActive() and not self.anim_timer.isActive():
            self.idle_timer.start()
        if not self.behavior_timer.isActive():
            self.behavior_timer.start()

    def _sleep_from_house(self):
        """点击小屋沙发：回到桌面后直接进入现有睡眠状态。"""
        self._sleep_mode = True
        self._settle()

    def _load_all_images(self):
        """加载全部素材，统一缩放到用户设置的高度。缺失图片自动跳过。"""
        self._images = {}
        self._idle_sources = {}
        idle_names = {
            BLINK_OPEN_IMAGE,
            BLINK_HALF_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_CLOSED_IMAGE,
            *EXPRESSION_IMAGES.values(),
            *DRAG_HANG_IMAGES.values(),
            *DIZZY_IMAGES.values(),
        }
        names = [
            DEFAULT_IMAGE,
            BLINK_OPEN_IMAGE,
            BLINK_HALF_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_CLOSED_IMAGE,
            RECEIVE_BASE_IMAGE,
        ] + list(EXPRESSION_IMAGES.values()) + list(DRAG_HANG_IMAGES.values()) + list(DIZZY_IMAGES.values()) + list(EASTER_EGG_IMAGES.values()) + HAPPY_FRAMES + WALK_FRAMES + SLEEP_FRAMES + NUZZLE_FRAMES + WAKE_FRAMES
        for name in names:
            path = self.base_dir / name
            if not path.exists():
                continue
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                continue
            if name in idle_names:
                # 待机动画从高分辨率源图一次性绘制到舞台，避免先缩小再变换。
                self._idle_sources[name] = pixmap
            self._images[name] = pixmap.scaledToHeight(
                self.pet_height,
                Qt.TransformationMode.SmoothTransformation
            )

        self._prepare_receive_frames()

        if DEFAULT_IMAGE not in self._images:
            raise FileNotFoundError(
                f"没有找到人物图片：{self.base_dir / DEFAULT_IMAGE}"
            )

        shadow_path = self.base_dir / SHADOW_IMAGE
        self._ground_shadow = QPixmap(str(shadow_path))
        if not self._ground_shadow.isNull():
            self._ground_shadow = self._ground_shadow.scaledToHeight(
                self.pet_height,
                Qt.TransformationMode.SmoothTransformation,
            )
        else:
            self._ground_shadow = None

        self._edge_sources = {}
        self._edge_blink_sources = {}
        fallback_names = {
            "left": EDGE_LEFT_IMAGE,
            "right": EDGE_RIGHT_IMAGE,
        }
        for side, fallback_name in fallback_names.items():
            states = {}
            for state, name in EDGE_BLINK_IMAGES[side].items():
                pixmap = QPixmap(str(self.base_dir / name))
                if not pixmap.isNull():
                    states[state] = pixmap

            fallback = QPixmap(str(self.base_dir / fallback_name))
            if not fallback.isNull():
                self._edge_sources[side] = fallback
                states.setdefault("open", fallback)
            if states:
                self._edge_blink_sources[side] = states

    def _prepare_stage(self):
        """创建一个固定的透明舞台，避免待机动画让窗口尺寸跳动。"""
        widest = max(pixmap.width() for pixmap in self._images.values())
        self._stage_width = widest + STAGE_PADDING * 2
        self._stage_height = self.pet_height + STAGE_PADDING * 2
        self.label.setGeometry(0, 0, self._stage_width, self._stage_height)
        self.setFixedSize(self._stage_width, self._stage_height)

    def _next_blink_start(self):
        """返回下一次眨眼的开始时间，间隔略随机才不会像计时器。"""
        return self._idle_elapsed_ms + random.randint(4500, 8000)

    def _prepare_receive_frames(self):
        """在空白卡片上动态绘制内容类型，避免为四种内容重复生成人物。"""
        base = self._images.get(RECEIVE_BASE_IMAGE)
        if base is None:
            return
        family = "Microsoft YaHei UI"
        for font_path in (
            Path("C:/Windows/Fonts/SIMYOU.TTF"),
            Path("C:/Windows/Fonts/msyh.ttc"),
        ):
            if not font_path.exists():
                continue
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                family = families[0]
                break
        for kind, label in RECEIVE_LABELS.items():
            frame = base.copy()
            painter = QPainter(frame)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            card = QRectF(
                frame.width() * 0.382,
                frame.height() * 0.482,
                frame.width() * 0.258,
                frame.height() * 0.106,
            )
            icon_rect = QRectF(
                card.left() + card.width() * 0.10,
                card.top() + card.height() * 0.22,
                card.height() * 0.56,
                card.height() * 0.56,
            )
            self._draw_content_icon(painter, icon_rect, kind)
            font = QFont(family)
            font.setPixelSize(max(8, round(card.height() * 0.27)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(QColor(112, 73, 68))
            text_rect = QRectF(
                icon_rect.right() + card.width() * 0.07,
                card.top(),
                card.right() - icon_rect.right() - card.width() * 0.14,
                card.height(),
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            painter.end()
            self._images[f"__receive_{kind}"] = frame

    @staticmethod
    def _draw_content_icon(painter, rect, kind):
        """用矢量线条绘制类型图标，在任意缩放尺寸下都保持清晰。"""
        color = QColor(192, 116, 105)
        pen = QPen(color, max(1.2, rect.height() * 0.075))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if kind == "file":
            body = QRectF(rect.left() + rect.width() * 0.12, rect.top(), rect.width() * 0.72, rect.height())
            painter.drawRoundedRect(body, rect.width() * 0.08, rect.width() * 0.08)
            painter.drawLine(
                QPointF(body.left() + body.width() * 0.22, body.top() + body.height() * 0.38),
                QPointF(body.right() - body.width() * 0.18, body.top() + body.height() * 0.38),
            )
            painter.drawLine(
                QPointF(body.left() + body.width() * 0.22, body.top() + body.height() * 0.62),
                QPointF(body.right() - body.width() * 0.30, body.top() + body.height() * 0.62),
            )
        elif kind == "note":
            painter.drawRoundedRect(rect, rect.width() * 0.12, rect.width() * 0.12)
            for ratio in (0.30, 0.50, 0.70):
                painter.drawLine(
                    QPointF(rect.left() + rect.width() * 0.20, rect.top() + rect.height() * ratio),
                    QPointF(rect.right() - rect.width() * (0.20 if ratio != 0.70 else 0.38), rect.top() + rect.height() * ratio),
                )
        elif kind == "link":
            painter.drawEllipse(QRectF(rect.left(), rect.top() + rect.height() * 0.15, rect.width() * 0.62, rect.height() * 0.48))
            painter.drawEllipse(QRectF(rect.left() + rect.width() * 0.38, rect.top() + rect.height() * 0.37, rect.width() * 0.62, rect.height() * 0.48))
            painter.drawLine(
                QPointF(rect.left() + rect.width() * 0.36, rect.top() + rect.height() * 0.56),
                QPointF(rect.left() + rect.width() * 0.64, rect.top() + rect.height() * 0.44),
            )
        elif kind == "image":
            painter.drawRoundedRect(rect, rect.width() * 0.10, rect.width() * 0.10)
            painter.drawEllipse(QRectF(rect.left() + rect.width() * 0.62, rect.top() + rect.height() * 0.16, rect.width() * 0.16, rect.width() * 0.16))
            mountain = QPainterPath()
            mountain.moveTo(rect.left() + rect.width() * 0.12, rect.bottom() - rect.height() * 0.16)
            mountain.lineTo(rect.left() + rect.width() * 0.40, rect.top() + rect.height() * 0.48)
            mountain.lineTo(rect.left() + rect.width() * 0.57, rect.top() + rect.height() * 0.66)
            mountain.lineTo(rect.left() + rect.width() * 0.72, rect.top() + rect.height() * 0.43)
            mountain.lineTo(rect.right() - rect.width() * 0.08, rect.bottom() - rect.height() * 0.16)
            painter.drawPath(mountain)
        else:
            radius = rect.width() * 0.13
            painter.setBrush(QColor(230, 164, 153))
            for x_ratio, y_ratio in ((0.28, 0.28), (0.72, 0.28), (0.28, 0.72), (0.72, 0.72)):
                painter.drawEllipse(QPointF(rect.left() + rect.width() * x_ratio, rect.top() + rect.height() * y_ratio), radius, radius)
            painter.setBrush(Qt.BrushStyle.NoBrush)

    @staticmethod
    def _star_path(center_x, center_y, outer_radius, inner_radius=None):
        """创建一个柔和的五角星路径，供头晕状态动态绘制。"""
        inner_radius = inner_radius or outer_radius * 0.46
        path = QPainterPath()
        for index in range(10):
            radius = outer_radius if index % 2 == 0 else inner_radius
            angle = -math.pi / 2 + index * math.pi / 5
            point = QPointF(
                center_x + math.cos(angle) * radius,
                center_y + math.sin(angle) * radius,
            )
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        path.closeSubpath()
        return path

    def _render_to_stage(
        self,
        pixmap,
        *,
        scale_x=1.0,
        scale_y=1.0,
        rotation=0.0,
        x_offset=0.0,
        y_offset=0.0,
        shadow_scale=1.0,
        shadow_opacity=1.0,
        fit_height=False,
        target_height=None,
        draw_shadow=True,
        supersample=1,
        star_phase=None,
        star_opacity=0.0,
    ):
        """在固定透明舞台绘制角色与接触阴影。"""
        render_width = self._stage_width * supersample
        render_height = self._stage_height * supersample
        stage = QPixmap(render_width, render_height)
        stage.fill(Qt.GlobalColor.transparent)
        painter = QPainter(stage)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if supersample > 1:
            painter.scale(supersample, supersample)

        base_x = self._stage_width / 2
        base_y = self._stage_height - STAGE_PADDING
        if draw_shadow and self._ground_shadow is not None:
            painter.save()
            painter.setOpacity(shadow_opacity)
            painter.translate(base_x, base_y)
            painter.scale(shadow_scale, 1.0)
            painter.translate(-self._ground_shadow.width() / 2, -self._ground_shadow.height())
            painter.drawPixmap(0, 0, self._ground_shadow)
            painter.restore()

        painter.save()
        painter.translate(base_x + x_offset, base_y + y_offset)
        painter.rotate(rotation)
        if target_height is None:
            target_height = self.pet_height
        fit_scale = target_height / pixmap.height() if fit_height else 1.0
        painter.scale(fit_scale * scale_x, fit_scale * scale_y)
        painter.translate(-pixmap.width() / 2, -pixmap.height())
        painter.drawPixmap(0, 0, pixmap)
        painter.restore()

        if star_phase is not None and star_opacity > 0.0:
            # 星星在舞台坐标中绕头部旋转，不烘焙进人物素材，因此不会
            # 改变角色轮廓，也能保持每帧清晰。
            colors = (
                QColor(255, 211, 79),
                QColor(255, 151, 166),
                QColor(132, 211, 255),
                QColor(255, 228, 132),
            )
            painter.save()
            painter.setOpacity(max(0.0, min(1.0, star_opacity)))
            size_scale = self.pet_height / PET_HEIGHT
            orbit_center_x = base_x
            orbit_center_y = STAGE_PADDING + (76.0 - STAGE_PADDING) * size_scale
            for index, color in enumerate(colors):
                angle = star_phase + index * math.tau / len(colors)
                x = orbit_center_x + math.cos(angle) * 76.0 * size_scale
                y = orbit_center_y + math.sin(angle) * 29.0 * size_scale
                size = (7.5 if index % 2 == 0 else 6.0) * size_scale
                painter.setPen(QPen(QColor(255, 255, 255, 225), 1.1))
                painter.setBrush(color)
                painter.drawPath(self._star_path(x, y, size))
            painter.restore()

        if self._sleep_mode and self._dream_receive_kind:
            self._draw_dream_receive_overlay(painter)
        painter.end()

        if supersample > 1:
            # 先在双倍画布完成透明边缘的旋转与缩放，再一次性缩回显示尺寸，
            # 避免轻微晃动时轮廓在相邻像素间跳变形成毛刺。
            stage = stage.scaled(
                self._stage_width,
                self._stage_height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        self.label.setPixmap(stage)

    def _draw_dream_receive_overlay(self, painter):
        """睡眠时只在沙发上方浮出梦境提示，不改变人物或沙发。"""
        scale = self.pet_height / PET_HEIGHT
        cloud = QRectF(
            self._stage_width - 112.0 * scale - STAGE_PADDING,
            22.0 * scale,
            98.0 * scale,
            58.0 * scale,
        )
        painter.save()
        painter.setPen(QPen(QColor(190, 137, 131, 220), max(1.0, 1.4 * scale)))
        painter.setBrush(QColor(255, 252, 249, 238))
        path = QPainterPath()
        path.addRoundedRect(cloud, 18.0 * scale, 18.0 * scale)
        painter.drawPath(path)
        painter.drawEllipse(QRectF(cloud.left() - 13.0 * scale, cloud.bottom() - 8.0 * scale, 12.0 * scale, 12.0 * scale))
        painter.drawEllipse(QRectF(cloud.left() - 22.0 * scale, cloud.bottom() + 4.0 * scale, 7.0 * scale, 7.0 * scale))

        icon_rect = QRectF(
            cloud.left() + 10.0 * scale,
            cloud.top() + 15.0 * scale,
            28.0 * scale,
            28.0 * scale,
        )
        self._draw_content_icon(painter, icon_rect, self._dream_receive_kind)
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(max(8, round(10.0 * scale)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(108, 74, 70))
        painter.drawText(
            QRectF(
                icon_rect.right() + 6.0 * scale,
                cloud.top(),
                cloud.right() - icon_rect.right() - 12.0 * scale,
                cloud.height(),
            ),
            Qt.AlignmentFlag.AlignCenter,
            RECEIVE_LABELS.get(self._dream_receive_kind, "内容"),
        )
        painter.restore()

    def _current_blink_frame(self):
        """选择当前眨眼帧，供普通待机和扒边待机共同使用。"""
        blink_elapsed = self._idle_elapsed_ms - self._blink_start_ms
        if blink_elapsed < 0:
            blink_frame = BLINK_OPEN_IMAGE
        elif blink_elapsed < 33:
            blink_frame = BLINK_HALF_IMAGE
        elif blink_elapsed < 66:
            blink_frame = BLINK_ALMOST_IMAGE
        elif blink_elapsed < 132:
            blink_frame = BLINK_CLOSED_IMAGE
        elif blink_elapsed < 165:
            blink_frame = BLINK_ALMOST_IMAGE
        elif blink_elapsed < 198:
            blink_frame = BLINK_HALF_IMAGE
        else:
            blink_frame = BLINK_OPEN_IMAGE
            if blink_elapsed >= 198:
                self._blink_start_ms = self._next_blink_start()
        return blink_frame

    def _current_edge_blink_state(self):
        """左右贴边姿态均使用 AI 绘制的四级闭合帧。"""
        blink_elapsed = self._idle_elapsed_ms - self._blink_start_ms
        if blink_elapsed < 0:
            state = "open"
        elif blink_elapsed < 33:
            state = "quarter"
        elif blink_elapsed < 66:
            state = "half"
        elif blink_elapsed < 99:
            state = "almost"
        elif blink_elapsed < 165:
            state = "closed"
        elif blink_elapsed < 198:
            state = "almost"
        elif blink_elapsed < 231:
            state = "half"
        elif blink_elapsed < 264:
            state = "quarter"
        else:
            state = "open"
            self._blink_start_ms = self._next_blink_start()
        return state

    def _render_idle_frame(self):
        """呼吸、微摆与眨眼：幅度刻意很小，避免像抖动的 GIF。"""
        breath = math.sin((self._idle_elapsed_ms / 3600) * math.tau)
        sway = math.sin((self._idle_elapsed_ms / 5100) * math.tau)
        if self._expression_name:
            frame = EXPRESSION_IMAGES[self._expression_name]
        else:
            frame = self._current_blink_frame()

        curious_direction = 0.0
        if self._expression_name == "curious":
            delta_x = QCursor.pos().x() - self.frameGeometry().center().x()
            curious_direction = max(-1.0, min(1.0, delta_x / 120.0))

        self._render_to_stage(
            self._idle_sources[frame],
            scale_x=1.0 - breath * 0.0018,
            scale_y=1.0 + breath * 0.006,
            rotation=sway * 0.22 + curious_direction * 0.72,
            x_offset=sway * 0.7 + curious_direction * 0.9,
            shadow_scale=1.0 - breath * 0.035,
            fit_height=True,
            supersample=2,
        )

    def _render_edge_cling_frame(self):
        """使用专用透明素材绘制左侧扒边或右侧探头姿态。"""
        blink_state = self._current_edge_blink_state()
        source = self._edge_blink_sources.get(self._edge_side, {}).get(blink_state)
        if source is None:
            source = self._edge_sources.get(self._edge_side)
        if source is None:
            # 素材缺失时仍可运行，退回普通待机图作为安全占位。
            source = self._idle_sources[BLINK_OPEN_IMAGE]
            target_height = self.pet_height
            contact_x = 0.5
        else:
            target_height = (
                EDGE_TARGET_HEIGHT[self._edge_side]
                * self.pet_height
                / PET_HEIGHT
            )
            contact_x = EDGE_CONTACT_X[self._edge_side]

        bob = math.sin((self._idle_elapsed_ms / 1900) * math.tau)
        sway = math.sin((self._idle_elapsed_ms / 2700) * math.tau)
        rendered_width = source.width() * target_height / source.height()
        desired_contact_x = (
            STAGE_PADDING
            if self._edge_side == "left"
            else self._stage_width - STAGE_PADDING
        )
        anchor_offset = (
            desired_contact_x
            - self._stage_width / 2
            + rendered_width / 2
            - rendered_width * contact_x
        )

        if self._edge_side == "left":
            rotation = -0.28 + sway * 0.20
            x_offset = anchor_offset + sway * 0.35
            y_offset = bob * 1.0
        else:
            # 右侧探头以极轻的横向探入代替整个人物摆动。
            rotation = sway * 0.12
            x_offset = anchor_offset - 0.8 + bob * 0.8
            y_offset = -10.0 + sway * 0.55

        self._render_to_stage(
            source,
            rotation=rotation,
            x_offset=x_offset,
            y_offset=y_offset,
            fit_height=True,
            target_height=target_height,
            draw_shadow=False,
            supersample=2,
        )

    def _show_image(self, name):
        """切换显示的图片，并让窗口匹配图片大小。"""
        pixmap = self._images[name]
        self._render_to_stage(
            pixmap,
            draw_shadow=(
                name not in SLEEP_FRAMES
                and name not in NUZZLE_FRAMES
                and name not in WAKE_FRAMES
            ),
        )

    def _show_default(self):
        if self._edge_side:
            self._render_edge_cling_frame()
        else:
            self._render_idle_frame()

    def _render_drag_pose(
        self,
        *,
        rotation=0.0,
        scale_x=0.985,
        scale_y=0.985,
        y_offset=-8.0,
        shadow_scale=0.72,
        shadow_opacity=0.38,
    ):
        """绘制悬空或落地姿态；睡觉模式下保持 sleep0 形象。"""
        if self._sleep_mode and SLEEP0_IMAGE in self._images:
            source = self._images[SLEEP0_IMAGE]
        elif self._motion_state == "drag":
            pose = self._drag_hang_pose
            source = self._images.get(
                DRAG_HANG_IMAGES[pose],
                self._idle_sources[BLINK_OPEN_IMAGE],
            )
            source = self._idle_sources.get(DRAG_HANG_IMAGES[pose], source)
            shadow_opacity = 0.0
        else:
            source = self._idle_sources[BLINK_OPEN_IMAGE]
        self._render_to_stage(
            source,
            rotation=rotation,
            scale_x=scale_x,
            scale_y=scale_y,
            y_offset=y_offset,
            shadow_scale=shadow_scale,
            shadow_opacity=shadow_opacity,
            fit_height=True,
            supersample=2,
        )

    def _begin_drag_motion(self):
        """进入悬空拖拽状态，并安全打断当前动作。"""
        self._clear_expression(render=False)
        self.anim_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
        self.idle_timer.stop()
        self._edge_side = ""
        self._motion_state = "drag"
        self._register_disturbance()
        self._drag_rotation = 0.0
        self._drag_target_rotation = 0.0
        self._drag_hang_pose = "center"
        self._shake_last_direction = 0
        self._shake_reversals = []
        self._shake_distance = 0.0
        self._dizzy_pending = False
        self.motion_timer.start()
        self._render_drag_pose()

    def _begin_drop_motion(self):
        """从悬空姿态进入短促的压缩、回弹和稳定过程。"""
        self._motion_state = "drop"
        self._drop_started_at = time.perf_counter()
        self.motion_timer.start()

    def _update_shake_detection(self, velocity_x, delta_x, now):
        """记录快速左右反转；普通单向拖动不会触发头晕。"""
        advanced = self.settings["advanced"]
        if (
            not advanced["dizzy_enabled"]
            or self._motion_state != "drag"
            or self._dizzy_pending
        ):
            return
        profiles = {
            "easy": (270.0, 2, 160),
            "normal": (340.0, 3, 210),
            "hard": (440.0, 4, 280),
        }
        speed_threshold, reversals_required, minimum_distance = profiles.get(
            advanced["shake_sensitivity"],
            profiles["normal"],
        )
        self._shake_distance += abs(delta_x)
        cutoff = now - SHAKE_WINDOW_MS / 1000.0
        self._shake_reversals = [
            stamp for stamp in self._shake_reversals if stamp >= cutoff
        ]
        if abs(velocity_x) < speed_threshold:
            return
        direction = 1 if velocity_x > 0 else -1
        if self._shake_last_direction and direction != self._shake_last_direction:
            self._shake_reversals.append(now)
        self._shake_last_direction = direction
        if (
            len(self._shake_reversals) >= reversals_required
            and self._shake_distance >= minimum_distance
        ):
            self._dizzy_pending = True

    def _begin_click_motion(self):
        """普通单击播放短促的注意反馈，不占用长时间交互。"""
        self._clear_expression(render=False)
        self.anim_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
        self.anim_intervals = None
        self.idle_timer.stop()
        self._motion_state = "tap"
        self._drop_started_at = time.perf_counter()
        self.motion_timer.start()
        self._render_tap_pose(0.0)

    def _render_tap_pose(self, elapsed_ms):
        """轻缩、侧头回应、反向缓冲、回稳，并穿插一次柔和眯眼。"""
        direction = self._tap_direction
        if elapsed_ms < 65:
            progress = self._ease_in_out(elapsed_ms / 65)
            scale_x = 1.0 + 0.012 * progress
            scale_y = 1.0 - 0.014 * progress
            rotation = direction * 0.22 * progress
            x_offset = direction * 0.25 * progress
            y_offset = 0.9 * progress
            shadow_scale = 1.0 + 0.018 * progress
        elif elapsed_ms < 155:
            progress = self._ease_in_out((elapsed_ms - 65) / 90)
            scale_x = 1.012 - 0.018 * progress
            scale_y = 0.986 + 0.030 * progress
            rotation = direction * (0.22 + 0.92 * progress)
            x_offset = direction * (0.25 + 0.70 * progress)
            y_offset = 0.9 - 4.0 * progress
            shadow_scale = 1.018 - 0.040 * progress
        elif elapsed_ms < 275:
            progress = self._ease_in_out((elapsed_ms - 155) / 120)
            scale_x = 0.994 + 0.011 * progress
            scale_y = 1.016 - 0.021 * progress
            rotation = direction * (1.14 - 1.46 * progress)
            x_offset = direction * (0.95 - 1.10 * progress)
            y_offset = -3.1 + 3.9 * progress
            shadow_scale = 0.978 + 0.030 * progress
        else:
            progress = self._ease_in_out(
                (elapsed_ms - 275) / (TAP_DURATION_MS - 275)
            )
            scale_x = 1.005 - 0.005 * progress
            scale_y = 0.995 + 0.005 * progress
            rotation = direction * -0.32 * (1.0 - progress)
            x_offset = direction * -0.15 * (1.0 - progress)
            y_offset = 0.8 * (1.0 - progress)
            shadow_scale = 1.008 - 0.008 * progress

        if 72 <= elapsed_ms < 132:
            source_name = BLINK_HALF_IMAGE
        elif 132 <= elapsed_ms < 172:
            source_name = BLINK_ALMOST_IMAGE
        elif 172 <= elapsed_ms < 212:
            source_name = BLINK_HALF_IMAGE
        else:
            source_name = BLINK_OPEN_IMAGE
        source = self._idle_sources[source_name]
        self._render_to_stage(
            source,
            rotation=rotation,
            scale_x=scale_x,
            scale_y=scale_y,
            x_offset=x_offset,
            y_offset=y_offset,
            shadow_scale=shadow_scale,
            shadow_opacity=1.0,
            fit_height=True,
            supersample=2,
        )

    def _begin_dizzy_motion(self):
        """落地后进入短暂头晕状态，并显示一句对应台词。"""
        self._clear_expression(render=False)
        self.anim_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
        self.anim_intervals = None
        self.idle_timer.stop()
        self._motion_state = "dizzy"
        self._dizzy_started_at = time.perf_counter()
        self.say_category("dizzy")
        self.motion_timer.start()
        self._render_dizzy_frame(0.0)

    def _render_dizzy_frame(self, elapsed_ms):
        """用三张清晰表情帧、轻摆和程序星星表现眩晕。"""
        if elapsed_ms < 360:
            state = "light"
            progress = elapsed_ms / 360
            sway_strength = 1.15 - 0.30 * progress
            star_opacity = 0.25 + 0.55 * progress
        elif elapsed_ms < 2050:
            state = "peak"
            sway_strength = 0.72
            star_opacity = 1.0
        else:
            state = "recover"
            progress = min(1.0, (elapsed_ms - 2050) / 800)
            sway_strength = 0.55 * (1.0 - progress)
            star_opacity = 1.0 - progress

        phase = elapsed_ms / 760 * math.tau
        sway = math.sin(elapsed_ms / 620 * math.tau)
        bob = math.sin(elapsed_ms / 410 * math.tau)
        source = self._idle_sources[DIZZY_IMAGES[state]]
        self._render_to_stage(
            source,
            rotation=sway * sway_strength,
            x_offset=sway * sway_strength * 1.15,
            y_offset=bob * 0.45,
            shadow_scale=1.0 - abs(sway) * 0.018,
            fit_height=True,
            supersample=2,
            star_phase=phase,
            star_opacity=star_opacity,
        )

    @staticmethod
    def _ease_out(value):
        value = max(0.0, min(1.0, value))
        return 1.0 - (1.0 - value) ** 3

    @staticmethod
    def _ease_in_out(value):
        value = max(0.0, min(1.0, value))
        return value * value * (3.0 - 2.0 * value)

    def _on_motion_tick(self):
        if self._motion_state == "drag":
            self._drag_rotation += (
                self._drag_target_rotation - self._drag_rotation
            ) * 0.30
            self._render_drag_pose(rotation=self._drag_rotation)
            return

        if self._motion_state == "dizzy":
            elapsed_ms = (time.perf_counter() - self._dizzy_started_at) * 1000
            if elapsed_ms < DIZZY_DURATION_MS:
                self._render_dizzy_frame(elapsed_ms)
            else:
                self.motion_timer.stop()
                self._motion_state = ""
                self._blink_start_ms = self._next_blink_start()
                self._settle()
            return

        if self._motion_state == "tap":
            elapsed_ms = (time.perf_counter() - self._drop_started_at) * 1000
            if elapsed_ms < TAP_DURATION_MS:
                self._render_tap_pose(elapsed_ms)
            else:
                self.motion_timer.stop()
                self._motion_state = ""
                self._blink_start_ms = self._next_blink_start()
                self._settle()
            return

        if self._motion_state != "drop":
            self.motion_timer.stop()
            return

        elapsed_ms = (time.perf_counter() - self._drop_started_at) * 1000
        if elapsed_ms < 105:
            progress = self._ease_out(elapsed_ms / 105)
            self._render_drag_pose(
                rotation=self._drag_rotation * (1.0 - progress),
                scale_x=0.985 + 0.055 * progress,
                scale_y=0.985 - 0.045 * progress,
                y_offset=-8.0 * (1.0 - progress),
                shadow_scale=0.72 + 0.38 * progress,
                shadow_opacity=0.38 + 0.62 * progress,
            )
        elif elapsed_ms < 225:
            progress = self._ease_out((elapsed_ms - 105) / 120)
            self._render_drag_pose(
                rotation=0.0,
                scale_x=1.04 - 0.055 * progress,
                scale_y=0.94 + 0.078 * progress,
                y_offset=-2.0 * progress,
                shadow_scale=1.10 - 0.08 * progress,
                shadow_opacity=1.0,
            )
        elif elapsed_ms < 380:
            progress = self._ease_out((elapsed_ms - 225) / 155)
            self._render_drag_pose(
                rotation=0.0,
                scale_x=0.985 + 0.015 * progress,
                scale_y=1.018 - 0.018 * progress,
                y_offset=-2.0 * (1.0 - progress),
                shadow_scale=1.02 - 0.02 * progress,
                shadow_opacity=1.0,
            )
        else:
            trigger_dizzy = self._dizzy_pending
            self._dizzy_pending = False
            self.motion_timer.stop()
            self._motion_state = ""
            self._drag_rotation = 0.0
            self._drag_target_rotation = 0.0
            self._drag_hang_pose = "center"
            self._blink_start_ms = self._next_blink_start()
            if trigger_dizzy:
                self._begin_dizzy_motion()
            else:
                self._settle()

    def _try_enter_edge_cling(self, release_position=None):
        """若靠近当前屏幕左右边缘，则吸附并进入扒边状态。"""
        screen_point = release_position or self.frameGeometry().center()
        screen = QApplication.screenAt(screen_point)
        if screen is None:
            screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()

        visual_left = self.x() + STAGE_PADDING
        visual_right = self.x() + self.width() - STAGE_PADDING - 1
        distances = {
            "left": abs(visual_left - geometry.left()),
            "right": abs(visual_right - geometry.right()),
        }
        if release_position is not None:
            # 拖拽通常抓在人物身体中间；鼠标已经碰到屏幕边缘时，
            # 人物透明窗口的边缘可能仍很远，因此两种距离取更小值。
            distances["left"] = min(
                distances["left"],
                abs(release_position.x() - geometry.left()),
            )
            distances["right"] = min(
                distances["right"],
                abs(release_position.x() - geometry.right()),
            )
        side = min(distances, key=distances.get)
        if distances[side] > EDGE_SNAP_DISTANCE:
            return False

        self.anim_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
        self.motion_timer.stop()
        self._motion_state = ""
        self._edge_side = side

        if side == "left":
            target_x = geometry.left() - STAGE_PADDING
        else:
            target_x = geometry.right() - self.width() + STAGE_PADDING + 1
        target_y = max(
            geometry.top(),
            min(self.y(), geometry.bottom() - self.height() + 1),
        )
        self.move(target_x, target_y)
        if self.bubble.isVisible():
            self._position_bubble()

        self._blink_start_ms = self._next_blink_start()
        self._render_edge_cling_frame()
        self.idle_timer.start()
        self.say_category("edge")
        return True

    def _tween_frame(self, first_name, second_name):
        """在内存中生成两帧的短暂交叉过渡，不写入新的图片文件。"""
        key = f"__tween__{first_name}__{second_name}"
        if key in self._images:
            return key

        first = self._images[first_name]
        second = self._images[second_name]
        tween = QPixmap(first.size())
        tween.fill(Qt.GlobalColor.transparent)

        painter = QPainter(tween)
        painter.drawPixmap(0, 0, first)
        painter.setOpacity(0.5)
        painter.drawPixmap(0, 0, second)
        painter.end()

        self._images[key] = tween
        return key

    def _blend_frame(self, first_name, second_name, second_opacity):
        """将不同宽度的两套角色图居中交叉混合，供彩蛋柔和换装。"""
        opacity_key = round(float(second_opacity), 2)
        key = f"__blend__{first_name}__{second_name}__{opacity_key:.2f}"
        if key in self._images:
            return key

        first = self._images[first_name]
        second = self._images[second_name]
        width = max(first.width(), second.width())
        height = max(first.height(), second.height())
        blended = QPixmap(width, height)
        blended.fill(Qt.GlobalColor.transparent)

        painter = QPainter(blended)
        painter.setOpacity(1.0 - second_opacity)
        painter.drawPixmap(
            (width - first.width()) // 2,
            height - first.height(),
            first,
        )
        painter.setOpacity(second_opacity)
        painter.drawPixmap(
            (width - second.width()) // 2,
            height - second.height(),
            second,
        )
        painter.end()

        self._images[key] = blended
        return key

    def _smooth_happy_frames(self, frames):
        """在每两张开心关键帧之间插入一张内存过渡帧。"""
        if len(frames) < 2:
            return frames

        smoothed = []
        for first, second in zip(frames, frames[1:]):
            smoothed.append(first)
            smoothed.append(self._tween_frame(first, second))
        smoothed.append(frames[-1])
        return smoothed

    def _show_easter_speech(self, category):
        """彩蛋台词需要与变身同步出现，因此会替换普通排队台词。"""
        lines = self.settings["dialogues"].get(category, [])
        if not lines:
            return
        self.bubble_timer.stop()
        self.speech_gap_timer.stop()
        self._pending_speech = None
        self.bubble.hide()
        self._current_speech_category = ""
        self._current_speech_priority = 0
        self._display_speech(
            random.choice(lines),
            category,
            SPEECH_PRIORITIES[category],
        )

    def _play_easter_egg(self, kind):
        """旧角色柔和淡去、彩蛋角色出现五秒，再淡回普通待机。"""
        special = EASTER_EGG_IMAGES.get(kind)
        if (
            self._easter_active
            or special not in self._images
            or self._sleep_mode
            or self._edge_side
        ):
            return False

        start = (
            EXPRESSION_IMAGES["petted"]
            if kind == "dress"
            else BLINK_OPEN_IMAGE
        )
        end = BLINK_OPEN_IMAGE
        frames = [
            start,
            self._blend_frame(start, special, 0.25),
            self._blend_frame(start, special, 0.50),
            self._blend_frame(start, special, 0.75),
            special,
            self._blend_frame(special, end, 0.25),
            self._blend_frame(special, end, 0.50),
            self._blend_frame(special, end, 0.75),
            end,
        ]

        self.easter_hold_timer.stop()
        self.long_press_timer.stop()
        self.expression_timer.stop()
        self.motion_timer.stop()
        self._motion_state = ""
        self._pending_annoyed = False
        self._disturb_events.clear()
        self._easter_active = True
        self.dragging = False
        self.drag_moved = False
        self.play_frames(
            frames,
            name=f"easter_{kind}",
            looping=False,
            on_finish=self._finish_easter_egg,
        )
        self._show_easter_speech(f"easter_{kind}")
        return True

    def _finish_easter_egg(self):
        self._easter_active = False
        self._long_press_triggered = False
        self._mark_activity()
        self._settle()

    def _register_easter_click(self):
        """十秒内累计十次短按时触发幽灵玩偶彩蛋。"""
        now = time.perf_counter()
        window_seconds = EASTER_CLICK_WINDOW_MS / 1000.0
        self._easter_click_events = [
            stamp for stamp in self._easter_click_events
            if now - stamp <= window_seconds
        ]
        self._easter_click_events.append(now)
        if len(self._easter_click_events) < EASTER_CLICK_COUNT:
            return False
        self._easter_click_events.clear()
        return self._play_easter_egg("ghost")

    def _trigger_dress_easter_egg(self):
        """一次不松手的摸头持续满十秒时触发古装彩蛋。"""
        if (
            self.dragging
            and not self.drag_moved
            and self._long_press_triggered
            and not self._sleep_mode
            and not self._edge_side
        ):
            self._play_easter_egg("dress")

    # =================================================================
    # 动画播放
    # =================================================================
    def play_frames(self, frames, name="", looping=False, on_finish=None):
        """播放一组帧图。

        frames:    图片文件名列表
        name:      动画名称（用于状态判断，如 "happy"/"walk"）
        looping:   True=循环播放直到手动停止；False=播一遍后回调
        on_finish: 播完后的回调（looping 时无效）
        """
        # 过滤掉缺失的帧
        usable = [f for f in frames if f in self._images]
        if not usable:
            return

        self._clear_expression(render=False)
        self.idle_timer.stop()

        # 20 张源图保持不变；开心动作播放时临时补成 39 帧。
        if name == "happy":
            usable = self._smooth_happy_frames(usable)

        self.anim_frames = usable
        self.anim_index = 0
        self.anim_name = name
        self.anim_looping = looping
        self.anim_on_finish = on_finish
        self.anim_intervals = None   # 每帧自定义停留时长（毫秒），None=统一间隔

        # 按动画类型设置播放间隔（开心动画放慢）
        if name == "happy":
            self.anim_timer.setInterval(HAPPY_INTERVAL)
        elif name == "walk":
            self.anim_timer.setInterval(WALK_INTERVAL)
        elif name == "sleep":
            self.anim_timer.setInterval(SLEEP_INTERVAL)
        elif name == "nuzzle":
            # nuzzle 每帧节奏不同，从第一帧时长开始
            self.anim_intervals = NUZZLE_INTERVALS
            self.anim_timer.setInterval(NUZZLE_INTERVALS[0])
        elif name == "wakeup":
            self.anim_intervals = WAKE_INTERVALS
            self.anim_timer.setInterval(WAKE_INTERVALS[0])
        elif name.startswith("receive_"):
            self.anim_intervals = [
                55, 65, 80, RECEIVE_POSE_HOLD_MS, 90, 70, 60,
            ]
            self.anim_timer.setInterval(self.anim_intervals[0])
        elif name.startswith("easter_"):
            self.anim_intervals = [
                EASTER_FADE_INTERVAL,
                EASTER_FADE_INTERVAL,
                EASTER_FADE_INTERVAL,
                EASTER_FADE_INTERVAL,
                EASTER_HOLD_MS,
                EASTER_FADE_INTERVAL,
                EASTER_FADE_INTERVAL,
                EASTER_FADE_INTERVAL,
                EASTER_FADE_INTERVAL,
            ]
            self.anim_timer.setInterval(self.anim_intervals[0])
        elif name.startswith("expression_"):
            self.anim_timer.setInterval(EXPRESSION_TRANSITION_INTERVAL)

        self._show_image(usable[0])
        self.anim_timer.start()

    def stop_animation(self):
        """停止动画，回到默认图。"""
        self.anim_timer.stop()
        self.nuzzle_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
        self.anim_intervals = None
        self._show_default()
        self.idle_timer.start()

    def _on_idle_tick(self):
        """只有待机状态刷新；开心和行走仍直接播放原始序列。"""
        if self.anim_name:
            return
        self._idle_elapsed_ms += IDLE_INTERVAL
        if self._edge_side:
            self._render_edge_cling_frame()
        else:
            self._render_idle_frame()

    def _on_anim_tick(self):
        self.anim_index += 1
        if self.anim_index >= len(self.anim_frames):
            if self.anim_looping:
                # 循环：回到开头
                self.anim_index = 0
            else:
                # 播完：停掉动画，交给回调安顿回常态（睡觉/待机）
                callback = self.anim_on_finish
                self.anim_timer.stop()
                self.nuzzle_timer.stop()
                self.anim_frames = []
                self.anim_name = ""
                self.anim_looping = False
                self.anim_on_finish = None
                self.anim_intervals = None
                if callback:
                    callback()
                return
        if self.anim_intervals:
            idx = min(self.anim_index, len(self.anim_intervals) - 1)
            self.anim_timer.setInterval(self.anim_intervals[idx])
        self._show_image(self.anim_frames[self.anim_index])

    def is_walking(self):
        return self.anim_name == "walk"

    def is_sleeping(self):
        return self._sleep_mode

    def _settle(self):
        """临时动画结束后安顿回常态：睡觉（若开启）或默认待机/贴边。"""
        self.anim_timer.stop()
        self.nuzzle_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
        self.anim_intervals = None
        if not self._sleep_mode:
            self._protect_automatic_behaviors()
        if self._pending_annoyed and not self._sleep_mode and not self._edge_side:
            self._pending_annoyed = False
            self.show_expression("annoyed")
            self.say_category("annoyed")
        elif self._sleep_mode and not self._edge_side:
            # 睡觉模式：回到呼吸循环并安排下一次随机 nuzzle
            self.play_frames(SLEEP_FRAMES, name="sleep", looping=True)
            self._schedule_nuzzle()
        else:
            self._show_default()
            self.idle_timer.start()

    # =================================================================
    # 睡觉时的随机 nuzzle（蹭蹭）
    # =================================================================
    def _schedule_nuzzle(self):
        """睡觉呼吸循环待机时，安排一次随机延迟的 nuzzle 触发。"""
        delay = random.randint(NUZZLE_MIN_DELAY, NUZZLE_MAX_DELAY)
        self.nuzzle_timer.start(delay)

    def _play_nuzzle(self):
        """只在睡觉呼吸循环中触发 nuzzle，避免误打断其他状态。"""
        if self.anim_name != "sleep":
            return
        self.play_frames(
            NUZZLE_FRAMES,
            name="nuzzle",
            looping=False,
            on_finish=self._settle,
        )

    # =================================================================
    # 说话气泡
    # =================================================================
    def _position_bubble(self):
        """把气泡放在宠物正上方（跟随宠物当前位置）。"""
        screen = QApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QApplication.primaryScreen()
        available = screen.availableGeometry()
        bubble_x = self.x() + (self.width() - self.bubble.width()) // 2
        bubble_x = max(
            available.left() + 6,
            min(bubble_x, available.right() - self.bubble.width() - 5),
        )
        bubble_y = max(
            available.top() + 6,
            self.y() - self.bubble.height() - 9,
        )
        self.bubble.move(bubble_x, bubble_y)

    def _display_speech(self, text, category="", priority=0):
        """立即显示一句台词；调用方负责确认当前不在保护期。"""
        self._current_speech_category = category
        self._current_speech_priority = priority
        self.bubble.set_message(text)
        self._position_bubble()
        self.bubble.show()
        self.bubble.raise_()
        self.bubble_timer.start(
            int(self.settings["appearance"]["bubble_duration_ms"])
        )

    def say(self, text, category="", priority=0):
        """完整显示当前台词；新台词排队，绝不覆盖正在显示的内容。"""
        if not text:
            return False

        protected = (
            self.bubble.isVisible()
            or self.bubble_timer.isActive()
            or self.speech_gap_timer.isActive()
        )
        if protected:
            # 同一触发源的重复台词不排队，避免连续刷出两句同类内容。
            if category and category == self._current_speech_category:
                return False
            candidate = (priority, text, category)
            if (
                self._pending_speech is None
                or priority >= self._pending_speech[0]
            ):
                self._pending_speech = candidate
            return False

        self._display_speech(text, category, priority)
        return True

    def _on_bubble_timeout(self):
        """一句台词播完后先留白，再决定是否播放排队台词。"""
        self.bubble.hide()
        self._current_speech_category = ""
        self._current_speech_priority = 0
        self.speech_gap_timer.start(
            int(self.settings["advanced"]["speech_gap_ms"])
        )

    def _speech_still_relevant(self, category):
        """丢弃已经过时的自动台词，避免状态结束后才补说。"""
        if category == "curious":
            return self._expression_name == "curious"
        if category in ("petted", "surprised", "hurt", "bored"):
            return self._expression_name == category
        if category == "sleepy":
            return self._auto_sleep_pending or self._expression_name == "sleepy"
        if category in ("dream", "dream_receive"):
            return self._sleep_mode
        if category == "dizzy":
            return self._motion_state == "dizzy"
        if category == "edge":
            return bool(self._edge_side)
        return True

    def _show_pending_speech(self):
        pending = self._pending_speech
        self._pending_speech = None
        if pending is None:
            return
        priority, text, category = pending
        if self._speech_still_relevant(category):
            self._display_speech(text, category, priority)

    def say_category(self, category):
        """从用户为某个触发情境配置的台词中随机选择一句。"""
        lines = self.settings["dialogues"].get(category, [])
        if lines:
            self.say(
                random.choice(lines),
                category,
                SPEECH_PRIORITIES.get(category, 2),
            )

    def say_random(self):
        self.say_category("manual")

    # =================================================================
    # 局部表情
    # =================================================================
    def show_expression(self, name):
        """通过一次完整眨眼进入表情，避免五官瞬间跳变。"""
        if name not in EXPRESSION_IMAGES or self._edge_side:
            return
        target = EXPRESSION_IMAGES[name]
        transition = [
            BLINK_HALF_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_CLOSED_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_HALF_IMAGE,
            target,
        ]
        self.play_frames(
            transition,
            name="expression_enter",
            looping=False,
            on_finish=lambda: self._hold_expression(name),
        )

    def _hold_expression(self, name):
        """保持表情，同时继续使用待机呼吸和轻摆。"""
        self._expression_name = name
        self._render_idle_frame()
        self.idle_timer.start()
        if name == "petted" and self.dragging and self._long_press_triggered:
            # 摸头表情由鼠标按住状态决定，松开前不自动计时退出。
            self.expression_timer.stop()
        elif name in ("curious", "bored"):
            # 好奇由鼠标距离决定；无聊由下一次互动或困倦接管。
            self.expression_timer.stop()
        else:
            self.expression_timer.start(EXPRESSION_DURATIONS[name])

    def _begin_expression_exit(self):
        """再次借眨眼闭合点退出表情。"""
        if not self._expression_name:
            return
        target = EXPRESSION_IMAGES[self._expression_name]
        self._expression_name = ""
        transition = [
            target,
            BLINK_HALF_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_CLOSED_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_HALF_IMAGE,
            BLINK_OPEN_IMAGE,
        ]
        self.play_frames(
            transition,
            name="expression_exit",
            looping=False,
            on_finish=lambda: (
                self._pause_blink_after_expression(),
                self._settle(),
            ),
        )

    def _pause_blink_after_expression(self):
        """表情切回待机后留出自然凝视时间，再恢复随机眨眼。"""
        self._blink_start_ms = (
            self._idle_elapsed_ms + POST_EXPRESSION_BLINK_PAUSE
        )
        self._render_idle_frame()

    def _clear_expression(self, render=True):
        self.expression_timer.stop()
        was_active = bool(self._expression_name)
        self._expression_name = ""
        if render and was_active and not self.anim_name and not self._edge_side:
            self._blink_start_ms = self._next_blink_start()
            self._render_idle_frame()

    # =================================================================
    # 自动行为与简单记忆
    # =================================================================
    def _mark_activity(self):
        """记录真实互动，并取消尚未完成的自动入睡。"""
        self._last_interaction_at = time.perf_counter()
        self._bored_shown_for_idle = False
        self._protect_automatic_behaviors(1200)
        self._auto_sleep_pending = False
        self.auto_sleep_timer.stop()

    def _protect_automatic_behaviors(self, duration_ms=None):
        """动作结束后暂缓好奇/困倦，让角色与台词有自然停顿。"""
        if duration_ms is None:
            duration_ms = self.settings["advanced"]["post_state_cooldown_ms"]
        self._automatic_behavior_block_until = max(
            self._automatic_behavior_block_until,
            time.perf_counter() + duration_ms / 1000.0,
        )
        # 保护期内的靠近不累计时间，结束后需要重新稳定停留。
        self._near_hover_started_at = None

    def _can_start_automatic_behavior(self):
        return not any((
            self.anim_name,
            self._expression_name,
            self._motion_state,
            self.dragging,
            self._edge_side,
            self._sleep_mode,
            self._auto_sleep_pending,
            self._easter_active,
        ))

    def _on_behavior_tick(self):
        """鼠标靠近时好奇；长时间无互动时先困倦再睡眠。"""
        now = time.perf_counter()
        cursor_position = QCursor.pos()

        # 好奇触发后使用更大的退出范围形成滞回：鼠标仍在附近时持续
        # 保持表情和视线跟随，只有明显离远才自然退出。
        if self._expression_name == "curious":
            if not self.settings["advanced"]["curious_enabled"]:
                self._begin_expression_exit()
                return
            exit_distance = self.settings["advanced"]["curious_exit_distance"]
            curious_keep_rect = self.frameGeometry().adjusted(
                -exit_distance,
                -exit_distance,
                exit_distance,
                exit_distance,
            )
            if curious_keep_rect.contains(cursor_position):
                return
            self._last_curious_at = now
            self._near_hover_started_at = None
            self._begin_expression_exit()
            return

        # “无聊”是困倦前的持续状态：鼠标靠近便退出并准备进入好奇，
        # 继续无人互动则自然被困倦状态接管。
        if self._expression_name == "bored":
            if now < self._bored_manual_preview_until:
                return
            near_rect = self.frameGeometry().adjusted(
                -CURIOUS_NEAR_DISTANCE,
                -CURIOUS_NEAR_DISTANCE,
                CURIOUS_NEAR_DISTANCE,
                CURIOUS_NEAR_DISTANCE,
            )
            mouse_is_near = near_rect.contains(cursor_position)
            idle_ms = (now - self._last_interaction_at) * 1000
            if not self.settings["advanced"]["bored_enabled"] or mouse_is_near:
                self._begin_expression_exit()
                return
            if (
                self.settings["advanced"]["auto_sleep_enabled"]
                and idle_ms >= self.settings["advanced"]["auto_sleep_idle_ms"]
            ):
                self._auto_sleep_pending = True
                self.show_expression("sleepy")
                self.say_category("sleepy")
                self.auto_sleep_timer.start(AUTO_SLEEP_TRANSITION_MS)
            return

        if now < self._automatic_behavior_block_until:
            self._near_hover_started_at = None
            return

        near_rect = self.frameGeometry().adjusted(
            -CURIOUS_NEAR_DISTANCE,
            -CURIOUS_NEAR_DISTANCE,
            CURIOUS_NEAR_DISTANCE,
            CURIOUS_NEAR_DISTANCE,
        )
        mouse_is_near = near_rect.contains(cursor_position)

        if mouse_is_near:
            if self._near_hover_started_at is None:
                self._near_hover_started_at = now
        else:
            self._near_hover_started_at = None

        # 困倦已经触发后，由单次计时器负责入睡。此期间不再
        # 重新播放困倦表情，否则会不断重置入睡倒计时。
        if self._auto_sleep_pending:
            return

        if not self._can_start_automatic_behavior():
            return

        curious_ready = (
            self.settings["advanced"]["curious_enabled"]
            and mouse_is_near
            and self._near_hover_started_at is not None
            and (now - self._near_hover_started_at) * 1000
            >= self.settings["advanced"]["curious_hover_ms"]
            and (now - self._last_curious_at) * 1000 >= CURIOUS_COOLDOWN_MS
        )
        if curious_ready:
            self._last_curious_at = now
            self._near_hover_started_at = now
            self.show_expression("curious")
            self.say_category("curious")
            return

        idle_ms = (now - self._last_interaction_at) * 1000
        if (
            self.settings["advanced"]["auto_sleep_enabled"]
            and not mouse_is_near
            and idle_ms >= self.settings["advanced"]["auto_sleep_idle_ms"]
        ):
            self._auto_sleep_pending = True
            self.show_expression("sleepy")
            self.say_category("sleepy")
            self.auto_sleep_timer.start(AUTO_SLEEP_TRANSITION_MS)
            return

        if (
            self.settings["advanced"]["bored_enabled"]
            and not mouse_is_near
            and not self._bored_shown_for_idle
            and idle_ms >= self.settings["advanced"]["bored_idle_ms"]
        ):
            self._bored_shown_for_idle = True
            self.show_expression("bored")
            self.say_category("bored")

    def _finish_auto_sleep(self):
        """只有困倦期间没有新互动才真正进入睡眠。"""
        if not self._auto_sleep_pending:
            return
        self._auto_sleep_pending = False
        idle_ms = (time.perf_counter() - self._last_interaction_at) * 1000
        if (
            not self.settings["advanced"]["auto_sleep_enabled"]
            or idle_ms < self.settings["advanced"]["auto_sleep_idle_ms"]
            or self.dragging
            or self._edge_side
        ):
            return
        self._sleep_mode = True
        self._settle()

    def _wake_from_sleep(self):
        """拖拽睡着的桌宠时立即唤醒，避免拖拽动作被醒来动画阻塞。"""
        if not self._sleep_mode:
            return False
        self._sleep_mode = False
        self.nuzzle_timer.stop()
        self.anim_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
        self.anim_intervals = None
        self._blink_start_ms = self._next_blink_start()
        self._show_default()
        self.idle_timer.start()
        return True

    def _play_wakeup(self):
        """睡眠中双击或选择“停止睡觉”后播放完整醒来动画。"""
        if not self._sleep_mode:
            return
        self.sleep_click_timer.stop()
        self._sleep_mode = False
        self.nuzzle_timer.stop()
        self.play_frames(
            WAKE_FRAMES,
            name="wakeup",
            looping=False,
            on_finish=self._finish_wakeup,
        )

    def _finish_wakeup(self):
        """醒来后重新从零计算无互动时间，并恢复普通待机。"""
        self._mark_activity()
        self._blink_start_ms = self._next_blink_start()
        self._settle()
        self.say_category("wakeup")

    def _register_disturbance(self):
        """十秒点击链中第三次委屈、第六次生气，之后仍可累积彩蛋。"""
        now = time.perf_counter()
        if now < self._annoyed_cooldown_until:
            return False
        window_seconds = DISTURB_WINDOW_MS / 1000.0
        self._disturb_events = [
            stamp for stamp in self._disturb_events
            if now - stamp <= window_seconds
        ]
        self._disturb_events.append(now)
        disturb_limit = self.settings["advanced"]["disturb_limit"]
        if len(self._disturb_events) == HURT_CLICK_COUNT:
            self.show_expression("hurt")
            self.say_category("hurt")
            return True
        if len(self._disturb_events) < disturb_limit:
            return False
        # 不清空另一条十连击计数链；第六次之后由冷却阻止重复生气，
        # 用户若继续点击，仍可在第十次顺利触发彩蛋。
        self._annoyed_cooldown_until = now + ANNOYED_COOLDOWN_MS / 1000.0
        if self.dragging or self._motion_state == "drag":
            self._pending_annoyed = True
        else:
            self.show_expression("annoyed")
            self.say_category("annoyed")
        return True

    # =================================================================
    # 文件收纳箱
    # =================================================================
    def _inbox_path(self):
        configured = self.settings["storage"]["inbox_path"].strip()
        return Path(configured or default_inbox_path()).expanduser().resolve()

    @staticmethod
    def _supports_mime_data(mime_data):
        return bool(
            mime_data.hasUrls()
            or mime_data.hasImage()
            or (mime_data.hasText() and mime_data.text().strip())
        )

    @staticmethod
    def _classify_drop(mime_data):
        local_paths = []
        links = []
        remote_image_urls = []

        def add_unique(collection, value):
            if value and value not in collection:
                collection.append(value)

        def looks_like_image_url(value):
            try:
                parsed = urllib.parse.urlparse(value)
            except ValueError:
                return False
            return (
                parsed.scheme.lower() in ("http", "https")
                and Path(urllib.parse.unquote(parsed.path)).suffix.lower()
                in IMAGE_SUFFIXES
            )

        # Chrome/Edge/Firefox 拖动网页图片时，常常只给出
        # HTML 中的 <img src> 而不是图片像素。
        if mime_data.hasHtml():
            html = mime_data.html()
            for match in re.finditer(
                r"<img\b[^>]*?\bsrc\s*=\s*(['\"])(.*?)\1",
                html,
                flags=re.IGNORECASE | re.DOTALL,
            ):
                source = match.group(2).strip().replace("&amp;", "&")
                if source.lower().startswith(("http://", "https://")):
                    add_unique(remote_image_urls, source)

        # Chromium 在部分站点使用 DownloadURL：
        # image/png:filename.png:https://...
        for mime_format in mime_data.formats():
            if str(mime_format).lower() != "downloadurl":
                continue
            raw = bytes(mime_data.data(mime_format)).decode("utf-8", errors="ignore")
            parts = raw.split(":", 2)
            if len(parts) == 3 and parts[0].lower().startswith("image/"):
                add_unique(remote_image_urls, parts[2].strip())

        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile() and url.toLocalFile():
                    local_paths.append(Path(url.toLocalFile()))
                elif url.scheme().lower() in ("http", "https"):
                    value = url.toString()
                    if value in remote_image_urls or looks_like_image_url(value):
                        add_unique(remote_image_urls, value)
                    else:
                        add_unique(links, value)

        files = []
        image_files = []
        for path in local_paths:
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                image_files.append(path)
            elif path.is_file():
                files.append(path)

        inline_image = None
        if not local_paths and mime_data.hasImage():
            image_data = mime_data.imageData()
            if isinstance(image_data, QPixmap):
                inline_image = image_data.toImage()
            elif isinstance(image_data, QImage):
                inline_image = image_data

        note_text = ""
        if not local_paths and inline_image is None and not links and not remote_image_urls and mime_data.hasText():
            text = mime_data.text().strip()
            possible_link = QUrl(text)
            if (
                "\n" not in text
                and possible_link.isValid()
                and possible_link.scheme().lower() in ("http", "https")
            ):
                if looks_like_image_url(text):
                    remote_image_urls.append(text)
                else:
                    links.append(text)
            else:
                note_text = text[:1_000_000]

        # 只要拖拽数据明确包含 <img>，就把它视为图片拖放；
        # 网页附带的跳转地址不再额外记入链接收藏。
        if remote_image_urls:
            links = []

        return (
            files,
            image_files,
            remote_image_urls,
            note_text,
            links,
            inline_image,
        )

    @staticmethod
    def _content_kind(
        files,
        image_files,
        remote_image_urls,
        note_text,
        links,
        inline_image,
    ):
        kinds = set()
        if files:
            kinds.add("file")
        if image_files or remote_image_urls or inline_image is not None:
            kinds.add("image")
        if note_text:
            kinds.add("note")
        if links:
            kinds.add("link")
        if len(kinds) == 1:
            return next(iter(kinds))
        return "mixed" if kinds else ""

    def _show_receive_feedback(self, kind):
        """清醒时举牌；睡眠时只显示梦境气泡，不打断睡姿。"""
        if not kind:
            return
        if self._sleep_mode:
            self._dream_receive_kind = kind
            self.receive_timer.start(RECEIVE_DREAM_HOLD_MS)
            if self.anim_name and self.anim_frames:
                self._show_image(self.anim_frames[self.anim_index])
            return
        if self._edge_side or self.dragging or self._easter_active:
            return

        target = f"__receive_{kind}"
        start = BLINK_OPEN_IMAGE
        if target not in self._images or start not in self._images:
            return
        frames = [
            self._blend_frame(start, target, 0.24),
            self._blend_frame(start, target, 0.52),
            self._blend_frame(start, target, 0.80),
            target,
            self._blend_frame(start, target, 0.72),
            self._blend_frame(start, target, 0.38),
            start,
        ]
        self.play_frames(
            frames,
            name=f"receive_{kind}",
            looping=False,
            on_finish=self._settle,
        )

    def _finish_dream_receive_feedback(self):
        if not self._dream_receive_kind:
            return
        self._dream_receive_kind = ""
        if self.anim_name and self.anim_frames:
            self._show_image(self.anim_frames[self.anim_index])
        elif self._sleep_mode:
            self._settle()

    def _say_dream_receive(self, kind):
        label = RECEIVE_LABELS.get(kind, "东西")
        lines = self.settings["dialogues"].get("dream_receive", [])
        if not lines:
            lines = ["唄……梦里收到了{类型}……"]
        text = random.choice(lines).replace("{类型}", label)
        self.say(
            text,
            "dream_receive",
            SPEECH_PRIORITIES["dream_receive"],
        )

    def dragEnterEvent(self, event):
        if not self._supports_mime_data(event.mimeData()):
            event.ignore()
            return
        self._mark_activity()
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if self._can_start_automatic_behavior():
            self.show_expression("surprised")

    def dragMoveEvent(self, event):
        if self._supports_mime_data(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        (
            files,
            image_files,
            remote_image_urls,
            note_text,
            links,
            inline_image,
        ) = self._classify_drop(event.mimeData())
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self._mark_activity()
        if not any((
            files,
            image_files,
            remote_image_urls,
            note_text,
            links,
            inline_image is not None,
        )):
            self.say_category("inbox_failure")
            return

        receive_kind = self._content_kind(
            files,
            image_files,
            remote_image_urls,
            note_text,
            links,
            inline_image,
        )
        was_sleeping = self._sleep_mode
        self._show_receive_feedback(receive_kind)

        task = InboxDropTask(
            self._inbox_path(),
            files=files,
            image_files=image_files,
            remote_image_urls=remote_image_urls,
            note_text=note_text,
            links=links,
            inline_image=inline_image,
        )
        self._copy_tasks.add(task)
        task.signals.finished.connect(
            lambda successes, failures, current=task, sleeping=was_sleeping:
            self._on_inbox_copy_finished(current, successes, failures, sleeping)
        )
        self._copy_pool.start(task)

    def _on_inbox_copy_finished(self, task, successes, failures, was_sleeping=False):
        self._copy_tasks.discard(task)
        self._last_inbox_failures = list(failures)
        if successes:
            kinds = {kind for kind, _path in successes}
            category = {
                "file": "inbox_success",
                "note": "note_success",
                "link": "link_success",
                "image": "image_success",
            }.get(next(iter(kinds)), "inbox_success") if len(kinds) == 1 else "inbox_success"
            if was_sleeping and self._sleep_mode:
                kind = next(iter(kinds)) if len(kinds) == 1 else "mixed"
                self._say_dream_receive(kind)
            else:
                self.say_category(category)
        if failures:
            self.say_category("inbox_failure")

    def open_inbox(self):
        self._open_collection_path(self._inbox_path(), is_folder=True)

    def open_notes(self):
        self._open_collection_path(self._inbox_path() / NOTES_FILE_NAME)

    def open_links(self):
        self._open_collection_path(self._inbox_path() / LINKS_FILE_NAME)

    def open_images(self):
        self._open_collection_path(
            self._inbox_path() / IMAGES_FOLDER_NAME,
            is_folder=True,
        )

    def open_clipboard_history(self):
        if self._clipboard_dialog is None:
            self._clipboard_dialog = ClipboardHistoryDialog(
                self.clipboard_history,
                self,
            )
        self._clipboard_dialog.refresh()
        self._clipboard_dialog.show()
        self._clipboard_dialog.raise_()
        self._clipboard_dialog.activateWindow()

    def _open_collection_path(self, target, is_folder=False):
        try:
            if is_folder:
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=True)
        except OSError:
            self.say_category("inbox_failure")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.say_category("inbox_failure")

    # =================================================================
    # 鼠标事件
    # =================================================================
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._easter_active:
                event.accept()
                return
            self.long_press_timer.stop()
            self.easter_hold_timer.stop()
            self._long_press_triggered = False
            self._mark_activity()
            if self._expression_name in ("curious", "bored"):
                # 点击或准备拖拽时立即结束自动观察/等待状态。
                self._clear_expression(render=True)
            # 先记住按下时是否正在睡觉：短按播放醒来动画；拖动则保持
            # 睡眠姿态，连角色和沙发一起平移。
            self._woke_on_press = self._sleep_mode
            if self._motion_state in ("drop", "tap"):
                self.motion_timer.stop()
                self._motion_state = ""
                self._dizzy_pending = False
                self._show_default()
                self.idle_timer.start()
            if self._woke_on_press:
                self._dizzy_pending = False
            self.dragging = True
            self.drag_moved = False
            self.drag_offset = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            self._press_pos = event.globalPosition().toPoint()
            local_center = max(1.0, self.width() / 2.0)
            self._tap_direction = max(
                -1.0,
                min(1.0, (event.position().x() - local_center) / local_center),
            )
            self._drag_last_global = self._press_pos
            self._drag_last_time = time.perf_counter()
            if (
                not self._woke_on_press
                and not self._edge_side
                and not self.anim_name
                and not self._expression_name
                and not self._motion_state
            ):
                self.long_press_timer.start(
                    int(self.settings["advanced"]["long_press_ms"])
                )
                self.easter_hold_timer.start(EASTER_PET_HOLD_MS)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging and event.buttons() & Qt.MouseButton.LeftButton:
            global_position = event.globalPosition().toPoint()
            new_position = (
                global_position
                - self.drag_offset
            )
            self.move(new_position)
            # 气泡跟随宠物移动
            if self.bubble.isVisible():
                self._position_bubble()
            # 移动了超过阈值就视为拖拽，而不是点击
            if (global_position - self._press_pos).manhattanLength() > 5:
                self.long_press_timer.stop()
                self.easter_hold_timer.stop()
                if not self.drag_moved:
                    if not self._woke_on_press:
                        self._begin_drag_motion()
                self.drag_moved = True

            now = time.perf_counter()
            elapsed = max(now - self._drag_last_time, 0.001)
            delta_x = global_position.x() - self._drag_last_global.x()
            velocity_x = delta_x / elapsed
            self._update_shake_detection(velocity_x, delta_x, now)
            if velocity_x >= DRAG_DIRECTION_TRIGGER_SPEED:
                # 向右拖时身体惯性滞后，使用左摆图。
                self._drag_hang_pose = "left"
                self._drag_target_rotation = DRAG_LOCK_ROTATION
            elif velocity_x <= -DRAG_DIRECTION_TRIGGER_SPEED:
                self._drag_hang_pose = "right"
                self._drag_target_rotation = -DRAG_LOCK_ROTATION
            self._drag_last_global = global_position
            self._drag_last_time = now
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._easter_active:
                event.accept()
                return
            self.long_press_timer.stop()
            self.easter_hold_timer.stop()
            was_click = self.dragging and not self.drag_moved
            was_long_press = self._long_press_triggered
            self.dragging = False

            if was_click:
                if self._woke_on_press:
                    # 延迟到系统双击判定结束：若随后收到双击事件，计时器
                    # 会被取消并改为醒来；否则才执行 nuzzle 和梦话。
                    interval = QApplication.instance().doubleClickInterval()
                    self.sleep_click_timer.start(interval + 20)
                elif was_long_press:
                    # 长按已经触发摸头反馈，松开时不再补一次普通点击。
                    self._release_petting_hold()
                else:
                    self._on_click()
            elif self.drag_moved:
                if self._woke_on_press:
                    # 睡着时只移动沙发，不进入悬挂、贴边或落地动作。
                    self._settle()
                elif self._dizzy_pending:
                    # 摇晃优先于贴边：先完成落地反馈，再进入头晕状态。
                    self._begin_drop_motion()
                elif not self._try_enter_edge_cling(
                    event.globalPosition().toPoint()
                ):
                    self._begin_drop_motion()
            self._drag_hang_pose = "center"
            self._woke_on_press = False
            self._long_press_triggered = False
            event.accept()

    def mouseDoubleClickEvent(self, event):
        self.long_press_timer.stop()
        self.easter_hold_timer.stop()
        if self._easter_active:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._sleep_mode:
            self.sleep_click_timer.stop()
            self.dragging = False
            self.drag_moved = False
            self._woke_on_press = False
            self._mark_activity()
            self._play_wakeup()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and not self._edge_side:
            self.dragging = False
            self.drag_moved = False
            self._long_press_triggered = False
            self.motion_timer.stop()
            self._motion_state = ""
            self._mark_activity()
            # Qt 会把快速点击中的第二次识别为双击事件；在这里补记一次，
            # 保证十次真实按下就是十次，而不会被按双击对折统计。
            if self._register_easter_click():
                event.accept()
                return
            self.show_expression("surprised")
            self.say_category("surprised")
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _trigger_petted(self):
        """清醒状态下稳定长按，视为轻轻摸头。"""
        if (
            not self.dragging
            or self.drag_moved
            or self._sleep_mode
            or self._edge_side
        ):
            return
        self._long_press_triggered = True
        self.show_expression("petted")
        self.say_category("petted")

    def _release_petting_hold(self):
        """松开鼠标后才结束持续摸头，兼容尚未播完的入场眨眼。"""
        if self._expression_name == "petted":
            self._begin_expression_exit()
            return
        if self.anim_name == "expression_enter":
            self.anim_timer.stop()
            self.anim_frames = []
            self.anim_name = ""
            self.anim_looping = False
            self.anim_on_finish = None
            self.anim_intervals = None
            self._clear_expression(render=False)
            self._show_default()
            self.idle_timer.start()

    def _play_sleep_touch(self):
        """睡着时被轻点：保持睡眠，蹭蹭枕头并说一句梦话。"""
        if not self._sleep_mode:
            return
        self.nuzzle_timer.stop()
        self.play_frames(
            NUZZLE_FRAMES,
            name="nuzzle",
            looping=False,
            on_finish=self._settle,
        )
        self.say_category("dream")

    def _on_click(self):
        """单击宠物：轻微按压回弹；连续打扰后切换为不耐烦。"""
        if self._edge_side:
            self.say_category("edge")
            return
        if self._register_easter_click():
            return
        if self._register_disturbance():
            return
        self._begin_click_motion()
        self.say_category("click")

    # =================================================================
    # 右键菜单
    # =================================================================
    def contextMenuEvent(self, event):
        self.sleep_click_timer.stop()
        self.long_press_timer.stop()
        self._mark_activity()
        menu = QMenu(self)

        house_action = menu.addAction("回家")
        menu.addSeparator()

        # 行走动画开关（播放中则显示"停止行走"）
        self._walk_action = menu.addAction(
            "停止行走" if self.is_walking() else "行走动画"
        )
        sleep_action = menu.addAction(
            "停止睡觉" if self.is_sleeping() else "睡觉动画"
        )
        expression_menu = menu.addMenu("预览表情")
        curious_action = expression_menu.addAction("好奇")
        petted_action = expression_menu.addAction("被摸头开心")
        surprised_action = expression_menu.addAction("惊讶")
        hurt_action = expression_menu.addAction("委屈")
        bored_action = expression_menu.addAction("无聊")
        annoyed_action = expression_menu.addAction("有点不满")
        sleepy_action = expression_menu.addAction("困倦")
        menu.addSeparator()

        inbox_menu = menu.addMenu("收纳箱")
        inbox_action = inbox_menu.addAction("打开全部收纳内容")
        notes_action = inbox_menu.addAction("打开桌宠便签")
        links_action = inbox_menu.addAction("打开链接收藏")
        images_action = inbox_menu.addAction("打开图片收藏")
        clipboard_action = menu.addAction("剪贴板历史（最近 5 条）")
        bubble_action = menu.addAction("说句话")
        settings_action = menu.addAction("设置…")
        menu.addSeparator()
        quit_action = menu.addAction("退出桌宠")

        selected = menu.exec(event.globalPos())

        if selected is None:
            return

        if selected == house_action:
            self.open_house()
        elif selected == self._walk_action:
            if self.is_walking():
                self._settle()
            else:
                self.play_frames(WALK_FRAMES, name="walk", looping=True)
        elif selected == sleep_action:
            if self.is_sleeping():
                # 右键“停止睡觉”与双击一致，走完整醒来动画。
                self._play_wakeup()
            else:
                # 开启睡觉：持久状态，点击/拖拽结束后仍保持睡觉
                self._sleep_mode = True
                self._settle()
        elif selected == curious_action:
            self.show_expression("curious")
        elif selected == petted_action:
            self.show_expression("petted")
        elif selected == surprised_action:
            self.show_expression("surprised")
        elif selected == hurt_action:
            self.show_expression("hurt")
        elif selected == bored_action:
            self._bored_manual_preview_until = time.perf_counter() + 5.0
            self.show_expression("bored")
        elif selected == annoyed_action:
            self.show_expression("annoyed")
        elif selected == sleepy_action:
            self.show_expression("sleepy")
        elif selected == inbox_action:
            self.open_inbox()
        elif selected == notes_action:
            self.open_notes()
        elif selected == links_action:
            self.open_links()
        elif selected == images_action:
            self.open_images()
        elif selected == clipboard_action:
            self.open_clipboard_history()
        elif selected == bubble_action:
            self.say_random()
        elif selected == settings_action:
            self.open_settings()
        elif selected == quit_action:
            QApplication.quit()


def _notify_existing_instance(server_name=SINGLE_INSTANCE_SERVER_NAME):
    """通知已运行的桌宠；连接成功时当前进程不再创建新窗口。"""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(350):
        socket.abort()
        return False
    socket.write(SINGLE_INSTANCE_MESSAGE)
    socket.flush()
    socket.waitForBytesWritten(500)
    if not socket.waitForReadyRead(700):
        socket.abort()
        return False
    acknowledged = SINGLE_INSTANCE_ACK in bytes(socket.readAll())
    socket.disconnectFromServer()
    return acknowledged


def _claim_single_instance(server_name=SINGLE_INSTANCE_SERVER_NAME):
    """抢占单实例通道，并兼顾上次异常退出留下的失效地址。"""
    if _notify_existing_instance(server_name):
        return None

    server = QLocalServer()
    if server.listen(server_name):
        return server

    # 可能是两个启动操作几乎同时发生：先再通知一次，避免误删
    # 刚由另一个进程创建的有效通道。
    if _notify_existing_instance(server_name):
        return None

    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    if server.listen(server_name):
        return server

    # 最后处理一次极小概率的并发竞争。
    if _notify_existing_instance(server_name):
        return None
    raise RuntimeError("无法建立桌宠单实例通道")


def _bind_instance_notifications(server, pet):
    """让后续启动请求转化为现有桌宠的一句反馈。"""
    clients = set()

    def process_client(client):
        if client.property("desktopPetHandled"):
            return
        payload = bytes(client.readAll())
        if not payload:
            return
        if SINGLE_INSTANCE_MESSAGE in payload:
            client.setProperty("desktopPetHandled", True)
            pet.say("一个我就可以啦！", "single_instance", priority=5)
            pet.show()
            pet.raise_()
            client.write(SINGLE_INSTANCE_ACK)
            client.flush()
            # 由通知方收到确认后主动断开，确保确认数据不会因过早关闭丢失。
            return
        client.disconnectFromServer()

    def accept_connections():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            clients.add(client)
            client.readyRead.connect(
                lambda current=client: process_client(current)
            )

            def discard_client(current=client):
                # 第二个进程发完消息便会立即退出；即使未触发 readyRead，
                # 断开时缓冲区中的内容仍要读取，不能把通知一起丢掉。
                process_client(current)
                clients.discard(current)
                current.deleteLater()

            client.disconnected.connect(discard_client)
            # 数据可能在连接信号绑定前已经到达。
            process_client(client)
            QTimer.singleShot(0, lambda current=client: process_client(current))

    server.newConnection.connect(accept_connections)
    accept_connections()
    # 明确交由桌宠持有，保证整个运行期间通道与连接都不会被回收。
    pet._single_instance_server = server
    pet._single_instance_clients = clients


def main():
    if "--build-exe" in sys.argv[1:]:
        return build_executable()

    app = QApplication(sys.argv)
    instance_server = _claim_single_instance()
    if instance_server is None:
        return 0

    pet = DesktopPet()
    _bind_instance_notifications(instance_server, pet)
    pet.show()
    exit_code = app.exec()
    instance_server.close()
    QLocalServer.removeServer(SINGLE_INSTANCE_SERVER_NAME)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
