"""透明置顶窗口 + 拖拽 + 点击反馈 + 多帧精灵图动画。"""
import datetime
import math
import os
import random
import time

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from . import config
from .animation import jump_animation
from .brain import PetBrain
from .notification_listener import NotificationWatcher
from .im_unread_watcher import ImUnreadWatcher
from .speech_bubble import SpeechBubble

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

        self.scale = float(config.get("scale"))

        # 加载所有精灵帧（基础 + 扩展），缺失基础帧回退 idle，缺失扩展帧跳过
        self.frames: dict[str, QPixmap] = {}
        idle = self._load_all_frames()
        self._rebuild_breath_cache()

        self._margin = 8
        self.setFixedSize(idle.width() + self._margin * 2, idle.height() + self._margin * 2)
        self.label = QLabel(self)
        self.label.setGeometry(self._margin, self._margin, idle.width(), idle.height())

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
        # 双击抑制：Qt 双击序列为 press→release→dblclick→release，
        # 第二次 release 会再触发一次单击逻辑，需标记抑制，否则双击会多跳一次
        self._suppress_click = False
        # 连跳定时器池（可取消，避免连点时叠加跳动）
        self._jump_timers: list[QTimer] = []
        # 贴边隐藏：normal → hiding → hidden → showing → normal
        # 静止 N 秒后滑到最近边缘只露一角，鼠标靠近再滑回 _last_user_pos
        self._edge_state = "normal"
        self._last_move_time = time.time()
        self._last_user_pos = self.pos()
        self._edge_hide_idle_timer: QTimer = None
        self._edge_hide_check_timer: QTimer = None
        self._edge_anim = None
        # 动作台词冷却：{state: last_emit_time}，避免切换刷屏
        self._last_action_quote_at: dict[str, float] = {}
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
        # 2. 状态映射
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

    def _on_walk(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = self.x() + self._walk_dir * 2
        if x < screen.left() or x + self.width() > screen.right():
            self._walk_dir *= -1
            x = self.x() + self._walk_dir * 2
        self.move(x, self.y())
        self._mark_movement()

    def _on_state(self, s: str) -> None:
        self.walk_timer.stop()
        self.walk_frame_timer.stop()
        self.jump_loop_timer.stop()

        if s == PetBrain.WALK:
            self._walk_dir = random.choice([-1, 1])
            self.walk_timer.start()
            self.walk_frame_timer.start()
        elif s == PetBrain.JUMP:
            self._do_jump()
            self.jump_loop_timer.start()
        elif s == PetBrain.CHAT:
            self._chat()
        elif s == PetBrain.WANDER:
            self._wander()

        self._blinking = s == PetBrain.SLEEP
        # 切换动作时按冷却弹台词气泡
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

    def _do_jump(self, dx=None) -> None:
        if dx is None:
            dx = random.randint(-24, 24)
        self._jumping = True
        anim = jump_animation(self, dx)
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

    # ---------- 拖拽 / 点击 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._press_global = e.globalPosition().toPoint()
            self._win_origin = self.pos()
            self._moved = False
            if self._edge_state == "hidden":
                # 用户点击露出的部分：直接滑回原位
                self._begin_edge_show()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag:
            delta = e.globalPosition().toPoint() - self._press_global
            if delta.manhattanLength() > 4:
                self._moved = True
            if self._moved:
                self.move(self._win_origin + delta)
            e.accept()

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
        self._do_jump()
        if random.random() < 0.5:
            self._say(config.get_click_messages())

    def _cancel_pending_jumps(self) -> None:
        """取消尚未触发的连跳定时器（连点双击时不叠加跳动）。"""
        for t in self._jump_timers:
            t.stop()
        self._jump_timers.clear()

    def _schedule_jump(self, delay: int) -> None:
        """安排一次延迟跳跃，可被 _cancel_pending_jumps 取消。"""
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(self._do_jump)
        t.start(delay)
        self._jump_timers.append(t)

    def _do_double_click(self) -> None:
        # 双击：连跳 3 下 + 临时 laugh 帧（1.5 秒后恢复）
        self._cancel_pending_jumps()
        self._mark_movement()
        if "laugh" in self.frames:
            self._override_frame = "laugh"
            self._override_until = time.time() * 1000 + 1500
        for i in range(3):
            self._schedule_jump(i * 280)
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
        if self._edge_hide_check_timer is not None:
            self._edge_hide_check_timer.stop()
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
        if self._edge_state == "normal":
            if self._jumping or self._drag:
                return
            if time.time() - self._last_move_time > config.EDGE_HIDE_IDLE_SECONDS:
                self._begin_edge_hide()
        elif self._edge_state == "hidden":
            # 鼠标在窗口几何外扩 30px 内即触发滑回
            geom = self.geometry().adjusted(-30, -30, 30, 30)
            if geom.contains(QCursor.pos()):
                self._begin_edge_show()

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
        """贴边动画完成：启动鼠标位置轮询，等待用户靠近。"""
        self._edge_state = "hidden"
        if self._edge_hide_check_timer is None:
            self._edge_hide_check_timer = QTimer(self)
            self._edge_hide_check_timer.setInterval(200)
            self._edge_hide_check_timer.timeout.connect(self._check_edge_hide)
        self._edge_hide_check_timer.start()

    def _begin_edge_show(self) -> None:
        """滑回用户最近显式拖到的位置。"""
        if self._edge_hide_check_timer is not None:
            self._edge_hide_check_timer.stop()
        self._edge_state = "showing"
        self._anim_to(
            self._last_user_pos.x(),
            self._last_user_pos.y(),
            500,
            on_finish=lambda: setattr(self, "_edge_state", "normal"),
        )

    def _anim_to(self, tx: int, ty: int, duration: int, on_finish=None) -> None:
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(duration)
        anim.setStartValue(self.pos())
        anim.setEndValue(QPoint(tx, ty))
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        if on_finish is not None:
            anim.finished.connect(on_finish)
        anim.start()
        self._edge_anim = anim

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
        """提醒开始：若在睡觉则唤醒，返回原本是否在睡。"""
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

    def closeEvent(self, e):
        self._save_pos()
        super().closeEvent(e)
