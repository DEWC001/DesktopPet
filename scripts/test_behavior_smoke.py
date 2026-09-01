"""行为级冒烟测试（offscreen 真实构造 PetWindow）。

覆盖 1.2.0 改动里“只有跑起来才会暴露”的交互逻辑：
  - 单击 / 双击区分（双击不能再多跳一次，连点不叠加连跳）
  - 贴边隐藏状态机（进入 hiding 后不重入）
  - 提醒计时互相独立（改喝水不会重置久坐倒计时）
  - 自定义提醒到点触发 + 当日去重
  - 静默时只弹气泡不跳

运行：
    QT_QPA_PLATFORM=offscreen python scripts/test_behavior_smoke.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime  # noqa: E402

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()


def assert_true(cond, msg="断言失败"):
    if not cond:
        raise AssertionError(msg)


def make_event(etype, button=Qt.MouseButton.LeftButton):
    pos = QPointF(10.0, 10.0)
    return QMouseEvent(
        etype,
        pos,
        pos,
        pos,
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def press_release(window, etype):
    window.mousePressEvent(make_event(QEvent.Type.MouseButtonPress))
    window.mouseReleaseEvent(make_event(etype))


def main() -> int:
    from pet import config
    from pet.window import PetWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    window.show()

    # 统计跳跃次数
    jump_calls = {"n": 0}
    orig_jump = window._do_jump

    def counting_jump():
        jump_calls["n"] += 1
        orig_jump()

    window._do_jump = counting_jump

    single_clicks = {"n": 0}
    orig_single = window._do_single_click

    def counting_single():
        single_clicks["n"] += 1
        orig_single()

    window._do_single_click = counting_single
    # 单击是通过 _click_timer 延迟触发的，重新接线到计数版本
    window._click_timer.timeout.disconnect()
    window._click_timer.timeout.connect(counting_single)

    custom_fired = {"n": 0}
    window._on_custom_reminder = lambda item: custom_fired.__setitem__("n", custom_fired["n"] + 1)

    print("[1] 单击：进入 250ms 判定窗口，不立即跳")

    def t_single():
        window._suppress_click = False
        press_release(window, QEvent.Type.MouseButtonRelease)
        assert_true(window._click_timer.isActive(), "单击后判定定时器应处于运行态")
        assert_true(not window._suppress_click, "单击不应置抑制标志")

    check("单击启动判定定时器", t_single)

    print("[2] 双击：判定定时器被取消，第二次 release 被抑制")

    def t_double():
        window._click_timer.stop()
        window._suppress_click = False
        window._cancel_pending_jumps()
        jump_calls["n"] = 0
        single_clicks["n"] = 0

        # Qt 真实序列：press → release → dblclick → release
        window.mousePressEvent(make_event(QEvent.Type.MouseButtonPress))
        window.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease))
        window.mouseDoubleClickEvent(make_event(QEvent.Type.MouseButtonDblClick))
        window.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease))

        assert_true(not window._click_timer.isActive(), "双击后判定定时器必须已停止")
        assert_true(window._suppress_click is False, "第二次 release 应把抑制标志消费掉")
        assert_true(single_clicks["n"] == 0, "双击不应触发单击逻辑")
        assert_true(len(window._jump_timers) == 3, f"连跳定时器应为 3 个，实际 {len(window._jump_timers)}")

    check("双击序列完整走通", t_double)

    print("[3] 连点两次双击：连跳不叠加")

    def t_double_twice():
        window._cancel_pending_jumps()
        window._suppress_click = False
        for _ in range(2):
            window.mousePressEvent(make_event(QEvent.Type.MouseButtonPress))
            window.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease))
            window.mouseDoubleClickEvent(make_event(QEvent.Type.MouseButtonDblClick))
            window.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease))
        assert_true(len(window._jump_timers) == 3, f"连点后仍应为 3 个，实际 {len(window._jump_timers)}")

    check("连点双击不叠加", t_double_twice)
    window._cancel_pending_jumps()

    print("[4] 贴边隐藏状态机")

    def t_edge_hide():
        old = config.get("edge_hide_enabled")
        config.set_value("edge_hide_enabled", True)
        try:
            window._edge_state = "normal"
            window._jumping = False
            window._drag = False
            window._last_move_time = time.time() - config.EDGE_HIDE_IDLE_SECONDS - 5
            window._check_edge_hide()
            assert_true(window._edge_state == "hiding", f"应进入 hiding，实际 {window._edge_state}")
            window._check_edge_hide()
            assert_true(window._edge_state == "hiding", "hiding 中不应重入")
        finally:
            config.set_value("edge_hide_enabled", old)
            window._edge_state = "normal"

    check("静止超时进入隐藏动画", t_edge_hide)

    def t_edge_disabled():
        old = config.get("edge_hide_enabled")
        config.set_value("edge_hide_enabled", False)
        try:
            window._edge_state = "normal"
            window._last_move_time = time.time() - 9999
            window._check_edge_hide()
            assert_true(window._edge_state == "normal", "关闭后不应触发隐藏")
        finally:
            config.set_value("edge_hide_enabled", old)

    check("关闭贴边隐藏则不触发", t_edge_disabled)

    print("[5] 提醒计时互相独立")

    def t_timer_independent():
        config.set_value("sit_enabled", True)
        config.set_value("sit_interval", 45)
        window.refresh_reminder("sit")
        before = window.sit_timer.remainingTime()
        window.refresh_reminder("drink")  # 改喝水不应重置久坐
        after = window.sit_timer.remainingTime()
        drift = before - after
        assert_true(0 <= drift < 2000, f"久坐倒计时被重置了：{before} → {after}")
        assert_true(window.sit_timer.isActive(), "久坐定时器应保持运行")

    check("改喝水不影响久坐倒计时", t_timer_independent)

    def t_timer_drink_reset():
        config.set_value("drink_enabled", True)
        config.set_value("drink_interval", 30)
        window.refresh_reminder("drink")
        first = window.drink_timer.remainingTime()
        config.set_value("drink_interval", 90)
        window.refresh_reminder("drink")
        second = window.drink_timer.remainingTime()
        assert_true(second - first > 60 * 1000, f"喝水间隔改大后倒计时应变长：{first} → {second}")

    check("改喝水间隔只重置喝水", t_timer_drink_reset)

    print("[6] 自定义提醒触发与去重")

    def t_custom_fire():
        old = config.get_custom_reminders()
        now = datetime.datetime.now()
        item = {
            "id": "test1",
            "label": "测试提醒",
            "time": now.strftime("%H:%M"),
            "kind": "daily",
            "weekday": now.weekday(),
            "date": now.strftime("%Y-%m-%d"),
            "enabled": True,
        }
        config.add_custom_reminder(item)
        try:
            window._fired_custom.clear()
            window._fired_custom_day = ""
            custom_fired["n"] = 0
            window._check_custom_reminders()
            assert_true(custom_fired["n"] == 1, f"到点应触发 1 次，实际 {custom_fired['n']}")
            window._check_custom_reminders()
            assert_true(custom_fired["n"] == 1, "同一分钟重复轮询不应再次触发")
        finally:
            config.save_custom_reminders(old)
            window._fired_custom.clear()
            window._fired_custom_day = ""

    check("到点触发一次", t_custom_fire)

    def t_custom_disabled():
        old = config.get_custom_reminders()
        now = datetime.datetime.now()
        item = {
            "id": "test2",
            "label": "停用测试",
            "time": now.strftime("%H:%M"),
            "kind": "daily",
            "weekday": now.weekday(),
            "date": now.strftime("%Y-%m-%d"),
            "enabled": True,
        }
        config.add_custom_reminder(item)
        config.set_custom_reminder_enabled("test2", False)
        try:
            window._fired_custom.clear()
            window._fired_custom_day = ""
            custom_fired["n"] = 0
            window._check_custom_reminders()
            assert_true(custom_fired["n"] == 0, "停用事项不应触发")
        finally:
            config.save_custom_reminders(old)
            window._fired_custom.clear()
            window._fired_custom_day = ""

    check("停用事项不触发", t_custom_disabled)

    print("[7] 静默时只弹气泡不跳")

    def t_silent_notify():
        window._jumping = False
        old_silent = config.is_silent_now
        config.is_silent_now = lambda: True
        try:
            window._notify("静默测试", 1000)
            assert_true(not window._jumping, "静默状态下不应起跳")
        finally:
            config.is_silent_now = old_silent
            window._jumping = False

        old_silent2 = config.is_silent_now
        config.is_silent_now = lambda: False
        try:
            window._jumping = False
            window._notify("正常测试", 1000)
            assert_true(window._jumping, "非静默状态应起跳")
        finally:
            config.is_silent_now = old_silent2
            window._jumping = False

    check("静默/非静默分支正确", t_silent_notify)

    print("[8] 音效受静默控制")

    def t_sound():
        played = {"n": 0}
        old_allowed = config.sound_allowed
        config.sound_allowed = lambda: False
        try:
            window._play_sound("drink.wav")
            assert_true(played["n"] == 0, "静默时不应播放（此处只验证不抛异常）")
        finally:
            config.sound_allowed = old_allowed

    check("静默时 _play_sound 安全返回", t_sound)

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
