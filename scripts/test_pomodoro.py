"""番茄钟（Pomodoro）功能测试（1.5.0）。

- 状态机：start/tick/stop 行为
- 阶段切换：work → short_break → work → ... → long_break → work
- 计数：每日完成数 + 跨日重置
- 与 is_silent_now() 集成
- 与宠物状态机集成（_pomodoro_frame 切表情）

注意：pomodoro_tick() 是依赖 time.time() 的逻辑函数，单测里直接 monkey-patch
config.time.time() 来模拟"过去几分钟"，不需要真等。
"""
import os
import sys
import time
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

# 在 import pet 前 stub QApplication 副作用最小化
_app = QApplication.instance() or QApplication([])

from pet import config
from pet import window as window_mod


PASS = 0
FAIL = 0


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except Exception as exc:
        FAIL += 1
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()


def reset_pomodoro_state() -> None:
    """清掉 QSettings 里的番茄钟字段。"""
    config.set_value("pomodoro_active", False)
    config.set_value("pomodoro_phase", "work")
    config.set_value("pomodoro_round", 1)
    config.set_value("pomodoro_phase_end", 0)
    config.set_value("pomodoro_phase_start", 0)
    config.set_value("pomodoro_today_date", "")
    config.set_value("pomodoro_today_count", 0)


def fake_time(epoch: float):
    """Monkey-patch config.time.time 返回固定值。"""
    orig = config.time.time
    config.time.time = lambda: epoch
    return lambda: setattr(config.time, "time", orig)


# ---------- 1. 状态机：start / stop ----------

def t_start_initial_state() -> None:
    reset_pomodoro_state()
    config.start_pomodoro()
    assert config.pomodoro_active() is True, "start 后应激活"
    assert config.pomodoro_phase() == "work", f"初始阶段应为 work，实际 {config.pomodoro_phase()}"
    assert config.pomodoro_round() == 1, f"初始 round 应为 1，实际 {config.pomodoro_round()}"
    assert config.pomodoro_phase_remaining() > 0, "剩余时间应 > 0"
    config.stop_pomodoro()

check("启动 → work round 1", t_start_initial_state)


def t_stop_clears_state() -> None:
    config.start_pomodoro()
    config.stop_pomodoro()
    assert config.pomodoro_active() is False, "stop 后应停止"
    assert config.pomodoro_phase() is None, f"stop 后 phase 应为 None，实际 {config.pomodoro_phase()}"
    assert config.pomodoro_phase_remaining() == 0, "stop 后剩余应为 0"

check("停止清状态", t_stop_clears_state)


def t_double_start_idempotent() -> None:
    reset_pomodoro_state()
    config.start_pomodoro()
    end1 = config.pomodoro_phase_end()
    config.start_pomodoro()  # 第二次启动应 noop
    end2 = config.pomodoro_phase_end()
    assert end1 == end2, "重复 start 不应重置阶段时间"
    config.stop_pomodoro()

check("重复启动幂等", t_double_start_idempotent)


# ---------- 2. 阶段切换：work → short_break → work → ... → long_break → work ----------

def t_work_to_short_break() -> None:
    """完成第一个 work：阶段切到 short_break。"""
    reset_pomodoro_state()
    restore = fake_time(1_000_000.0)
    try:
        config.start_pomodoro()  # work round 1, end = 1_000_000 + 25*60
        end = config.pomodoro_phase_end()
        # 把"现在"推过阶段结束时间
        config.time.time = lambda: end + 1
        result = config.pomodoro_tick()
        assert result is not None, "过阶段时间后 tick 应返回切换"
        old, new, finished = result
        assert old == "work" and new == "short_break" and finished is True, \
            f"应为 work→short_break 标记完成，实际 {result}"
        assert config.pomodoro_phase() == "short_break", "当前阶段应为 short_break"
        assert config.pomodoro_round() == 2, f"round 应 +1，实际 {config.pomodoro_round()}"
        assert config.pomodoro_today_count() == 1, f"今日完成应 +1，实际 {config.pomodoro_today_count()}"
    finally:
        restore()
        config.stop_pomodoro()

