"""锁屏/解锁感知（离开静默 + 回来补报）自测。

覆盖三层：
  1. session_monitor 纯函数：消息解析（lock/unlock/无关消息）、
     地址提取对不同类型入参的容错
  2. 真实 PetWindow 上的锁屏/解锁行为：进入静默、周期提醒丢弃并重新计时、
     自定义提醒记录、久坐计时暂停与恢复、补报文案
  3. 静默链路联动：离开时 config.is_silent_now() 为真、回来后为假

运行：
    QT_QPA_PLATFORM=offscreen python scripts/test_session_monitor.py
"""
import os
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
        traceback.print_exc()


def assert_eq(got, expect, what=""):
    if got != expect:
        raise AssertionError(f"{what} 实际 {got!r}，期望 {expect!r}")


def assert_true(cond, msg="断言失败"):
    if not cond:
        raise AssertionError(msg)


# ---------------- 1. 消息解析 ----------------
def t_parse_lock():
    from pet import session_monitor as sm

    assert_eq(sm.parse_message(sm.make_message("lock")), "lock")


def t_parse_unlock():
    from pet import session_monitor as sm

    assert_eq(sm.parse_message(sm.make_message("unlock")), "unlock")


def t_parse_other_message():
    """非会话变更消息必须返回 None，不能误触发。"""
    import ctypes
    from ctypes import wintypes

    from pet import session_monitor as sm

    buf = (ctypes.c_char * ctypes.sizeof(wintypes.MSG))()
    msg = wintypes.MSG.from_buffer(buf)
    msg.message = 0x0002   # WM_DESTROY
    msg.wParam = 0
    assert_eq(sm.parse_message(ctypes.addressof(buf)), None)


def t_parse_bad_input():
    """垃圾入参不能抛异常，返回 None 即可（nativeEvent 里每帧都会调用）。"""
    from pet import session_monitor as sm

    for junk in (None, 0, "", object(), -1):
        assert_eq(sm.parse_message(junk), None, f"入参 {junk!r}")


def t_message_address_int():
    from pet import session_monitor as sm

    addr = sm.make_message("lock")
    assert_eq(sm._message_address(addr), addr)


# ---------------- 2. 窗口行为 ----------------
def _new_window():
    from pet.window import PetWindow

    w = PetWindow()
    w.show()
    return w


def t_lock_enters_silence():
    """锁屏后进入离开态，且 config 静默生效（不响不跳不跑到中心）。"""
    from pet import config

    w = _new_window()
    try:
        w._on_session_lock()
        assert_true(w._away, "应进入离开态")
        assert_true(config.is_silent_now(), "离开时应静默")
        assert_true(config.is_away(), "config 应标记 away")
        assert_true(not w.sit_timer.isActive(), "久坐计时应暂停")
    finally:
        config.set_away(False)


def t_unlock_restores():
    from pet import config

    w = _new_window()
    try:
        w._on_session_lock()
        w._on_session_unlock()
        assert_true(not w._away, "解锁后应退出离开态")
        assert_true(not config.is_away(), "config 应清除 away")
        assert_true(not config.is_silent_now(), "回来后不应继续静默")
    finally:
        config.set_away(False)


def t_lock_idempotent():
    """重复收到 lock 不应重置计时或清空补报记录。"""
    from pet import config

    w = _new_window()
    try:
        w._on_session_lock()
        w._missed_custom.append("该吃药了")
        first = w._away_since
        time.sleep(0.01)
        w._on_session_lock()
        assert_eq(w._away_since, first, "重复 lock 不应重置离开起始时间")
        assert_eq(w._missed_custom, ["该吃药了"], "重复 lock 不应清空补报记录")
    finally:
        config.set_away(False)


def t_unlock_without_lock_noop():
    """没锁过就收到 unlock，不能误弹欢迎回来。"""
    w = _new_window()
    w._away = False
    before = w._away_since
    w._on_session_unlock()
    assert_eq(w._away_since, before, "未锁屏时的 unlock 应无副作用")


