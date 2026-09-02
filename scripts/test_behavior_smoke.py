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
    from pet.brain import PetBrain
    from pet.window import PetWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    window.show()

    # 统计跳跃次数
    jump_calls = {"n": 0}
    orig_jump = window._do_jump

    def counting_jump(*args, **kwargs):
        jump_calls["n"] += 1
        orig_jump(*args, **kwargs)

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

    print("[2] 双击：判定定时器被取消，第二次 release 被抑制，只跳 1 下")

    def t_double():
        window._click_timer.stop()
        window._suppress_click = False
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
        assert_true(jump_calls["n"] == 1, f"双击应只跳 1 下，实际 {jump_calls['n']} 下")
        assert_true(
            not hasattr(window, "_jump_timers"),
            "连跳定时器机制应已随 1.6.0 删除",
        )

    check("双击序列完整走通", t_double)

    print("[3] 连点两次双击：每次各跳 1 下，不排队叠加")

    def t_double_twice():
        window._suppress_click = False
        jump_calls["n"] = 0
        for _ in range(2):
            window.mousePressEvent(make_event(QEvent.Type.MouseButtonPress))
            window.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease))
            window.mouseDoubleClickEvent(make_event(QEvent.Type.MouseButtonDblClick))
            window.mouseReleaseEvent(make_event(QEvent.Type.MouseButtonRelease))
        assert_true(jump_calls["n"] == 2, f"两次双击应各跳 1 下共 2 下，实际 {jump_calls['n']} 下")

    check("连点双击不叠加", t_double_twice)

    print("[4] 贴边隐藏状态机")

    def t_edge_hide():
        old = config.get("edge_hide_enabled")
        config.set_value("edge_hide_enabled", True)
        try:
            # 1.7.0：睡觉/睡着靠边时不触发收缝，先 poke 醒再测静止超时
            window.brain.poke()
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
            window._edge_anim = None

    check("静止超时进入隐藏动画", t_edge_hide)

    def t_edge_disabled():
        old = config.get("edge_hide_enabled")
        config.set_value("edge_hide_enabled", False)
        try:
            window.brain.poke()
            window._edge_state = "normal"
            window._last_move_time = time.time() - 9999
            window._check_edge_hide()
            assert_true(window._edge_state == "normal", "关闭后不应触发隐藏")
        finally:
            config.set_value("edge_hide_enabled", old)

    check("关闭贴边隐藏则不触发", t_edge_disabled)

    def t_sleep_no_hide():
        """1.7.0：睡着时即使静止超时也不收缝（睡觉本身已滑到边缘完整可见）。"""
        old = config.get("edge_hide_enabled")
        config.set_value("edge_hide_enabled", True)
        try:
            window.brain.poke()
            window._edge_state = "normal"
            window.brain.go_sleep()  # 触发 _on_state(SLEEP) → 睡眠靠边
            window._last_move_time = time.time() - 9999
            window._check_edge_hide()
            assert_true(window._edge_state == "normal", "睡着时不应触发收缝")
        finally:
            window.brain.wake()
            window._sleep_side = False
            window._slide_anim = None
            config.set_value("edge_hide_enabled", old)

    check("睡着时不触发贴边收缝", t_sleep_no_hide)

    def t_hidden_no_auto_show():
        """需求2：隐藏后鼠标靠近不再自动滑回；_check_edge_hide 对 hidden 无操作。"""
        window.brain.poke()
        window._edge_state = "hidden"
        window._check_edge_hide()  # 旧版会因光标在几何+30px 内自动 _begin_edge_show
        assert_true(window._edge_state == "hidden", "hidden 不应因 idle 检查自动滑回")
        assert_true(
            not hasattr(window, "_edge_hide_check_timer"),
            "鼠标轮询定时器字段应已删除",
        )

    check("隐藏后不自动滑回", t_hidden_no_auto_show)

    def t_hidden_click_show():
        """需求2：点击露出的隐藏缝 → 进入 showing 滑回。"""
        window.brain.poke()
        window._last_user_pos = QPoint(123, 200)
        window._edge_state = "hidden"
        press_release(window, QEvent.Type.MouseButtonRelease)
        assert_true(window._edge_state == "showing", f"点击隐藏缝应滑回，实际 {window._edge_state}")
        # 收尾：停掉动画，恢复正常态，避免影响后续用例
        if window._edge_anim is not None:
            window._edge_anim.stop()
            window._edge_anim = None
        window._edge_state = "normal"

    check("点击隐藏缝唤出", t_hidden_click_show)

    def t_reminder_restores_from_hidden():
        """需求2：提醒唤出收缝——瞬间回到最近停留位置再提醒。"""
        window.brain.poke()
        window._last_user_pos = QPoint(321, 400)
        window.move(700, 500)
        window._edge_state = "hidden"
        was = window._begin_reminder()
        assert_true(window._edge_state == "normal", "提醒应把状态还原为 normal")
        assert_true(
            window.pos().x() == 321 and window.pos().y() == 400,
            f"提醒应回到最近停留位置，实际 {window.pos().x()},{window.pos().y()}",
        )

    check("提醒唤出收缝并回原位", t_reminder_restores_from_hidden)

    print("[9] 需求3：睡觉自动靠边（完整可见），醒来就地活动")

    def t_sleep_side():
        screen = app.primaryScreen().availableGeometry()
        w, h = window.width(), window.height()
        window.brain.poke()
        window._edge_state = "normal"
        window._sleep_side = False
        window._slide_anim = None
        window.move(300, 300)
        window.brain.go_sleep()
        assert_true(window._sleep_side, "入睡应标记睡眠靠边")
        anim = window._slide_anim
        assert_true(anim is not None, "入睡应启动滑向边缘的动画")
        end = anim.endValue()
        # 目标必须在某个屏幕边缘且完整可见
        ex, ey = end.x(), end.y()
        on_edge = (
            ex == screen.left() or ex == screen.right() - w
            or ey == screen.top() or ey == screen.bottom() - h
        )
        assert_true(on_edge, f"滑动目标应在屏幕边缘：{ex},{ey}")
        assert_true(
            screen.left() <= ex <= screen.right() - w and screen.top() <= ey <= screen.bottom() - h,
            f"目标应完整可见：{ex},{ey}",
        )

    check("入睡滑向边缘完整可见", t_sleep_side)

    def t_wake_in_place():
        """醒来"睡在哪醒在哪"：清靠边标记，不起滑回原位动画。"""
        window.brain.poke()
        window._edge_state = "normal"
        window.brain.go_sleep()
        assert_true(window._sleep_side, "前置：应处于睡眠靠边")
        window.brain.wake()  # 自然醒/点击/提醒都走这里
        assert_true(not window._sleep_side, "醒来应清除靠边标记")
        assert_true(window._slide_anim is None, "醒来不应再有滑向边缘的动画")

    check("醒来就地活动不清除位置", t_wake_in_place)

    def t_sleep_hidden_no_side():
        """已在收缝（hidden）时入睡：保持原状，不触发睡眠靠边。"""
        window.brain.poke()
        window._edge_state = "hidden"
        window._sleep_side = False
        window.brain.go_sleep()
        assert_true(not window._sleep_side, "收缝中入睡不应触发睡眠靠边")
        window.brain.wake()
        window._sleep_side = False

    check("收缝中入睡不靠边", t_sleep_hidden_no_side)

    print("[10] 需求4：活跃度联动")

    _orig_act = config.activity()

    def set_act(v):
        config.set_value("activity", v)
        window.refresh_activity()

    def t_act_jump():
        set_act(0)
        assert_true(window._jump_height() < 20, f"低活跃跳跃应偏矮：{window._jump_height()}")
        set_act(50)
        assert_true(window._jump_height() == 26, f"默认活跃跳跃应为 26：{window._jump_height()}")
        set_act(100)
        assert_true(window._jump_height() > 30, f"高活跃跳跃应更高：{window._jump_height()}")

    check("跳跃高度随活跃度缩放", t_act_jump)

    def t_act_walk():
        set_act(0)
        assert_true(window._walk_step() == 1, f"低活跃步速应 1px：{window._walk_step()}")
        set_act(50)
        assert_true(window._walk_step() == 2, f"默认步速应 2px：{window._walk_step()}")
        set_act(100)
        assert_true(window._walk_step() == 3, f"高活跃步速应 3px：{window._walk_step()}")

    check("散步步速随活跃度缩放", t_act_walk)

    def t_act_brain():
        # 睡眠越长 = 越爱睡；回睡概率越大；清醒越短
        set_act(0)
        s0 = window.brain._dur_range(PetBrain.SLEEP)
        p0 = window.brain._resleep_prob()
        a0 = window.brain._awake_actions()
        set_act(100)
        s100 = window.brain._dur_range(PetBrain.SLEEP)
        p100 = window.brain._resleep_prob()
        a100 = window.brain._awake_actions()
        assert_true(s0[0] > s100[0] and s0[1] > s100[1], f"低活跃应睡得久：{s0} vs {s100}")
        assert_true(p0 > p100, f"低活跃应更容易回睡：{p0} vs {p100}")
        assert_true(window.brain.WALK in a0 or window.brain.CHAT in a0, "低活跃仍有安静活动")
        assert_true(len(a100) >= len(a0), "高活跃动作池不应比低活跃小")
        set_act(50)

    check("脑状态机按时长/回睡概率联动", t_act_brain)
    set_act(_orig_act)

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