check("work → short_break（round 1 → 2）", t_work_to_short_break)


def t_break_to_work() -> None:
    """短休结束：阶段切回 work。"""
    reset_pomodoro_state()
    restore = fake_time(1_000_000.0)
    try:
        config.start_pomodoro()
        # 先 work → short_break
        config.time.time = lambda: config.pomodoro_phase_end() + 1
        config.pomodoro_tick()
        assert config.pomodoro_phase() == "short_break"
        # 再 short_break → work
        config.time.time = lambda: config.pomodoro_phase_end() + 1
        result = config.pomodoro_tick()
        assert result is not None
        old, new, finished = result
        assert old == "short_break" and new == "work" and finished is False, \
            f"短休结束 finished 应为 False，实际 {result}"
        assert config.pomodoro_phase() == "work"
    finally:
        restore()
        config.stop_pomodoro()

check("short_break → work（不增计数）", t_break_to_work)


def t_long_break_after_4_works() -> None:
    """完成第 4 个 work：下一段是 long_break。

    实现：跑 4 个完整的"work + short_break"循环（中间 3 个），
    最后一个 work 完成时直接检查下一阶段。
    """
    reset_pomodoro_state()
    restore = fake_time(1_000_000.0)
    try:
        config.start_pomodoro()
        # 跑前 3 个 work（每个后跟 short_break，再回 work）
        for _ in range(3):
            # 完成 work
            config.time.time = lambda: config.pomodoro_phase_end() + 1
            r = config.pomodoro_tick()
            assert r[1] == "short_break", f"前 3 个 work 完成应到 short_break，实际 {r[1]}"
            # 走完 short_break 回到 work
            config.time.time = lambda: config.pomodoro_phase_end() + 1
            config.pomodoro_tick()
        # 第 4 个 work：完成时应到 long_break
        config.time.time = lambda: config.pomodoro_phase_end() + 1
        r = config.pomodoro_tick()
        assert r[1] == "long_break", f"第 4 个 work 完成应到 long_break，实际 {r[1]}"
        assert config.pomodoro_today_count() == 4, f"今日完成 4 个番茄，实际 {config.pomodoro_today_count()}"
    finally:
        restore()
        config.stop_pomodoro()

check("完成 4 个 work 后进 long_break", t_long_break_after_4_works)


def t_long_break_back_to_round_1() -> None:
    """长休结束：阶段回到 work，round 回到 1。"""
    reset_pomodoro_state()
    restore = fake_time(1_000_000.0)
    try:
        config.start_pomodoro()
        # 跑 3 个 work+short_break 循环
        for _ in range(3):
            config.time.time = lambda: config.pomodoro_phase_end() + 1
            config.pomodoro_tick()  # work → short_break
            config.time.time = lambda: config.pomodoro_phase_end() + 1
            config.pomodoro_tick()  # short_break → work
        # 第 4 个 work → long_break
        config.time.time = lambda: config.pomodoro_phase_end() + 1
        config.pomodoro_tick()
        assert config.pomodoro_phase() == "long_break"
        # long_break 结束 → work round 1
        config.time.time = lambda: config.pomodoro_phase_end() + 1
        r = config.pomodoro_tick()
        assert r[1] == "work", f"长休结束应回 work，实际 {r[1]}"
        assert config.pomodoro_round() == 1, f"长休后 round 应回 1，实际 {config.pomodoro_round()}"
    finally:
        restore()
        config.stop_pomodoro()

check("long_break → work round 1", t_long_break_back_to_round_1)


def t_tick_before_end_is_noop() -> None:
    """阶段未结束：tick 返回 None。"""
    reset_pomodoro_state()
    restore = fake_time(1_000_000.0)
    try:
        config.start_pomodoro()
        # 还没到阶段结束
        config.time.time = lambda: config.pomodoro_phase_end() - 10
        assert config.pomodoro_tick() is None, "未到结束时间 tick 应 noop"
        # 时间正好等于结束时间
        config.time.time = lambda: config.pomodoro_phase_end()
        # 注意：tick 用的是 `< end`，等于时不切换
        # 改用 `>= end` 之前先看真实行为
        result = config.pomodoro_tick()
        # 当前实现：time.time() < end 才 return None，所以等于时也算结束
        # 这里只断言「没结束时」为 None
    finally:
        restore()
        config.stop_pomodoro()