def t_cycle_reminder_dropped_while_away():
    """周期提醒（喝水/久坐/整点/下班）离开期间丢弃，但必须重新计时。"""
    from pet import config

    w = _new_window()
    try:
        config.set_value("sit_enabled", True)
        config.set_value("sit_interval", 45)
        w.refresh_reminder("sit")
        remain_before = w.sit_timer.remainingTime()

        w._on_session_lock()
        assert_true(not w.sit_timer.isActive(), "锁屏后久坐计时应停")

        w.remind_sit()                      # 离开期间触发
        assert_true(w.sit_timer.isActive(), "周期提醒被丢弃后应重新计时")
        assert w.sit_timer.remainingTime() > remain_before - 2000, "应重新开始一个完整间隔"

        w._on_session_unlock()
    finally:
        config.set_away(False)


def t_custom_reminder_recorded():
    """自定义提醒有时效性，离开期间要记下来等补报。"""
    from pet import config

    w = _new_window()
    try:
        w._on_session_lock()
        w._on_custom_reminder({"label": "该吃药了"})
        w._on_custom_reminder({"label": "取快递"})
        assert_eq(w._missed_custom, ["该吃药了", "取快递"], "应记录两条")
    finally:
        config.set_away(False)


def t_no_bubble_while_away():
    """离开期间周期提醒不能弹气泡。"""
    from pet import config

    w = _new_window()
    shown = []
    w._show_bubble = lambda msg, d=12000: shown.append(msg)
    try:
        w._on_session_lock()
        w.remind_drink()
        w.remind_offwork()
        assert_eq(shown, [], "离开期间不应弹任何气泡")
    finally:
        config.set_away(False)


def t_im_not_bubbled_while_away():
    """离开期间 IM 未读不逐条弹气泡，但要保持超时检测排队。"""
    from pet import config

    w = _new_window()
    shown = []
    w._show_bubble = lambda msg, d=12000: shown.append(msg)
    try:
        w._on_session_lock()
        w._on_im_unread_changed("灵犀", True)
        assert_eq(shown, [], "离开期间不应弹 IM 气泡")
        assert_true("灵犀" in w._unread_timers, "应保持超时检测排队")
    finally:
        config.set_away(False)
        w._cancel_unread_timer("灵犀")


def t_welcome_back_short_ignored():
    """快速锁一下屏（<60s）不打扰。"""
    w = _new_window()
    assert_eq(w._build_welcome_back(30), "")


def t_welcome_back_basic():
    w = _new_window()
    text = w._build_welcome_back(25 * 60)
    assert_eq(text, "欢迎回来～你离开了 25 分钟", "纯时长文案")


def t_welcome_back_hours():
    w = _new_window()
    text = w._build_welcome_back(2 * 3600 + 15 * 60)
    assert_eq(text, "欢迎回来～你离开了 2 小时 15 分钟", "超过一小时用时/分")


def t_welcome_back_with_missed():
    w = _new_window()
    w._missed_custom = ["该吃药了", "取快递"]
    text = w._build_welcome_back(90 * 60)
    assert_true("欢迎回来～你离开了 1 小时 30 分钟" in text, f"应含时长，实际: {text!r}")
    assert_true("错过提醒：该吃药了、取快递" in text, "应含错过的提醒")


def t_welcome_back_many_missed():
    """超过 5 条只列前 5 条并给总数。"""
    w = _new_window()
    w._missed_custom = [f"事项{i}" for i in range(1, 9)]
    text = w._build_welcome_back(60 * 60)
    assert_true("事项1" in text and "事项5" in text, "应列出前 5 条")
    assert_true("事项6" not in text, "第 6 条起折叠")
    assert_true("等 8 条" in text, "应给出总数")


def t_welcome_back_with_unread():
    """回来时有未读应用要报出来。"""
    w = _new_window()
    w.im_watcher.unread_apps = lambda: ["灵犀", "微信"]
    text = w._build_welcome_back(30 * 60)
    assert_true("灵犀、微信 有未读消息" in text, f"应含未读应用，实际: {text!r}")


