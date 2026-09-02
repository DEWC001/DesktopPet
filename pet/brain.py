"""宠物行为状态机：睡眠为主，偶尔醒来短暂活动，到点提醒时唤醒。

活跃度（config.activity()，0-100，默认 50）动态调节"睡眠占比"：
- 活跃度越低：睡得越久、清醒越短、越容易回睡、动作越安静
- 活跃度越高：睡得越短、清醒越长、越不容易回睡、动作越活泼（跳跃/散步）
50 为基准值，与 1.6.0 之前的行为完全一致（回归测试依赖这一点）。
"""
import random

from PySide6.QtCore import QObject, QTimer, Signal

from . import config


class PetBrain(QObject):
    IDLE = "idle"
    WALK = "walk"
    SLEEP = "sleep"
    JUMP = "jump"      # 开心连跳
    CHAT = "chat"      # 随机说话
    WANDER = "wander"  # 散步到随机位置

    state_changed = Signal(str)

    # 各状态持续时长基准（毫秒，活跃度=50 时生效）：
    # 睡眠相对短（30-80s），让宠物更常醒来活动
    DURATIONS = {
        IDLE: (8000, 18000),
        WALK: (8000, 16000),
        JUMP: (1500, 2500),
        SLEEP: (30000, 80000),   # 原本 90-240s 太长，缩到 30-80s
        CHAT: (4500, 7000),
        WANDER: (2500, 5000),
    }

    # 醒来后的活动选项基准（活跃度=50 时生效，含 WANDER 散步到随机位置）
    AWAKE_ACTIONS = [IDLE, WALK, JUMP, CHAT, WANDER, WANDER]  # WANDER 加权

    # 活动结束后的回睡概率基准（活跃度=50 时生效）
    RESLEEP_PROB = 0.45

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = self.SLEEP  # 初始直接进入睡眠
        self.scheduler = QTimer(self)
        self.scheduler.setSingleShot(True)
        self.scheduler.timeout.connect(self._next)

    def start(self) -> None:
        self._schedule()

    def poke(self) -> None:
        """被点击：醒来待机并重新计时。"""
        self._set_state(self.IDLE)
        self._schedule()

    def wake(self) -> None:
        """唤醒到待机。"""
        self._set_state(self.IDLE)
        self._schedule()

    def go_sleep(self) -> None:
        """进入睡眠。"""
        self._set_state(self.SLEEP)
        self._schedule()

    def reschedule(self) -> None:
        """活跃度等参数变更后按当前状态重新计时（立即生效）。"""
        self._schedule()

    # ---------- 活跃度换算（纯函数，便于测试） ----------
    @staticmethod
    def _scale(activity: int, y0: float, y1: float, y2: float) -> float:
        """两段线性插值：activity=0→y0，=50→y1，=100→y2。"""
        if activity <= 50:
            return y0 + (y1 - y0) * (activity / 50.0)
        return y1 + (y2 - y1) * ((activity - 50) / 50.0)

    def _dur_range(self, state: str) -> tuple[int, int]:
        """按当前活跃度返回状态的持续时长范围（毫秒）。"""
        lo, hi = self.DURATIONS.get(state, (4000, 9000))
        act = config.activity()
        if state == self.SLEEP:
            # 睡得久 = 睡眠占比高：低活跃睡 1.8 倍，高活跃只睡一半
            m = self._scale(act, 1.8, 1.0, 0.5)
            return int(lo * m), int(hi * m)
        # 清醒状态：活跃度越高清醒越长；JUMP 是短爆发，下限兜底防呆
        m = self._scale(act, 0.6, 1.0, 1.6)
        return max(800, int(lo * m)), max(1200, int(hi * m))

    def _resleep_prob(self) -> float:
        """回睡概率：低活跃更爱睡回去（0.8），高活跃更愿多待会（0.1）。"""
        return self._scale(config.activity(), 0.80, 0.45, 0.10)

    def _awake_actions(self) -> list[str]:
        """清醒动作池：低活跃安静（无跳跃无远走），高活跃更活泼（跳跃/散步加权）。"""
        act = config.activity()
        if act < 20:
            return [self.IDLE, self.IDLE, self.WALK, self.CHAT]
        if act < 40:
            return [self.IDLE, self.WALK, self.CHAT, self.WANDER]
        if act < 70:
            return list(self.AWAKE_ACTIONS)  # 基准：含跳跃与散步
        return self.AWAKE_ACTIONS + [self.WANDER, self.JUMP]  # 高活跃额外加权

    def _schedule(self) -> None:
        lo, hi = self._dur_range(self.state)
        self.scheduler.start(random.randint(lo, hi))

    def _next(self) -> None:
        if self.state == self.SLEEP:
            # 睡醒了，进入短暂活动
            nxt = random.choice(self._awake_actions())
        else:
            # 活动结束，按概率决定回睡还是继续活动
            if random.random() < self._resleep_prob():
                nxt = self.SLEEP
            else:
                nxt = random.choice(self._awake_actions())
        self._set_state(nxt)
        self._schedule()

    def _set_state(self, s: str) -> None:
        if s == self.state:
            return
        self.state = s
        self.state_changed.emit(s)