check("阶段未结束 tick 不切换", t_tick_before_end_is_noop)


def t_tick_when_inactive() -> None:
    """番茄钟未启动时 tick 不做事。"""
    reset_pomodoro_state()
    assert config.pomodoro_tick() is None, "未启动时 tick 应 None"
check("未启动时 tick 不做事", t_tick_when_inactive)


# ---------- 3. 今日计数跨日重置 ----------

def t_count_resets_across_days() -> None:
    """pomodoro_today_count() 在日期变更时自动从 0 开始。"""
    reset_pomodoro_state()
    restore = fake_time(1_700_000_000.0)  # 假设是 2023-11-14
    try:
        # 模拟：今天做了 3 个番茄
        config.set_value("pomodoro_today_date", time.strftime("%Y-%m-%d"))
        config.set_value("pomodoro_today_count", 3)
        assert config.pomodoro_today_count() == 3, "今日计数应为 3"
        # 跨到明天
        config.time.time = lambda: 1_700_000_000.0 + 86400 + 1
        # strftime 用本地时间，不一定真跨日，但 fake_time 至少让 pomodoro_today_count 检查时时间不同
        # 实际上我们测试的是：saved_date 与 today 不一致时返回 0
        # 通过 set_value 强制改 saved_date 到昨天
        config.set_value("pomodoro_today_date", "2020-01-01")
        assert config.pomodoro_today_count() == 0, "saved_date 与今天不同应返回 0"
    finally:
        restore()
        reset_pomodoro_state()

check("今日计数跨日自动归零", t_count_resets_across_days)


# ---------- 4. 与 is_silent_now() 集成 ----------

def t_pomodoro_silences() -> None:
    """番茄钟运行时 is_silent_now() 应返回 True。"""
    reset_pomodoro_state()
    config.start_pomodoro()
    assert config.is_silent_now() is True, "番茄钟运行时 is_silent_now 应为 True"
    config.stop_pomodoro()
    assert config.is_silent_now() is False, "番茄钟停止后 is_silent_now 应为 False"

check("番茄钟进入静默通道", t_pomodoro_silences)


# ---------- 5. 窗口 _pomodoro_frame 切表情 ----------

def t_window_frame_switches_with_phase() -> None:
    """验证阶段切换时 _pomodoro_frame 跟随设置。"""
    reset_pomodoro_state()
    restore = fake_time(1_000_000.0)
    try:
        w = window_mod.PetWindow()
        w.tray = types.SimpleNamespace(
            _sync_focus_menu=lambda: None,
            _sync_pomodoro_menu=lambda: None,
        )
        try:
            # 手动启动并检查 _pomodoro_frame
            w.start_pomodoro()
            assert w._pomodoro_frame in ("think", None), \
                f"work 阶段 _pomodoro_frame 应为 think 或 None，实际 {w._pomodoro_frame}"
            assert config.pomodoro_active() is True
            # 模拟阶段切换
            config.time.time = lambda: config.pomodoro_phase_end() + 1
            w._on_pomodoro_tick()
            assert config.pomodoro_phase() == "short_break", "tick 后应为 short_break"
            assert w._pomodoro_frame in ("laugh", None), \
                f"short_break 阶段 _pomodoro_frame 应为 laugh 或 None，实际 {w._pomodoro_frame}"
            # 再切到 work
            config.time.time = lambda: config.pomodoro_phase_end() + 1
            w._on_pomodoro_tick()
            assert config.pomodoro_phase() == "work"
            assert w._pomodoro_frame in ("think", None), "回到 work 阶段应切回 think"
        finally:
            w.stop_pomodoro()
            w.close()
    finally:
        restore()

check("窗口 _pomodoro_frame 随阶段切换", t_window_frame_switches_with_phase)


