import math
import random
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QPoint, QRect, QRectF, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
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

# =====================================================================
# 素材配置
# 想改文件名/加表情，只需修改这里
# =====================================================================
MASTER_CHARACTER_IMAGE = "pet.png"                          # 锁定的角色母版
DEFAULT_IMAGE = MASTER_CHARACTER_IMAGE                       # 默认待机图

BASE_DIR = Path(__file__).parent          # 素材目录


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

PET_HEIGHT = 350            # 统一缩放高度
HAPPY_INTERVAL = 40         # 原帧和内存过渡帧交替播放，约 25FPS
WALK_INTERVAL = 120         # 行走动画每帧间隔毫秒（约 0.6s 播完 5 帧）
IDLE_INTERVAL = 33          # 待机渲染约 30 FPS；仅对默认图生效
MOTION_INTERVAL = 20        # 拖拽/落地姿态约 50 FPS
EXPRESSION_TRANSITION_INTERVAL = 45  # 借现有眨眼帧遮住表情切换
POST_EXPRESSION_BLINK_PAUSE = 3200    # 表情退出后先保持睁眼，避免连续眨眼
EDGE_SNAP_DISTANCE = 24     # 基本碰到屏幕左右边缘时才吸附
STAGE_PADDING = 12          # 给呼吸、轻摆和脚下阴影预留的透明边缘
SHADOW_IMAGE = "assets/character/layers/ground_shadow.png"
BLINK_OPEN_IMAGE = "assets/character/expressions/pet_blink_open_v1.png"
BLINK_HALF_IMAGE = "assets/character/expressions/pet_blink_half_v1.png"
BLINK_ALMOST_IMAGE = "assets/character/expressions/pet_blink_almost_v1.png"
BLINK_CLOSED_IMAGE = "assets/character/expressions/pet_blink_closed_v1.png"
EXPRESSION_IMAGES = {
    "curious": "assets/character/expressions/pet_expression_curious_v1.png",
    "annoyed": "assets/character/expressions/pet_expression_annoyed_v1.png",
    "sleepy": "assets/character/expressions/pet_expression_sleepy_v1.png",
}
EXPRESSION_DURATIONS = {
    "curious": 1800,
    "annoyed": 1900,
    "sleepy": 2400,
}
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

    MAX_TEXT_WIDTH = 220
    MIN_WIDTH = 150
    HORIZONTAL_PADDING = 24
    TOP_PADDING = 14
    TAIL_HEIGHT = 18

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

    def set_message(self, text):
        self._text = text
        metrics = QFontMetrics(self._font)
        single_line_width = metrics.horizontalAdvance(text)
        text_width = min(
            self.MAX_TEXT_WIDTH,
            max(106, single_line_width),
        )
        final_bounds = metrics.boundingRect(
            QRect(0, 0, text_width, 1000),
            self.text_flags,
            text,
        )
        width = max(
            self.MIN_WIDTH,
            final_bounds.width() + self.HORIZONTAL_PADDING * 2 + 14,
        )
        height = max(
            66,
            final_bounds.height() + self.TOP_PADDING * 2 + self.TAIL_HEIGHT,
        )
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
            self.TOP_PADDING - 2,
            -self.HORIZONTAL_PADDING,
            -(self.TOP_PADDING - 2),
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

        # -------------------------
        # 1. 窗口设置
        # -------------------------
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint      # 无标题栏边框
            | Qt.WindowType.WindowStaysOnTopHint   # 始终置顶
            | Qt.WindowType.Tool                   # 不占任务栏
        )
        self.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground,
            True
        )

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

        # -------------------------
        # 3.2 可组合表情（目前从右键菜单手动预览）
        # -------------------------
        self._expression_name = ""
        self.expression_timer = QTimer(self)
        self.expression_timer.setSingleShot(True)
        self.expression_timer.timeout.connect(self._begin_expression_exit)

        # -------------------------
        # 4. 说话气泡
        # -------------------------
        self.bubble = SpeechBubble()
        self.bubble_timer = QTimer(self)
        self.bubble_timer.setSingleShot(True)
        self.bubble_timer.timeout.connect(self.bubble.hide)

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
        self._drag_last_global = QPoint()
        self._drag_last_time = time.perf_counter()
        self._drop_started_at = 0.0
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
    def _load_all_images(self):
        """加载全部素材，统一缩放到 PET_HEIGHT。缺失的图片自动跳过。"""
        self._idle_sources = {}
        idle_names = {
            BLINK_OPEN_IMAGE,
            BLINK_HALF_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_CLOSED_IMAGE,
            *EXPRESSION_IMAGES.values(),
        }
        names = [
            DEFAULT_IMAGE,
            BLINK_OPEN_IMAGE,
            BLINK_HALF_IMAGE,
            BLINK_ALMOST_IMAGE,
            BLINK_CLOSED_IMAGE,
        ] + list(EXPRESSION_IMAGES.values()) + HAPPY_FRAMES + WALK_FRAMES
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
                PET_HEIGHT,
                Qt.TransformationMode.SmoothTransformation
            )

        if DEFAULT_IMAGE not in self._images:
            raise FileNotFoundError(
                f"没有找到人物图片：{self.base_dir / DEFAULT_IMAGE}"
            )

        shadow_path = self.base_dir / SHADOW_IMAGE
        self._ground_shadow = QPixmap(str(shadow_path))
        if not self._ground_shadow.isNull():
            self._ground_shadow = self._ground_shadow.scaledToHeight(
                PET_HEIGHT,
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
        self._stage_height = PET_HEIGHT + STAGE_PADDING * 2
        self.label.setGeometry(0, 0, self._stage_width, self._stage_height)
        self.setFixedSize(self._stage_width, self._stage_height)

    def _next_blink_start(self):
        """返回下一次眨眼的开始时间，间隔略随机才不会像计时器。"""
        return self._idle_elapsed_ms + random.randint(4500, 8000)

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
        target_height=PET_HEIGHT,
        draw_shadow=True,
        supersample=1,
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
        fit_scale = target_height / pixmap.height() if fit_height else 1.0
        painter.scale(fit_scale * scale_x, fit_scale * scale_y)
        painter.translate(-pixmap.width() / 2, -pixmap.height())
        painter.drawPixmap(0, 0, pixmap)
        painter.restore()
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

        self._render_to_stage(
            self._idle_sources[frame],
            scale_x=1.0 - breath * 0.0018,
            scale_y=1.0 + breath * 0.006,
            rotation=sway * 0.22,
            x_offset=sway * 0.7,
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
            target_height = PET_HEIGHT
            contact_x = 0.5
        else:
            target_height = EDGE_TARGET_HEIGHT[self._edge_side]
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
        self._render_to_stage(pixmap)

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
        """只用现有睁眼图绘制悬空或落地姿态。"""
        self._render_to_stage(
            self._idle_sources[BLINK_OPEN_IMAGE],
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
        self._drag_rotation = 0.0
        self._drag_target_rotation = 0.0
        self.motion_timer.start()
        self._render_drag_pose()

    def _begin_drop_motion(self):
        """从悬空姿态进入短促的压缩、回弹和稳定过程。"""
        self._motion_state = "drop"
        self._drop_started_at = time.perf_counter()
        self.motion_timer.start()

    @staticmethod
    def _ease_out(value):
        value = max(0.0, min(1.0, value))
        return 1.0 - (1.0 - value) ** 3

    def _on_motion_tick(self):
        if self._motion_state == "drag":
            self._drag_rotation += (
                self._drag_target_rotation - self._drag_rotation
            ) * 0.30
            self._drag_target_rotation *= 0.82
            self._render_drag_pose(rotation=self._drag_rotation)
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
            self.motion_timer.stop()
            self._motion_state = ""
            self._drag_rotation = 0.0
            self._drag_target_rotation = 0.0
            self._blink_start_ms = self._next_blink_start()
            self._show_default()
            self.idle_timer.start()

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

        # 按动画类型设置播放间隔（开心动画放慢）
        if name == "happy":
            self.anim_timer.setInterval(HAPPY_INTERVAL)
        elif name == "walk":
            self.anim_timer.setInterval(WALK_INTERVAL)
        elif name.startswith("expression_"):
            self.anim_timer.setInterval(EXPRESSION_TRANSITION_INTERVAL)

        self._show_image(usable[0])
        self.anim_timer.start()

    def stop_animation(self):
        """停止动画，回到默认图。"""
        self.anim_timer.stop()
        self.anim_frames = []
        self.anim_name = ""
        self.anim_looping = False
        self.anim_on_finish = None
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
                # 播完：先取出回调，再停止，最后执行回调
                callback = self.anim_on_finish
                self.stop_animation()
                if callback:
                    callback()
                return
        self._show_image(self.anim_frames[self.anim_index])

    def is_walking(self):
        return self.anim_name == "walk"

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

    def say(self, text):
        """在宠物上方弹出说话气泡。"""
        self.bubble.set_message(text)

        self._position_bubble()
        self.bubble.show()
        self.bubble.raise_()
        self.bubble_timer.start(3000)   # 3 秒后自动消失

    def say_random(self):
        self.say(random.choice(BUBBLE_TEXTS))

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
            on_finish=self._pause_blink_after_expression,
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
    # 鼠标事件
    # =================================================================
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._motion_state == "drop":
                self.motion_timer.stop()
                self._motion_state = ""
                self._show_default()
                self.idle_timer.start()
            self.dragging = True
            self.drag_moved = False
            self.drag_offset = (
                event.globalPosition().toPoint()
                - self.frameGeometry().topLeft()
            )
            self._press_pos = event.globalPosition().toPoint()
            self._drag_last_global = self._press_pos
            self._drag_last_time = time.perf_counter()
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
                if not self.drag_moved:
                    self._begin_drag_motion()
                self.drag_moved = True

            now = time.perf_counter()
            elapsed = max(now - self._drag_last_time, 0.001)
            velocity_x = (global_position.x() - self._drag_last_global.x()) / elapsed
            self._drag_target_rotation = max(-3.8, min(3.8, velocity_x / 420.0))
            self._drag_last_global = global_position
            self._drag_last_time = now
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            was_click = self.dragging and not self.drag_moved
            self.dragging = False

            if was_click:
                self._on_click()
            elif self.drag_moved:
                if not self._try_enter_edge_cling(
                    event.globalPosition().toPoint()
                ):
                    self._begin_drop_motion()
            event.accept()

    def _on_click(self):
        """单击宠物：播放开心动画 + 随机台词。"""
        if self._edge_side:
            self.say_random()
            return
        self.play_frames(
            HAPPY_FRAMES,
            name="happy",
            looping=False,
            on_finish=self.say_random,
        )

    # =================================================================
    # 右键菜单
    # =================================================================
    def contextMenuEvent(self, event):
        menu = QMenu(self)

        # 行走动画开关（播放中则显示"停止行走"）
        self._walk_action = menu.addAction(
            "停止行走" if self.is_walking() else "行走动画"
        )
        expression_menu = menu.addMenu("预览表情")
        curious_action = expression_menu.addAction("好奇")
        annoyed_action = expression_menu.addAction("有点不满")
        sleepy_action = expression_menu.addAction("困倦")
        menu.addSeparator()

        bubble_action = menu.addAction("说句话")
        quit_action = menu.addAction("退出桌宠")

        selected = menu.exec(event.globalPos())

        if selected is None:
            return

        if selected == self._walk_action:
            if self.is_walking():
                self.stop_animation()
            else:
                self.play_frames(WALK_FRAMES, name="walk", looping=True)
        elif selected == curious_action:
            self.show_expression("curious")
        elif selected == annoyed_action:
            self.show_expression("annoyed")
        elif selected == sleepy_action:
            self.show_expression("sleepy")
        elif selected == bubble_action:
            self.say_random()
        elif selected == quit_action:
            QApplication.quit()


def main():
    app = QApplication(sys.argv)
    pet = DesktopPet()
    pet.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
