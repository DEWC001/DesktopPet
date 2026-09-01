"""宠物行为状态机：睡眠为主，偶尔醒来短暂活动，到点提醒时唤醒。"""
import random

from PySide6.QtCore import QObject, QTimer, Signal


class PetBrain(QObject):
    IDLE = "idle"
    WALK = "walk"
    SLEEP = "sleep"
    JUMP = "jump"      # 开心连跳
    CHAT = "chat"      # 随机说话
    WANDER = "wander"  # 散步到随机位置

    state_changed = Signal(str)

    # 各状态持续时长（毫秒）：睡眠相对短（30-80s），让宠物更常醒来活动
    DURATIONS = {
        IDLE: (8000, 18000),
        WALK: (8000, 16000),
        JUMP: (1500, 2500),
        SLEEP: (30000, 80000),   # 原本 90-240s 太长，缩到 30-80s
        CHAT: (4500, 7000),
        WANDER: (2500, 5000),
    }

    # 醒来后的活动选项（含 WANDER 散步到随机位置，让宠物真正"会移动"）
    AWAKE_ACTIONS = [IDLE, WALK, JUMP, CHAT, WANDER, WANDER]  # WANDER 加权

    # 活动结束后的回睡概率（0.45 = 大半时间在外面活动，只有不到一半回去睡）
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

    def _schedule(self) -> None:
        lo, hi = self.DURATIONS.get(self.state, (4000, 9000))
        self.scheduler.start(random.randint(lo, hi))

    def _next(self) -> None:
        if self.state == self.SLEEP:
            # 睡醒了，进入短暂活动
            nxt = random.choice(self.AWAKE_ACTIONS)
        else:
            # 活动结束，按概率决定回睡还是继续活动（45% 回睡，比原来 80% 少很多）
            if random.random() < self.RESLEEP_PROB:
                nxt = self.SLEEP
            else:
                nxt = random.choice(self.AWAKE_ACTIONS)
        self._set_state(nxt)
        self._schedule()

    def _set_state(self, s: str) -> None:
        if s == self.state:
            return
        self.state = s
        self.state_changed.emit(s)
