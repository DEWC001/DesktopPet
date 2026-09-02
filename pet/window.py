"""透明置顶窗口 + 拖拽 + 点击反馈 + 多帧精灵图动画。"""
import datetime
import logging
import math
import os
import random
import time

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from . import config
from . import session_monitor
from .animation import jump_animation
from .brain import PetBrain
from .notification_listener import NotificationWatcher
from .im_unread_watcher import ImUnreadWatcher
from .speech_bubble import SpeechBubble

logger = logging.getLogger("pet")

FRAME_NAMES = ["idle", "blink", "walk_a", "walk_b", "jump", "sleep"]
# 扩展动作帧（皮肤目录里存在则加载，不存在则回退 idle）
EXTRA_FRAME_NAMES = ["drink", "think", "laugh"]

# 呼吸缩放预生成级别（加密到 21 级，缩放过渡平滑）
BREATH_SCALES = [round(0.96 + 0.004 * i, 4) for i in range(21)]


class PetWindow(QWidget):
    DISPLAY_H = 260  # 精灵帧统一高度（px）

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # 摸头互动需要无按键时的鼠标移动事件
        self.setMouseTracking(True)

        self.scale = float(config.get("scale"))

        # 加载所有精灵帧（基础 + 扩展），缺失基础帧回退 idle，缺失扩展帧跳过
        self.frames: dict[str, QPixmap] = {}
        idle = self._load_all_frames()
        self._rebuild_breath_cache()

        self._margin = 8
        self.setFixedSize(idle.width() + self._margin * 2, idle.height() + self._margin * 2)
        self.label = QLabel(self)
        self.label.setGeometry(self._margin, self._margin, idle.width(), idle.height())
        # 图片标签只负责显示：鼠标事件一律透传给窗口本体处理，
        # 否则 move 事件会被标签吃掉，摸头互动收不到（press 靠 ignore 上传是侥幸）
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # 运行时状态
        self._blinking = False
        self._jumping = False
        self._phase = 0.0
        self._walk_dir = 1
        self._walk_frame = "walk_a"
        self._drag = False
        self._moved = False
        self._press_global = QPoint()
        self._win_origin = QPoint()
        self._remind_anim = None
        # 临时帧覆盖（笑/喝水等短暂动作）：_override_frame 为帧名，_override_until 为过期时间戳
        self._override_frame = None
        self._override_until = 0
        # 番茄钟阶段表情：work → think，break → laugh，由 _on_pomodoro_tick 维护
        self._pomodoro_frame = None
        # 双击抑制：Qt 双击序列为 press→release→dblclick→release，
        # 第二次 release 会再触发一次单击逻辑，需标记抑制，否则双击会多跳一次
        self._suppress_click = False
        # 贴边隐藏：normal → hiding → hidden → showing → normal
        # 静止 N 秒后滑到最近边缘只露一角；隐藏后只有手动点击或提醒才滑回
        #（1.7.0 起不再因鼠标靠近自动弹出）
        self._edge_state = "normal"
        self._last_move_time = time.time()
        self._last_user_pos = self.pos()
        self._edge_hide_idle_timer: QTimer = None
        self._edge_anim = None
        # 睡眠靠边（1.7.0）：入睡时若处于普通位置，滑到最近屏幕边缘完整可见地睡；
        # _sleep_side 标记"睡着靠边"中，唤醒后睡在哪醒在哪（不回位，用户选择）
        self._sleep_side = False
        self._slide_anim = None
        # 上一个 brain 状态（_on_state 触发时 state 已是新值，靠它判断"刚睡醒"）
        self._prev_brain_state = None
        # 活跃度缓存（托盘改动后经 refresh_activity() 刷新）：逐帧散步步速/跳跃
        # 高度用它，避免每个 33ms tick 都去读 QSettings（registry 读取开销）
        self._activity = config.activity()
        # 动作台词冷却：{state: last_emit_time}，避免切换刷屏
        self._last_action_quote_at: dict[str, float] = {}
        # 离开感知（锁屏）：会话通知只在 HWND 创建后才能注册，放 showEvent 里做
        self._session_registered = False
        self._away = False
        self._away_since = None
        self._missed_custom: list[str] = []
        self.bubble = None
        self.tray = None
        # 呼吸/漂浮
        self.breath_timer = QTimer(self)
        self.breath_timer.setInterval(33)
        self.breath_timer.timeout.connect(self._on_breath)
        self.breath_timer.start()

        # 眨眼
        self.blink_timer = QTimer(self)
        self.blink_timer.setSingleShot(True)
        self.blink_timer.timeout.connect(self._on_blink_timer)

        # 走动：窗口水平移动
        self.walk_timer = QTimer(self)
        self.walk_timer.setInterval(33)
        self.walk_timer.timeout.connect(self._on_walk)

        # 走动：帧切换（walk_a <-> walk_b）
        self.walk_frame_timer = QTimer(self)
        self.walk_frame_timer.setInterval(200)
        self.walk_frame_timer.timeout.connect(self._toggle_walk_frame)

        # 开心连跳
        self.jump_loop_timer = QTimer(self)
        self.jump_loop_timer.setInterval(850)
        self.jump_loop_timer.timeout.connect(self._do_jump)

        # 单击/双击判定
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(250)
        self._click_timer.timeout.connect(self._do_single_click)

        # 状态机
        self.brain = PetBrain(self)
        self.brain.state_changed.connect(self._on_state)
        self.brain.start()

        QTimer.singleShot(0, self._schedule_blink)
        self._restore_pos()
        self.apply_topmost(bool(config.get("always_on_top")))

        # 喝水提醒
        self.bubble = SpeechBubble()
        self.drink_timer = QTimer(self)
        self.drink_timer.setSingleShot(True)
        self.drink_timer.timeout.connect(self.remind_drink)
        self._setup_drink_timer()

        # 整点报时
        self.hourly_timer = QTimer(self)
        self.hourly_timer.setSingleShot(True)
        self.hourly_timer.timeout.connect(self.remind_hourly)
        self._setup_hourly_timer()

        # 久坐休息
        self.sit_timer = QTimer(self)
        self.sit_timer.setSingleShot(True)
        self.sit_timer.timeout.connect(self.remind_sit)
        self._setup_sit_timer()

        # 自定义提醒：轮询定时器 + 当日已触发去重（跨天自动清空）
        # 必须早于 _setup_custom_reminders() 调用
        self.custom_timer = None
        self._fired_custom: set = set()
        self._fired_custom_day = ""

        # 下班倒计时
        self.offwork_timer = QTimer(self)
        self.offwork_timer.setSingleShot(True)
        self.offwork_timer.timeout.connect(self.remind_offwork)
        self._setup_offwork_timer()

        # 自定义提醒事项（吃药 / 周会 / 一次性提醒）
        self._setup_custom_reminders()

        # 贴边隐藏（静止超时自动滑到边缘只露一角）
        self._setup_edge_hide_timer()

        # 气泡统一 hide 管理（避免多个定时器互相干扰导致一闪而过）
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self.bubble.hide)

        # 飞书新消息监听（轮询 Windows 通知中心，识别飞书来源）
        self.notifier = NotificationWatcher(self)
        self.notifier.message_received.connect(self._on_feishu_message)

        # 灵犀/QQ/微信/企微 未读监听（任务栏「请求注意」状态，多应用）
        self.im_watcher = ImUnreadWatcher(self)
        self.im_watcher.unread_changed.connect(self._on_im_unread_changed)

        # 未读超时强提醒：app -> 单次 QTimer（持续未读超时后跑到屏幕中心）
        self._unread_timers = {}

        # 番茄钟阶段切换：1s 周期轮询；阶段结束自动切下一阶段并弹气泡
        # 番茄钟启动/停止由托盘菜单控制，这里只做"驱赶阶段切换"
        self._pomodoro_timer = QTimer(self)
        self._pomodoro_timer.setInterval(1000)
        self._pomodoro_timer.timeout.connect(self._on_pomodoro_tick)
        self._pomodoro_timer.start()

    # ---------- 素材 ----------
    def _load_all_frames(self) -> QPixmap:
        """加载当前皮肤的全部基础+扩展帧；缺失基础帧回退 idle，缺失扩展帧跳过。
        返回 idle 帧（用于尺寸/位置参考）。"""
        self.frames: dict[str, QPixmap] = {}
        for name in FRAME_NAMES:
            pix = self._load(f"{name}.png")
            self.frames[name] = self._fit(pix) if not pix.isNull() else None
        if self.frames["idle"] is None:
            idle = QPixmap(120, 120)
            idle.fill(Qt.GlobalColor.transparent)
            self.frames["idle"] = idle
        idle = self.frames["idle"]
        for name in FRAME_NAMES:
            if self.frames[name] is None:
                self.frames[name] = idle
        # 扩展动作帧（存在则用，不存在时跳过，_current_frame_name 会回退 idle）
        for name in EXTRA_FRAME_NAMES:
            pix = self._load(f"{name}.png")
            if not pix.isNull():
                self.frames[name] = self._fit(pix)
        return idle

    def _load(self, name: str) -> QPixmap:
        skin = config.current_skin()
        if skin == "default":
            path = config.resource_path("skins", name)
        else:
            path = config.resource_path("skins", skin, name)
        if os.path.exists(path):
            return QPixmap(path)
        return QPixmap()

    def set_skin(self, name: str) -> None:
        """切换皮肤：保存配置、重新加载所有帧、重建呼吸缓存、保持窗口中心。"""
        if name not in config.list_skins():
            return  # 非法皮肤名直接忽略
        if name == config.current_skin():
            return  # 已是当前皮肤
        config.set_value("skin", name)
        idle = self._load_all_frames()
        self._rebuild_breath_cache()
        # 保持窗口中心调整尺寸
        center = self.geometry().center()
        self.setFixedSize(idle.width() + self._margin * 2, idle.height() + self._margin * 2)
        self.label.setGeometry(self._margin, self._margin, idle.width(), idle.height())
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        # 同步托盘图标为当前皮肤的 idle
        if self.tray is not None:
            self.tray.refresh_icon()

    def _fit(self, pix: QPixmap) -> QPixmap:
        if pix.isNull():
            return pix
        target_h = int(self.DISPLAY_H * self.scale)
        if pix.height() > target_h:
            pix = pix.scaledToHeight(
                target_h, Qt.TransformationMode.SmoothTransformation
            )
        return pix

    def set_scale(self, scale: float) -> None:
        """切换宠物大小：重新加载帧、保持窗口中心不变调整尺寸。"""
        self.scale = max(0.3, min(2.0, float(scale)))
        config.set_value("scale", self.scale)
        idle = self._load_all_frames()
        self._rebuild_breath_cache()
        center = self.geometry().center()
        self.setFixedSize(idle.width() + self._margin * 2, idle.height() + self._margin * 2)
        self.label.setGeometry(self._margin, self._margin, idle.width(), idle.height())
        self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
        self._save_pos()

    def _rebuild_breath_cache(self) -> None:
        """预生成各帧的缩放级别缓存，供呼吸动画直接取用。
        覆盖所有已加载帧（含扩展帧 drink/think/laugh），避免 _current_frame_name
        返回扩展帧时 KeyError。"""
        self._breath_cache = {}
        for name, base in self.frames.items():
            if base is None or base.isNull():
                continue
            self._breath_cache[name] = [
                base.scaled(
                    max(1, int(base.width() * s)),
                    max(1, int(base.height() * s)),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                for s in BREATH_SCALES
            ]

    def _current_frame_name(self) -> str:
        # 1. 临时帧覆盖（如双击 laugh、喝水 drink），过期自动失效
        if self._override_frame and self._override_frame in self.frames:
            return self._override_frame
        # 2. 番茄钟阶段表情：work → think（专注），break → laugh（开心）
        # _pomodoro_frame 字段本身就是意图标记（由 start_pomodoro / stop_pomodoro 维护），
        # 不需要再查 pomodoro_active()。这样测试时只设字段也能立刻生效
        if self._pomodoro_frame and self._pomodoro_frame in self.frames:
            return self._pomodoro_frame
        # 3. 状态映射
        if self._jumping or self.brain.state == PetBrain.JUMP:
            return "jump"
        if self.brain.state == PetBrain.SLEEP:
            return "sleep"
        if self.brain.state in (PetBrain.WALK, PetBrain.WANDER):
            return self._walk_frame
        if self.brain.state == PetBrain.CHAT and "think" in self.frames:
            return "think"  # 自语时用 think 帧（摸头/害羞感）
        if self._blinking:
            return "blink"
        return "idle"

    # ---------- 顶置 ----------
    def apply_topmost(self, on: bool) -> None:
        flags = self.windowFlags()
        if on:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    # ---------- 动画 ----------
    def _on_breath(self) -> None:
        # 临时帧覆盖过期清除
        if self._override_until and time.time() * 1000 > self._override_until:
            self._override_frame = None
            self._override_until = 0
        self._phase += 0.1
        if self.brain.state == PetBrain.SLEEP:
            amp, sf = 1.0, 0.01
        elif self._jumping:
            amp, sf = 0.0, 0.0
        else:
            amp, sf = 2.5, 0.025

        scale = 1.0 + sf * math.sin(self._phase)
        idx = min(range(len(BREATH_SCALES)), key=lambda i: abs(BREATH_SCALES[i] - scale))
        name = self._current_frame_name()
        px = self._breath_cache[name][idx]
        self.label.setPixmap(px)
        x = (self.width() - px.width()) // 2
        y = self._margin + int(amp * math.sin(self._phase * 0.8))
        self.label.setGeometry(x, y, px.width(), px.height())

    def _schedule_blink(self) -> None:
        self.blink_timer.start(random.randint(2500, 6000))

    def _on_blink_timer(self) -> None:
        if self.brain.state == PetBrain.IDLE:
            self._blinking = True
            QTimer.singleShot(140, self._end_blink)
        self._schedule_blink()

    def _end_blink(self) -> None:
        self._blinking = False

    def _toggle_walk_frame(self) -> None:
        self._walk_frame = "walk_b" if self._walk_frame == "walk_a" else "walk_a"

    def _walk_step(self) -> int:
        """散步步速（px/帧）：低活跃 1px，默认 50 活跃 2px，高活跃 3px。"""
        v = PetBrain._scale(self._activity, 1.0, 2.0, 3.0)
        if v < 1.5:
            return 1
        return 2 if v < 2.5 else 3

    def _on_walk(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        step = self._walk_step()
        x = self.x() + self._walk_dir * step
        if x < screen.left() or x + self.width() > screen.right():
            self._walk_dir *= -1
            x = self.x() + self._walk_dir * step
        self.move(x, self.y())
        self._mark_movement()

    def _on_state(self, s: str) -> None:
        self.walk_timer.stop()
        self.walk_frame_timer.stop()
        self.jump_loop_timer.stop()

        # _on_state 触发时 brain.state 已经是新值，用 _prev_brain_state 判断"刚睡醒"
        old = self._prev_brain_state
        self._prev_brain_state = s
        hidden = self._edge_state == "hidden"

        if s == PetBrain.SLEEP:
            # 需求3：睡着滑到最近屏幕边缘完整可见（已处于收缝则保持原状）
            self._start_sleep_side()
        elif old == PetBrain.SLEEP:
            # 刚睡醒：睡在哪醒在哪（1.7.0 用户选择不回位）；刷新空闲计时，
            # 否则醒来瞬间又因超时被贴边收缝
            self._sleep_side = False
            if self._slide_anim is not None:
                self._slide_anim.stop()
                self._slide_anim = None
            self._mark_movement()

        if s in (PetBrain.WALK, PetBrain.JUMP, PetBrain.WANDER) and self._edge_state == "hiding":
            # 收缝动画中大脑决定要活动：取消收缝原地活动，别让滑向边缘的
            # 动画继续把窗口拽走（walk 的 move 与收缝动画会互相拉扯）
            if self._edge_anim is not None:
                self._edge_anim.stop()
                self._edge_anim = None
            self._edge_state = "normal"

        if s == PetBrain.WALK:
            # 收缝（hidden）期间不迈步：等点击/提醒唤出后再走，否则宠物会
            # 自己从隐藏缝里走出来，违背"隐藏后不自动出来"
            if not hidden:
                self._walk_dir = random.choice([-1, 1])
                self.walk_timer.start()
                self.walk_frame_timer.start()
        elif s == PetBrain.JUMP:
            if not hidden:
                self._do_jump()
                self.jump_loop_timer.start()
        elif s == PetBrain.CHAT:
            if not hidden:
                self._chat()
        elif s == PetBrain.WANDER:
            if not hidden:
                self._wander()

        self._blinking = s == PetBrain.SLEEP
        # 切换动作时按冷却弹台词气泡（收缝里不弹，避免气泡从缝里冒出来）
        if not hidden:
            self._emit_action_quote(s)

    def _emit_action_quote(self, state: str) -> None:
        """状态切换时按冷却弹动作台词（避免频繁刷屏）。"""
        msgs = config.get_action_quotes(state)
        if not msgs:
            return
        now = time.time()
        last = self._last_action_quote_at.get(state, 0)
        if now - last < config.ACTION_QUOTE_COOLDOWN:
            return
        self._last_action_quote_at[state] = now
        if self.bubble is not None and self.bubble.isVisible():
            return  # 气泡正显示，不覆盖
        self._show_bubble(random.choice(msgs), 4000)

    def _jump_height(self) -> int:
        """自发跳跃高度按活跃度缩放：低活跃轻轻蹦（14px），高活跃蹦更高（44px）。"""
        return int(round(PetBrain._scale(self._activity, 14.0, 26.0, 44.0)))

    def _do_jump(self, dx=None, *, interactive: bool = False) -> None:
        if dx is None:
            dx = random.randint(-24, 24)
        # 自发跳跃随活跃度缩放；点击/双击这类用户互动保持固定高度，回应不打折
        height = 26 if interactive else self._jump_height()
        self._jumping = True
        anim = jump_animation(self, dx, height=height)
        anim.finished.connect(self._save_pos)
        anim.start()
        QTimer.singleShot(400, self._end_jump)

    def _chat(self) -> None:
        if self.bubble.isVisible():
            return  # 气泡正在显示（提醒中），不自言自语覆盖
        msg = random.choice(config.get_random_messages())
        self._show_bubble(msg, 8000)

    def _wander(self) -> None:
        self._mark_movement()
        screen = QApplication.primaryScreen().availableGeometry()
        lo = screen.left()
        hi = max(screen.left(), screen.right() - self.width())
        tx = random.randint(lo, hi)
        ylo = screen.top() + screen.height() // 3
        yhi = max(ylo, screen.bottom() - self.height())
        ty = random.randint(ylo, yhi)
        self.walk_frame_timer.start()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(900)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(tx, ty))
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.finished.connect(self.walk_frame_timer.stop)
        anim.finished.connect(self._save_pos)
        anim.start()

    def refresh_activity(self) -> None:
        """托盘调节活跃度后调用：刷新窗口侧缓存，并让状态机按新参数重新计时。"""
        self._activity = config.activity()
        self.brain.reschedule()

    # ---------- 拖拽 / 点击 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._press_global = e.globalPosition().toPoint()
            self._win_origin = self.pos()
            self._moved = False
            if self._edge_state == "hidden":
                # 需求2：收缝后手动唤出的唯一途径之一——点击露出的那条边
                self._begin_edge_show()
            elif self._sleep_side:
                # 用户按住睡着靠边的宠物：靠边契约作废，位置改由拖动接管
                self._sleep_side = False
                if self._slide_anim is not None:
                    self._slide_anim.stop()
                    self._slide_anim = None
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag:
            delta = e.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() > 4:
                self._moved = True
            if self._moved:
                self.move(self._win_origin + delta)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            was_click = not self._moved
            self._drag = False
            self._moved = False
            if self._suppress_click:
                # 双击序列的第二次 release：忽略，否则会额外触发一次单击跳
                self._suppress_click = False
                e.accept()
                return
            if was_click:
                self._on_click()
            else:
                self._save_pos()
                self._last_user_pos = self.pos()
                self._mark_movement()
                e.accept()

    def _on_click(self) -> None:
        self.brain.poke()
        self._click_timer.start()  # 延迟判断单击/双击
        self._mark_movement()

    def mouseDoubleClickEvent(self, e) -> None:
        self._click_timer.stop()
        self._suppress_click = True  # 抑制紧随其后的第二次 release
        self._do_double_click()
        e.accept()

    def contextMenuEvent(self, e) -> None:
        if self.tray is not None:
            self.tray.refresh_menu_checks()
            self.tray.menu.popup(e.globalPos())
            e.accept()
        else:
            super().contextMenuEvent(e)

    def _do_single_click(self) -> None:
        self._do_jump(interactive=True)
        if random.random() < 0.5:
            self._say(config.get_click_messages())

    def _do_double_click(self) -> None:
        """双击：跳 1 下 + 临时 laugh 帧（1.5 秒后恢复）。

        跳跃次数刻意保持为 1：连跳是「很兴奋」的表达，双击只是日常打招呼，
        连蹦 3 下显得过度亢奋；而且上一次还没落地就排队下一次，观感是抽搐
        而不是开心。更强的反馈靠表情（laugh 帧）+ 台词，不靠堆次数。

        1.6.0 起不再用延迟定时器排连跳（原 _schedule_jump / _cancel_pending_jumps
        整套机制已随之删除）——只有一次跳跃，就不需要「取消未触发的排队跳跃」了。
        """
        self._mark_movement()
        if "laugh" in self.frames:
            self._override_frame = "laugh"
            self._override_until = time.time() * 1000 + 1500
        self._do_jump(interactive=True)
        self._say(config.get_happy_messages())

    def _say(self, messages) -> None:
        msg = random.choice(messages)
        self._show_bubble(msg, 6000)

    def _end_jump(self) -> None:
        self._jumping = False
        self._mark_movement()

    # ---------- 贴边隐藏 ----------
    def _setup_edge_hide_timer(self) -> None:
        """启动/停止贴边隐藏的空闲计时器（每秒检查一次）。"""
        if not config.flag("edge_hide_enabled"):
            if self._edge_hide_idle_timer is not None:
                self._edge_hide_idle_timer.stop()
            return
        if self._edge_hide_idle_timer is None:
            self._edge_hide_idle_timer = QTimer(self)
            self._edge_hide_idle_timer.setInterval(1000)
            self._edge_hide_idle_timer.timeout.connect(self._check_edge_hide)
        self._edge_hide_idle_timer.start()

    def _disable_edge_hide(self) -> None:
        """用户关闭贴边隐藏时调用：停掉定时器，若处于贴边则滑回原位。"""
        if self._edge_hide_idle_timer is not None:
            self._edge_hide_idle_timer.stop()
        if self._edge_state in ("hidden", "hiding"):
            self._begin_edge_show()
        else:
            self._edge_state = "normal"

    def _mark_movement(self) -> None:
        """任何移动（自发或用户驱动）都刷新空闲计时；hiding 中被打断则回到 normal。"""
        self._last_move_time = time.time()
        if self._edge_state == "hiding":
            self._edge_state = "normal"

    def _check_edge_hide(self) -> None:
        if not config.flag("edge_hide_enabled"):
            return
        if self._edge_state in ("hiding", "showing"):
            return
        # 睡觉中 / 睡着靠边中不触发收缝：睡眠已把宠物带到屏幕边缘完整可见，
        # 不需要再缩成一条缝
        if self._sleep_side or self.brain.state == PetBrain.SLEEP:
            return
        if self._edge_state == "normal":
            if self._jumping or self._drag:
                return
            if time.time() - self._last_move_time > config.EDGE_HIDE_IDLE_SECONDS:
                self._begin_edge_hide()
        # 1.7.0：hidden 态不再检查鼠标靠近自动滑回——只有手动点击或提醒才唤出

    def _begin_edge_hide(self) -> None:
        """贴边：找最近的屏幕边缘，滑过去只露 20px。"""
        screen = QApplication.primaryScreen().availableGeometry()
        x, y, w, h = self.x(), self.y(), self.width(), self.height()
        distances = {
            "left": abs(x - screen.left()),
            "right": abs(screen.right() - (x + w)),
            "top": abs(y - screen.top()),
            "bottom": abs(screen.bottom() - (y + h)),
        }
        nearest = min(distances, key=distances.get)
        peek = 20
        tx, ty = x, y
        if nearest == "left":
            tx = screen.left() + peek - w
        elif nearest == "right":
            tx = screen.right() - peek
        elif nearest == "top":
            ty = screen.top() + peek - h
        else:
            ty = screen.bottom() - peek
        self._edge_state = "hiding"
        self._anim_to(tx, ty, 600, on_finish=self._on_hide_arrived)

    def _on_hide_arrived(self) -> None:
        """贴边动画完成：进入 hidden 态。

        1.7.0 起不再启动鼠标位置轮询——隐藏后只有手动点击（_begin_edge_show）
        或提醒（_begin_reminder）两条唤出途径。
        """
        self._edge_state = "hidden"

    def _begin_edge_show(self) -> None:
        """需求2：点击露出的隐藏缝时，滑回最近一次显式停留的位置。"""
        self._edge_state = "showing"
        self._anim_to(
            self._last_user_pos.x(),
            self._last_user_pos.y(),
            500,
            on_finish=self._on_show_arrived,
        )

    def _on_show_arrived(self) -> None:
        """滑回完成：恢复正常态，并恢复收缝期间被暂停的走动/散步。"""
        self._edge_state = "normal"
        self._resume_if_locomoting()

    def _resume_if_locomoting(self) -> None:
        """从收缝唤出后，恢复收缝期间被暂停的走动/散步/自发跳跃。"""
        s = self.brain.state
        if s == PetBrain.WALK and not self.walk_timer.isActive():
            self.walk_timer.start()
            self.walk_frame_timer.start()
        elif s == PetBrain.WANDER:
            self._wander()
        elif s == PetBrain.JUMP and not self._jumping:
            self._do_jump()
            self.jump_loop_timer.start()

    def _start_sleep_side(self) -> None:
        """需求3：入睡时若处于普通位置，滑到最近屏幕边缘完整可见地睡觉。

        唤醒后"睡在哪醒在哪"（用户选择，不回位）；若入睡时已处于贴边收缝
        （hidden/hiding）则保持原状，避免和收缝逻辑打架。
        """
        if self._sleep_side or self._edge_state != "normal":
            return
        if self._drag or self._jumping:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        x, y, w, h = self.x(), self.y(), self.width(), self.height()
        distances = {
            "left": abs(x - screen.left()),
            "right": abs(screen.right() - (x + w)),
            "top": abs(y - screen.top()),
            "bottom": abs(screen.bottom() - (y + h)),
        }
        nearest = min(distances, key=distances.get)
        tx, ty = x, y
        if nearest == "left":
            tx = screen.left()
        elif nearest == "right":
            tx = screen.right() - w
        elif nearest == "top":
            ty = screen.top()
        else:
            ty = screen.bottom() - h
        self._sleep_side = True
        if tx == x and ty == y:
            return  # 已在边缘完整可见，无需移动
        self._slide_anim = self._anim_to(tx, ty, 800)

    def _anim_to(self, tx: int, ty: int, duration: int, on_finish=None):
        """平移窗口到 (tx,ty)；返回动画对象。先停掉上一个平移动画避免互相拉扯。"""
        if self._edge_anim is not None:
            self._edge_anim.stop()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(duration)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(tx, ty))
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        if on_finish is not None:
            anim.finished.connect(on_finish)
        anim.start()
        self._edge_anim = anim
        return anim

    # ---------- 位置 ----------
    def _restore_pos(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        try:
            x = int(config.get("pos_x"))
            y = int(config.get("pos_y"))
        except (TypeError, ValueError):
            x, y = -1, -1
        if x >= 0 and y >= 0:
            x = max(screen.left(), min(x, screen.right() - self.width()))
            y = max(screen.top(), min(y, screen.bottom() - self.height()))
        else:
            x = screen.right() - self.width() - 40
            y = screen.bottom() - self.height() - 40
        self.move(x, y)

    def _save_pos(self) -> None:
        config.set_value("pos_x", self.x())
        config.set_value("pos_y", self.y())

    # ---------- 喝水提醒 ----------
    def _setup_drink_timer(self) -> None:
        """根据配置启动/停止提醒计时。"""
        if bool(config.get("drink_enabled")):
            interval_ms = int(config.get("drink_interval")) * 60 * 1000
            self.drink_timer.start(max(5000, interval_ms))
        else:
            self.drink_timer.stop()

    def remind_drink(self) -> None:
        """到点提醒：随机提示词 + 音效 + 跳跃 + 气泡，按位置模式决定是否跑到屏幕中心。"""
        if self._away:
            # 周期提醒离开期间丢弃，回来后按间隔重新计时即可，不必补报
            self._setup_drink_timer()
            return
        msg = random.choice(config.get_drink_messages())
        self._play_sound("drink.wav")
        was = self._begin_reminder()
        # 喝水提醒期间用 drink 帧（10 秒过期，配合气泡持续时间）
        if "drink" in self.frames:
            self._override_frame = "drink"
            self._override_until = time.time() * 1000 + 10000
        # 喝水专属动作台词（用新 ACTION_QUOTES 系统）
        self._emit_action_quote("drink")
        if config.get("drink_location") == "center" and not config.is_silent_now():
            origin = self.pos()
            self._move_to_center()
            self._remind_anim.finished.connect(lambda: self._do_jump_and_bubble(msg))
            # 气泡消失后回到原位
            QTimer.singleShot(10200, lambda: self._move_back(origin))
        else:
            self._do_jump_and_bubble(msg)
        self._end_reminder(was)
        # 重新计时下一轮
        self._setup_drink_timer()

    def _do_jump_and_bubble(self, msg: str) -> None:
        """跳跃 + 长时间气泡；静默（免打扰/专注）时只弹气泡不跳。"""
        if not config.is_silent_now():
            self._jumping = True
            jump_animation(self).start()
            QTimer.singleShot(400, self._end_jump)
        self._show_bubble(msg, 12000)

    def _play_sound(self, name: str) -> None:
        """播放提示音；关闭提示音或处于静默（免打扰/专注）时不播放。"""
        if not config.sound_allowed():
            return
        try:
            import winsound

            path = config.resource_path("sounds", name)
            if os.path.exists(path):
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass

    def _move_back(self, pos) -> None:
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(500)
        anim.setStartValue(self.pos())
        anim.setEndValue(pos)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.finished.connect(self._save_pos)
        anim.start()

    def _move_to_center(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        tx = screen.left() + (screen.width() - self.width()) // 2
        ty = screen.top() + (screen.height() - self.height()) // 2
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(600)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(tx, ty))
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.finished.connect(self._save_pos)
        anim.start()
        self._remind_anim = anim

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        if self.bubble is not None and self.bubble.isVisible():
            self.bubble.reposition()

    def _show_bubble(self, msg: str, duration: int = 12000) -> None:
        """统一气泡显示：取消旧 hide 定时器，避免多个定时器互相干扰。"""
        self._bubble_timer.stop()
        self.bubble.show_text(msg, self)
        self._bubble_timer.start(duration)

    def _notify(self, msg: str, duration: int = 10000) -> None:
        """通用原地提醒：跳一下 + 气泡。静默（免打扰/专注）时只弹气泡。"""
        if not config.is_silent_now():
            self._jumping = True
            jump_animation(self).start()
            QTimer.singleShot(400, self._end_jump)
        self._show_bubble(msg, duration)

    def _in_silence(self) -> bool:
        """当前是否静默（免打扰时段或专注模式）。"""
        return config.is_silent_now()

    def _begin_reminder(self) -> bool:
        """提醒开始：若藏在屏幕边缘（收缝）则先还原；若在睡觉则唤醒。返回原本是否在睡。

        需求2：收缝（hidden/hiding）只有手动点击或提醒两条唤出途径，提醒走这里。
        瞬间回到最近停留的位置（不做滑回动画），避免和随后的跳跃/移动动画抢窗口。
        """
        if self._edge_state in ("hidden", "hiding"):
            self._edge_state = "normal"
            if self._edge_anim is not None:
                self._edge_anim.stop()
                self._edge_anim = None
            self.move(self._last_user_pos.x(), self._last_user_pos.y())
        was = self.brain.state == PetBrain.SLEEP
        if was:
            self.brain.wake()
        return was

    def _end_reminder(self, was_sleeping: bool, delay: int = 13000) -> None:
        """提醒结束：若原本在睡，延迟后回去继续睡。"""
        if was_sleeping:
            QTimer.singleShot(delay, self.brain.go_sleep)

    # ---------- 整点报时 ----------
    def _setup_hourly_timer(self) -> None:
        if bool(config.get("hourly_enabled")):
            now = datetime.datetime.now()
            nxt = (now + datetime.timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            ms = int((nxt - now).total_seconds() * 1000)
            self.hourly_timer.start(ms)
        else:
            self.hourly_timer.stop()

    def remind_hourly(self) -> None:
        if self._away:
            self._setup_hourly_timer()
            return
        h = datetime.datetime.now().hour
        msg = random.choice(config.get_hourly_messages()).format(h=h)
        was = self._begin_reminder()
        self._notify(msg)
        self._end_reminder(was)
        self._setup_hourly_timer()

    # ---------- 久坐休息 ----------
    def _setup_sit_timer(self) -> None:
        if bool(config.get("sit_enabled")):
            interval_ms = int(config.get("sit_interval")) * 60 * 1000
            self.sit_timer.start(max(5000, interval_ms))
        else:
            self.sit_timer.stop()

    def remind_sit(self) -> None:
        if self._away:
            self._setup_sit_timer()
            return
        was = self._begin_reminder()
        self._notify(random.choice(config.get_sit_messages()))
        self._end_reminder(was)
        self._setup_sit_timer()

    # ---------- 下班倒计时 ----------
    def _setup_offwork_timer(self) -> None:
        if bool(config.get("offwork_enabled")):
            try:
                t = datetime.datetime.strptime(config.get("offwork_time"), "%H:%M").time()
                now = datetime.datetime.now()
                target = datetime.datetime.combine(now.date(), t)
                if target <= now:
                    target += datetime.timedelta(days=1)
                ms = int((target - now).total_seconds() * 1000)
                self.offwork_timer.start(ms)
            except Exception:
                self.offwork_timer.stop()
        else:
            self.offwork_timer.stop()

    def remind_offwork(self) -> None:
        if self._away:
            self._setup_offwork_timer()
            return
        was = self._begin_reminder()
        self._notify(random.choice(config.get_offwork_messages()), duration=12000)
        self._end_reminder(was, delay=14000)
        self._setup_offwork_timer()

    # ---------- 自定义提醒事项 ----------
    def _setup_custom_reminders(self) -> None:
        """启动自定义提醒轮询；没有事项时停掉定时器省资源。"""
        if self.custom_timer is None:
            self.custom_timer = QTimer(self)
            self.custom_timer.setInterval(30000)
            self.custom_timer.timeout.connect(self._check_custom_reminders)
        if config.get_custom_reminders():
            self.custom_timer.start()
        else:
            self.custom_timer.stop()

    def _check_custom_reminders(self) -> None:
        """检查是否有事项到点。30 秒轮询保证不会漏掉整分钟，靠去重保证只触发一次。"""
        now = datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self._fired_custom_day != today:
            self._fired_custom.clear()
            self._fired_custom_day = today
        hm = now.strftime("%H:%M")
        for item in config.get_custom_reminders():
            if not item.get("enabled", True):
                continue
            if item.get("time") != hm:
                continue
            kind = item.get("kind", "daily")
            if kind == "weekly" and int(item.get("weekday", 0)) != now.weekday():
                continue
            if kind == "once" and item.get("date") != today:
                continue
            fid = f"{today}:{item.get('id')}"
            if fid in self._fired_custom:
                continue
            self._fired_custom.add(fid)
            self._on_custom_reminder(item)

    def _on_custom_reminder(self, item: dict) -> None:
        """自定义事项到点提醒（静默时自动不响铃不跳跃，只留气泡）。"""
        if self._away:
            # 自定义提醒有时效性（吃药/周会/取快递），记下来等回来补报
            self._missed_custom.append(str(item.get("label") or "时间到啦"))
            return
        was = self._begin_reminder()
        self._play_sound("msg.wav")
        self._notify(str(item.get("label") or "时间到啦"), duration=12000)
        self._end_reminder(was, delay=14000)

    def refresh_reminder(self, kind: str) -> None:
        """只刷新指定提醒的计时，不影响其他提醒的倒计时。

        kind: drink / hourly / sit / offwork / custom
        早期版本改一个设置会把 4 个计时器全部重启（喝水倒计时被清零），
        这里按类型精确刷新，改久坐间隔不影响喝水计时。
        """
        if kind == "drink":
            self._setup_drink_timer()
        elif kind == "hourly":
            self._setup_hourly_timer()
        elif kind == "sit":
            self._setup_sit_timer()
        elif kind == "offwork":
            self._setup_offwork_timer()
        elif kind == "custom":
            self._setup_custom_reminders()

    def refresh_reminders(self) -> None:
        """配置变更后（托盘调用）刷新所有提醒计时。"""
        self._setup_drink_timer()
        self._setup_hourly_timer()
        self._setup_sit_timer()
        self._setup_offwork_timer()
        self._setup_custom_reminders()

    # ---------- 飞书新消息提醒 ----------
    def _on_feishu_message(self, sender: str, content: str) -> None:
        """收到飞书新消息：唤醒 + 跳一下 + 气泡显示摘要 + 提示音。"""
        if self._away:
            return  # 回来时由未读汇总统一补报，不逐条打扰
        was = self._begin_reminder()
        self._play_sound("msg.wav")
        if sender == "飞书":
            msg = f"【飞书】{content}"
        else:
            msg = f"【飞书】{sender}：{content}"
        self._notify(msg, duration=8000)
        self._end_reminder(was, delay=9000)

    def _on_im_unread_changed(self, app: str, unread: bool) -> None:
        """IM 未读状态翻转：有未读 → 常规提醒 + 启动超时强提醒；已读 → 取消强提醒。

        IM 不对外暴露消息内容，只能得到「有未读」信号，气泡为通用提示。
        """
        if unread:
            if self._away:
                # 离开期间不逐条打扰，回来由未读汇总统一补报
                self._start_unread_timer(app)
                return
            was = self._begin_reminder()
            self._play_sound("msg.wav")
            self._notify(f"【{app}】有新消息，快去看看吧", duration=8000)
            self._end_reminder(was, delay=9000)
            self._start_unread_timer(app)
        else:
            self._cancel_unread_timer(app)

    def _start_unread_timer(self, app: str) -> None:
        """启动某应用的「持续未读」超时定时器（幂等）。"""
        if app in self._unread_timers:
            return
        delay = max(10, int(config.get("unread_center_delay"))) * 1000
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda a=app: self._on_unread_still_pending(a))
        self._unread_timers[app] = t
        t.start(delay)

    def _cancel_unread_timer(self, app: str) -> None:
        t = self._unread_timers.pop(app, None)
        if t is not None:
            t.stop()

    def _on_unread_still_pending(self, app: str) -> None:
        """超时仍未读：桌宠跑到屏幕中心强提醒，之后若继续未读则每超时再提醒一次。"""
        self._unread_timers.pop(app, None)
        if not self.im_watcher.is_unread(app):
            return  # 已经读过了，不再提醒
        if self._away:
            # 离开期间不跑到屏幕中心，继续排队等回来
            self._start_unread_timer(app)
            return
        was = self._begin_reminder()
        self._play_sound("msg.wav")
        tip = f"【{app}】消息还没看，快回来看看！"
        if config.is_silent_now():
            # 静默期间不跑到屏幕中心打扰，只在原地弹气泡
            self._show_bubble(tip, 12000)
        else:
            origin = self.pos()
            self._move_to_center()
            self._remind_anim.finished.connect(
                lambda: self._do_jump_and_bubble(tip)
            )
            QTimer.singleShot(12000, lambda: self._move_back(origin))
        self._end_reminder(was, delay=14000)
        self._start_unread_timer(app)

    # ---------- 离开感知（锁屏 / 解锁） ----------
    def showEvent(self, e) -> None:
        """窗口显示后注册会话通知：HWND 此刻才有效。"""
        super().showEvent(e)
        if not self._session_registered:
            self._session_registered = True
            self._setup_session_monitor()

    def _setup_session_monitor(self) -> None:
        """注册锁屏/解锁通知。失败只记日志，不影响其它功能。"""
        if not config.flag("away_detect_enabled"):
            return
        if session_monitor.register(int(self.winId())):
            logger.info("离开感知已启用（锁屏时自动静默，回来补报）")
        else:
            logger.warning("离开感知注册失败，锁屏检测不可用")

    def _teardown_session_monitor(self) -> None:
        session_monitor.unregister(int(self.winId()))
        self._session_registered = False

    def nativeEvent(self, eventType, message):
        """接收 Windows 原生消息，只处理会话变更（锁屏/解锁）。"""
        kind = session_monitor.parse_message(message)
        if kind == "lock":
            self._on_session_lock()
        elif kind == "unlock":
            self._on_session_unlock()
        return super().nativeEvent(eventType, message)

    def _on_session_lock(self) -> None:
        """锁屏 / 离开：进入静默，暂停久坐计时，清空上一轮补报记录。"""
        if self._away:
            return
        self._away = True
        self._away_since = time.time()
        self._missed_custom.clear()
        config.set_away(True)
        # 久坐计时在离开期间没有意义：暂停，回来重新计时
        #（否则离开两小时后一回来就立刻弹「该起身了」）
        self.sit_timer.stop()
        self._hide_bubble_now()
        logger.info("检测到离开（锁屏），桌宠进入静默")

    def _on_session_unlock(self) -> None:
        """解锁 / 回来：恢复计时，汇总补报离开期间错过的事。"""
        if not self._away:
            return
        self._away = False
        config.set_away(False)
        away_sec = time.time() - (self._away_since or time.time())
        self._away_since = None
        self._setup_sit_timer()  # 久坐计时重新开始
        logger.info("检测到回来（解锁），离开 %.0f 秒", away_sec)
        report = self._build_welcome_back(away_sec)
        if report:
            was = self._begin_reminder()
            self._notify(report, duration=15000)
            self._end_reminder(was, delay=16000)

    def _build_welcome_back(self, away_sec: float) -> str:
        """拼「欢迎回来」补报文案；离开太短或没内容就不打扰。"""
        if away_sec < 60:
            return ""  # 只是快速锁一下屏，不打扰
        mins = int(away_sec // 60)
        if mins < 60:
            head = f"欢迎回来～你离开了 {mins} 分钟"
        else:
            head = f"欢迎回来～你离开了 {mins // 60} 小时 {mins % 60} 分钟"

        lines = []
        try:
            pending = self.im_watcher.unread_apps()
            if pending:
                lines.append("、".join(pending) + " 有未读消息")
        except Exception:  # noqa: BLE001
            pass
        if self._missed_custom:
            shown = self._missed_custom[:5]
            more = len(self._missed_custom) - len(shown)
            tail = f" 等 {len(self._missed_custom)} 条" if more > 0 else ""
            lines.append("错过提醒：" + "、".join(shown) + tail)
        self._missed_custom.clear()

        if not lines:
            return head
        return head + "\n" + "；".join(lines)

    def _hide_bubble_now(self) -> None:
        """立即收起气泡（离开时避免留一个过期气泡在桌面）。"""
        self._bubble_timer.stop()
        if self.bubble is not None:
            self.bubble.hide()

    # ---------- 番茄钟阶段切换 ----------
    def _on_pomodoro_tick(self) -> None:
        """1s 周期：检查番茄钟阶段是否结束，是则切换并通知用户。

        阶段切换不弹系统通知——番茄钟是"温和"循环，仅在桌宠身上：
        1. 切表情（work → think，break → laugh）
        2. 弹气泡说"该休息啦" / "继续工作"
        3. 表情通过 _pomodoro_frame 持续到阶段结束（不依赖 _override_until）

        **同步保护**：tick 入口处若 _pomodoro_frame 为 None 而番茄钟已运行
        （用户在另一进程改 QSettings 启动、或刚被切换但表达式没匹配等），
        根据当前 phase 同步表情字段。避免窗口一直停在 idle 帧
        """
        if config.pomodoro_active() and not self._pomodoro_frame:
            phase = config.pomodoro_phase()
            if phase == "work":
                self._pomodoro_frame = "think" if "think" in self.frames else None
            elif phase in ("short_break", "long_break"):
                self._pomodoro_frame = "laugh" if "laugh" in self.frames else None
        result = config.pomodoro_tick()
        if result is not None:
            old_phase, new_phase, finished_work = result
            # 表情：work 阶段严肃，break 阶段开心
            if new_phase == "work":
                self._pomodoro_frame = "think" if "think" in self.frames else None
            else:
                self._pomodoro_frame = "laugh" if "laugh" in self.frames else None
            self._refresh_frame()
            # 气泡台词
            if new_phase == "work":
                self._show_bubble("继续工作，专注 25 分钟～", 8000)
            elif new_phase == "short_break":
                self._show_bubble("该休息啦，伸个懒腰 5 分钟～", 8000)
            else:  # long_break
                self._show_bubble("完成一轮！来个长休 15 分钟～", 10000)
            # 托盘菜单标题刷新（剩余时间变了）
            if hasattr(self.tray, "_sync_focus_menu"):
                self.tray._sync_focus_menu()
            # 通知托盘刷新「今日完成：N」项
            if hasattr(self.tray, "_sync_pomodoro_menu"):
                self.tray._sync_pomodoro_menu()
        # 每 60s 刷新一次菜单标题（避免显示"剩 25 分"卡了 24 分钟不变）
        elif config.pomodoro_active() and hasattr(self, "_pomodoro_tick_count"):
            self._pomodoro_tick_count += 1
            if self._pomodoro_tick_count >= 60 and hasattr(self.tray, "_sync_focus_menu"):
                self._pomodoro_tick_count = 0
                self.tray._sync_focus_menu()
        else:
            self._pomodoro_tick_count = 0

    def _refresh_frame(self) -> None:
        """刷新当前帧（强制重新调 _on_breath）。"""
        if hasattr(self, "_on_breath"):
            self._on_breath()

    def start_pomodoro(self) -> None:
        """托盘入口：启动番茄钟（从 work round 1 开始）。"""
        config.start_pomodoro()
        self._pomodoro_frame = "think" if "think" in self.frames else None
        self._refresh_frame()
        self._show_bubble("番茄钟启动～ 工作中 25 分钟", 6000)
        if hasattr(self.tray, "_sync_focus_menu"):
            self.tray._sync_focus_menu()
        if hasattr(self.tray, "_sync_pomodoro_menu"):
            self.tray._sync_pomodoro_menu()

    def stop_pomodoro(self) -> None:
        """托盘入口：结束番茄钟。"""
        config.stop_pomodoro()
        self._pomodoro_frame = None
        self._refresh_frame()
        self._show_bubble("番茄钟结束～", 5000)
        if hasattr(self.tray, "_sync_focus_menu"):
            self.tray._sync_focus_menu()
        if hasattr(self.tray, "_sync_pomodoro_menu"):
            self.tray._sync_pomodoro_menu()

    def set_away_detect(self, enabled: bool) -> None:
        """托盘开关：启用/停用离开感知。"""
        config.set_value("away_detect_enabled", bool(enabled))
        if enabled:
            self._setup_session_monitor()
        else:
            self._teardown_session_monitor()
            if self._away:  # 关掉功能时若正处在离开态，立刻恢复正常
                self._away = False
                self._away_since = None
                self._missed_custom.clear()
                config.set_away(False)
                self._setup_sit_timer()

    def closeEvent(self, e):
        self._save_pos()
        try:
            self._teardown_session_monitor()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(e)
