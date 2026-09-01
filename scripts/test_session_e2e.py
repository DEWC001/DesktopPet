"""锁屏感知端到端测试：真窗口 + 真发 WM_WTSSESSION_CHANGE。

前面的 test_session_monitor.py 跑在 offscreen 下，窗口没有真实 HWND，
注册必然失败，验证不到最关键的一环：Qt 的 nativeEvent 到底能不能收到
系统消息、parse_message 能不能正确解析 PySide6 传进来的那个对象。

这里绕开「真的去锁屏」（会打断用户），改用 SendMessage 直接把
WM_WTSSESSION_CHANGE 投递给已注册的窗口，效果等价且可自动化。

注意：必须在**真实桌面平台**运行（不能设 QT_QPA_PLATFORM=offscreen），
窗口会被临时挪到屏幕外，不影响用户。

运行：
    python scripts/test_session_e2e.py
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctypes import wintypes  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from pet import config  # noqa: E402
from pet import session_monitor as sm  # noqa: E402

PASS = 0
FAIL = 0


def check(name, fn):
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


_user32 = ctypes.WinDLL("user32")
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.SendMessageW.restype = wintypes.LPARAM


def send_session_message(hwnd: int, kind: str) -> None:
    """向窗口投递一条会话变更消息（等价于系统锁屏/解锁时发的那条）。"""
    wparam = sm.WTS_SESSION_LOCK if kind == "lock" else sm.WTS_SESSION_UNLOCK
    _user32.SendMessageW(
        wintypes.HWND(hwnd), sm.WM_WTSSESSION_CHANGE, wintypes.WPARAM(wparam), wintypes.LPARAM(0)
    )


def main() -> int:
    from pet.window import PetWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    print("== 环境 ==")
    print(f"  session_monitor.available() = {sm.available()}")

    window = PetWindow()
    window.move(-3000, -3000)     # 挪到屏幕外，别打扰用户
    window.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)

    hwnd = int(window.winId())
    print(f"  PetWindow hwnd = {hwnd}")
    if hwnd == 0:
        print("  FAIL  拿不到真实 HWND（是否误设了 offscreen？）")
        return 1

    check("会话通知注册成功", lambda: assert_true(sm.register(hwnd), "register() 应返回 True"))

    def t_lock():
        app.processEvents()
        assert_true(not window._away, "初始应不在离开态")
        send_session_message(hwnd, "lock")
        app.processEvents()
        assert_true(window._away, "收到锁屏消息后应进入离开态")
        assert_true(config.is_away(), "config 应标记 away")
        assert_true(config.is_silent_now(), "离开时应静默")
        assert_true(not window.sit_timer.isActive(), "久坐计时应暂停")

    check("收到锁屏消息 → 进入静默", t_lock)

    def t_unlock():
        send_session_message(hwnd, "unlock")
        app.processEvents()
        assert_true(not window._away, "收到解锁消息后应退出离开态")
        assert_true(not config.is_away(), "config 应清除 away")
        assert_true(not config.is_silent_now(), "回来后不应继续静默")

    check("收到解锁消息 → 恢复正常", t_unlock)

    def t_roundtrip():
        """连续两次锁→解，确认状态机不会卡住。"""
        for _ in range(2):
            send_session_message(hwnd, "lock")
            app.processEvents()
            assert_true(window._away, "应进入离开态")
            send_session_message(hwnd, "unlock")
            app.processEvents()
            assert_true(not window._away, "应退出离开态")

    check("连续锁屏/解锁不卡死", t_roundtrip)

    def t_irrelevant_message():
        """投递无关消息不能误触发离开态。"""
        _user32.SendMessageW(wintypes.HWND(hwnd), 0x0002, wintypes.WPARAM(0), wintypes.LPARAM(0))
        app.processEvents()
        assert_true(not window._away, "无关消息不应触发离开态")

    check("无关消息不误触发", t_irrelevant_message)

    # 收尾：注销 + 关闭
    sm.unregister(hwnd)
    window.close()
    app.processEvents()

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