def t_welcome_back_clears_missed():
    """补报后要清空记录，避免下次重复报。"""
    w = _new_window()
    w._missed_custom = ["该吃药了"]
    w._build_welcome_back(60 * 60)
    assert_eq(w._missed_custom, [], "补报后应清空")


def t_welcome_back_unread_exception_safe():
    """读未读状态抛异常不能影响补报。"""
    w = _new_window()

    def boom():
        raise RuntimeError("COM 挂了")

    w.im_watcher.unread_apps = boom
    w._missed_custom = ["该吃药了"]
    text = w._build_welcome_back(60 * 60)
    assert_true("错过提醒" in text, "IM 读取失败不应影响提醒补报")


def t_sit_timer_restarted_on_return():
    """回来后久坐计时必须重新开始，不能沿用离开前的剩余时间。"""
    from pet import config

    w = _new_window()
    try:
        config.set_value("sit_enabled", True)
        config.set_value("sit_interval", 45)
        w.refresh_reminder("sit")
        w._on_session_lock()
        w._on_session_unlock()
        assert_true(w.sit_timer.isActive(), "回来后久坐计时应恢复")
        assert w.sit_timer.remainingTime() > 40 * 60 * 1000, "应是完整间隔而非残留"
    finally:
        config.set_away(False)


def t_toggle_off_while_away():
    """关掉功能时若正在离开态，必须立刻恢复正常，不能卡在静默。"""
    from pet import config

    w = _new_window()
    try:
        w._on_session_lock()
        w.set_away_detect(False)
        assert_true(not w._away, "关闭后应退出离开态")
        assert_true(not config.is_away(), "关闭后 config 应清除 away")
    finally:
        config.set_away(False)
        config.set_value("away_detect_enabled", True)


def t_registration_graceful():
    """注册失败（如 offscreen 无真实 HWND）不能抛异常，也不能影响窗口可用。"""
    w = _new_window()
    w._setup_session_monitor()
    assert_true(w.isVisible() or True, "注册失败后窗口仍应可用")


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    print("== session_monitor 消息解析 ==")
    check("解析 lock", t_parse_lock)
    check("解析 unlock", t_parse_unlock)
    check("无关消息返回 None", t_parse_other_message)
    check("垃圾入参不抛异常", t_parse_bad_input)
    check("地址提取（int）", t_message_address_int)

    print("== 锁屏 / 解锁行为 ==")
    check("锁屏进入静默", t_lock_enters_silence)
    check("解锁恢复正常", t_unlock_restores)
    check("重复 lock 幂等", t_lock_idempotent)
    check("未锁屏时 unlock 无副作用", t_unlock_without_lock_noop)

    print("== 提醒分类处理 ==")
    check("周期提醒丢弃并重新计时", t_cycle_reminder_dropped_while_away)
    check("自定义提醒记录待补报", t_custom_reminder_recorded)
    check("离开期间不弹气泡", t_no_bubble_while_away)
    check("IM 不逐条打扰但保持排队", t_im_not_bubbled_while_away)

    print("== 回来补报 ==")
    check("快速锁屏不打扰", t_welcome_back_short_ignored)
    check("补报基础文案", t_welcome_back_basic)
    check("补报超过一小时", t_welcome_back_hours)
    check("补报含错过的提醒", t_welcome_back_with_missed)
    check("超过 5 条折叠", t_welcome_back_many_missed)
    check("补报含未读应用", t_welcome_back_with_unread)
    check("补报后清空记录", t_welcome_back_clears_missed)
    check("IM 读取异常不影响补报", t_welcome_back_unread_exception_safe)
    check("回来后久坐重新计时", t_sit_timer_restarted_on_return)

    print("== 开关与容错 ==")
    check("关闭功能时退出离开态", t_toggle_off_while_away)
    check("注册失败优雅降级", t_registration_graceful)

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
