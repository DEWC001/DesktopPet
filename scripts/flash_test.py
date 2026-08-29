"""自主验证桌宠 IM 未读检测链路（无需用户配合）。

原理：真实灵犀消息会让任务栏按钮 Help 变「已请求注意」（已诊断证实）。
FlashWindowEx 触发的是同一套 flashFrame 机制，可等价注入测试信号：
  1. 读当前灵犀任务栏按钮 Help（应为空）
  2. FlashWindowEx 灵犀主窗口 → 任务栏按钮 Help 应变「已请求注意」
  3. 桌宠 2 秒轮询应检测到 → 日志出现「IM 未读变化: 灵犀 -> True」
  4. 激活灵犀窗口恢复 → Help 变回空 → 日志「IM 未读变化: 灵犀 -> False」

运行前提：桌宠已在运行（新版 exe），灵犀窗口在任务栏。
"""
import ctypes
import sys
import time
from ctypes import wintypes

import uiautomation as auto

user32 = ctypes.windll.user32


class FLASHWINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("hwnd", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint),
        ("uCount", ctypes.c_uint),
        ("dwTimeout", ctypes.c_uint),
    ]


FLASHW_ALL = 0x03
FLASHW_TIMERNOFG = 0x0C


def find_visible_lingxi():
    out = []

    def enum_proc(hwnd, _):
        try:
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, 512)
            if "灵犀" in title.value and user32.IsWindowVisible(hwnd):
                out.append(hwnd)
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
    return out


def taskbar_lingxi():
    """返回任务栏灵犀按钮的 (Name, Help)。"""
    try:
        root = auto.GetRootControl()
        tb = [None]

        def _walk(c, d=0):
            if d > 8 or tb[0]:
                return
            try:
                if c.ClassName == "Shell_TrayWnd":
                    tb[0] = c
                    return
            except Exception:
                pass
            try:
                for ch in c.GetChildren():
                    _walk(ch, d + 1)
            except Exception:
                pass

        _walk(root)
        if tb[0] is None:
            return None, "<无任务栏>"
        btns = []

        def _btns(c, d=0):
            if d > 12:
                return
            try:
                if "TaskListButton" in c.ClassName:
                    btns.append(c)
            except Exception:
                pass
            try:
                for ch in c.GetChildren():
                    _btns(ch, d + 1)
            except Exception:
                pass

        _btns(tb[0])
        for b in btns:
            try:
                n = b.Name or ""
                if "灵犀" in n:
                    la = b.GetLegacyIAccessiblePattern()
                    help_t = (la.Help or "") if la is not None else "<无模式>"
                    return n, help_t
            except Exception:
                pass
        return None, "<无灵犀按钮>"
    except Exception as e:
        return None, f"<异常:{e}>"


def main():
    print("=== 桌宠 IM 未读检测链路自主验证 ===")
    wins = find_visible_lingxi()
    if not wins:
        print("!! 未找到可见灵犀窗口（请先把灵犀窗口打开到任务栏）")
        return
    hwnd = wins[0]
    print(f"灵犀窗口 hwnd={hwnd}")

    name, help_before = taskbar_lingxi()
    print(f"[1] flash 前任务栏: {name!r} Help={help_before!r}")

    fi = FLASHWINFO()
    fi.cbSize = ctypes.sizeof(FLASHWINFO)
    fi.hwnd = hwnd
    fi.dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG
    fi.uCount = 0
    fi.dwTimeout = 0
    user32.FlashWindowEx(ctypes.byref(fi))
    print("[2] 已触发 FlashWindowEx（持续闪烁直到窗口激活）")

    for i in range(6):
        time.sleep(2)
        name, help_now = taskbar_lingxi()
        print(f"[3.{i}] t+{(i + 1) * 2}s 任务栏: Help={help_now!r}")
        if "请求注意" in help_now or "需要关注" in help_now:
            print("    -> 信号已生效，桌宠应已在 2 秒轮询中检测到未读（查日志）")
            break

    print("[4] 激活灵犀窗口恢复状态...")
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(3)
    _, help_after = taskbar_lingxi()
    print(f"[5] flash 后任务栏: Help={help_after!r}")
    print("=== 验证完成，请检查桌宠日志的「IM 未读变化」行 ===")


if __name__ == "__main__":
    main()