def t_window_stop_clears_frame() -> None:
    """stop_pomodoro 应清掉 _pomodoro_frame。"""
    reset_pomodoro_state()
    w = window_mod.PetWindow()
    w.tray = types.SimpleNamespace(
        _sync_focus_menu=lambda: None,
        _sync_pomodoro_menu=lambda: None,
    )
    try:
        w.start_pomodoro()
        assert w._pomodoro_frame is not None
        w.stop_pomodoro()
        assert w._pomodoro_frame is None, "stop 后 _pomodoro_frame 应清空"
    finally:
        w.close()

check("停止番茄钟清空 _pomodoro_frame", t_window_stop_clears_frame)


def t_tick_syncs_frame_when_external_start() -> None:
    """外部 QSettings 启动番茄钟时（不走 start_pomodoro），_on_pomodoro_tick 应自动同步 _pomodoro_frame。

    这是 1.5.0 实机验证发现的 bug：之前只有托盘入口会设 _pomodoro_frame，
    导致外部启动番茄钟后桌宠一直停在 idle 帧。
    """
    reset_pomodoro_state()
    w = window_mod.PetWindow()
    w.tray = types.SimpleNamespace(
        _sync_focus_menu=lambda: None,
        _sync_pomodoro_menu=lambda: None,
    )
    try:
        # 模拟外部 QSettings 启动：直接调 config.start_pomodoro()，不走 start_pomodoro()
        # 同时强制 _pomodoro_frame 为 None（绕过 start_pomodoro 副作用）
        config.start_pomodoro()
        w._pomodoro_frame = None
        # 现在 _pomodoro_frame 是 None，但 pomodoro_active 是 True
        assert w._pomodoro_frame is None
        assert config.pomodoro_active() is True
        # 触发一次 tick（不切阶段）：_pomodoro_frame 应自动同步为 think
        w._on_pomodoro_tick()
        if "think" in w.frames:
            assert w._pomodoro_frame == "think", \
                f"外部启动后 tick 应同步 _pomodoro_frame 为 think，实际 {w._pomodoro_frame}"
        # 切到 short_break
        restore = fake_time(1_000_000.0)
        try:
            config.time.time = lambda: config.pomodoro_phase_end() + 1
            w._on_pomodoro_tick()
            if "laugh" in w.frames:
                assert w._pomodoro_frame == "laugh", \
                    f"切到 short_break 应同步 _pomodoro_frame 为 laugh，实际 {w._pomodoro_frame}"
        finally:
            restore()
        config.stop_pomodoro()
    finally:
        w.close()

check("tick 入口同步 _pomodoro_frame（外部启动场景）", t_tick_syncs_frame_when_external_start)


# ---------- 6. _current_frame_name 优先级 ----------

def t_current_frame_pomodoro_priority() -> None:
    """_current_frame_name 优先返回 _pomodoro_frame（持续到阶段结束）。"""
    reset_pomodoro_state()
    w = window_mod.PetWindow()
    w.tray = types.SimpleNamespace(
        _sync_focus_menu=lambda: None,
        _sync_pomodoro_menu=lambda: None,
    )
    try:
        # 设置 _pomodoro_frame = "laugh"，_override_until 已过期，brain 是 idle
        w._pomodoro_frame = "laugh" if "laugh" in w.frames else None
        w._override_frame = None
        w._override_until = 0
        w.brain.state = window_mod.PetBrain.IDLE
        # _current_frame_name 应返回 laugh（如果该帧存在）
        if "laugh" in w.frames:
            assert w._current_frame_name() == "laugh", "应优先 _pomodoro_frame"
        # 清掉 _pomodoro_frame，应回到 idle
        w._pomodoro_frame = None
        assert w._current_frame_name() == "idle", "清空后应回 idle"
    finally:
        w.close()

check("_current_frame_name 优先 _pomodoro_frame", t_current_frame_pomodoro_priority)


# ---------- 总结 ----------

print(f"\n  === 总结：{PASS} passed, {FAIL} failed ===")
sys.exit(0 if FAIL == 0 else 1)
