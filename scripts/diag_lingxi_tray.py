"""灵犀托盘场景综合监控：每 2 秒快照以下信号源，观察缩托盘 + 发消息全过程。

信号源：
1. Win32 顶层窗口（可见/隐藏 + 标题）
2. UIA 任务栏按钮（Name/Help）
3. Win32 托盘 Toolbar 按钮文本（含溢出区）

用法：运行脚本后：
  1) 把灵犀缩到系统托盘（等 10 秒）
  2) 用另一账号给灵犀发一条消息，保持未读 30 秒
  3) 观察各信号源的变化（240 秒自动结束）
"""
import ctypes
import sys
import time
from ctypes import wintypes

import uiautomation as auto

user32 = ctypes.windll.user32

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
TB_BUTTONCOUNT = 0x0418
TB_GETBUTTON = 0x0417
TB_GETBUTTONTEXTW = 0x041D


class TBBUTTON(ctypes.Structure):
    _fields_ = [
        ("iBitmap", ctypes.c_int),
        ("idCommand", ctypes.c_int),
        ("fsState", ctypes.c_ubyte),
        ("fsStyle", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte * 2),
        ("dwData", ctypes.c_ulonglong),
        ("iString", ctypes.c_longlong),
    ]


def get_title(hwnd):
    length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buf)
    return buf.value


def win32_windows():
    """枚举所有顶层窗口中的灵犀窗口。"""
    out = []

    def enum_proc(hwnd, _):
        try:
            title = get_title(hwnd)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if "lingxi" in cls.value.lower() or "灵犀" in title:
                vis = bool(user32.IsWindowVisible(hwnd))
                out.append((hwnd, cls.value, title, vis))
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
    return out


def taskbar_button():
    """UIA 任务栏灵犀按钮的 Name/Help。"""
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
            return "<无任务栏>"
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
                    return f"按钮:{n!r} Help:{help_t!r}"
            except Exception:
                pass
        return "<无灵犀按钮>"
    except Exception as e:
        return f"<任务栏异常:{e}>"


def tray_toolbar_texts():
    """托盘（含溢出区）Toolbar 所有按钮文本，只返回灵犀相关。"""
    texts = []
    try:
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        if not tray:
            return texts
        notify = user32.FindWindowExW(tray, 0, "TrayNotifyWnd", None)
        tbw = notify and user32.FindWindowExW(notify, 0, "ToolbarWindow32", None)
        while tbw:
            count = user32.SendMessageW(tbw, TB_BUTTONCOUNT, 0, 0)
            for i in range(count):
                try:
                    btn = TBBUTTON()
                    if not user32.SendMessageW(tbw, TB_GETBUTTON, i, ctypes.byref(btn)):
                        continue
                    if btn.iString and btn.iString != -1:
                        buf = ctypes.create_unicode_buffer(256)
                        n = user32.SendMessageW(tbw, TB_GETBUTTONTEXTW, btn.idCommand, buf)
                        if n > 0:
                            texts.append(buf.value)
                except Exception:
                    pass
            tbw = user32.FindWindowExW(notify, tbw, "ToolbarWindow32", None)
        # 溢出区
        overflow = user32.FindWindowExW(notify, 0, "NotifyIconOverflowWindow", None)
        if overflow:
            otb = user32.FindWindowExW(overflow, 0, "ToolbarWindow32", None)
            while otb:
                count = user32.SendMessageW(otb, TB_BUTTONCOUNT, 0, 0)
                for i in range(count):
                    try:
                        btn = TBBUTTON()
                        if not user32.SendMessageW(otb, TB_GETBUTTON, i, ctypes.byref(btn)):
                            continue
                        if btn.iString and btn.iString != -1:
                            buf = ctypes.create_unicode_buffer(256)
                            n = user32.SendMessageW(otb, TB_GETBUTTONTEXTW, btn.idCommand, buf)
                            if n > 0:
                                texts.append("[溢出]" + buf.value)
                    except Exception:
                        pass
                otb = user32.FindWindowExW(overflow, otb, "ToolbarWindow32", None)
    except Exception:
        pass
    return [t for t in texts if "灵犀" in t or "lingxi" in t.lower()]


def main():
    print(">>> 开始监控 240 秒。步骤：")
    print(">>>   1) 把灵犀缩到系统托盘（等 10 秒）")
    print(">>>   2) 用另一账号给灵犀发一条消息，保持未读 30 秒")
    print(">>>   3) 看下面各信号源变化。")
    start = time.time()
    last_summary = ""
    while time.time() - start < 240:
        t = int(time.time() - start)
        try:
            wins = win32_windows()
            win_str = "; ".join(
                f"hwnd={h} {'可见' if v else '隐藏'} '{ti}'" for h, _, ti, v in wins
            )
            btn = taskbar_button()
            tray = tray_toolbar_texts()
            tray_str = "; ".join(tray) if tray else "<托盘无灵犀>"
            summary = f"[t+{t}s] 窗口: {win_str} | 任务栏: {btn} | 托盘: {tray_str}"
            if summary != last_summary:
                print(summary)
                sys.stdout.flush()
                last_summary = summary
        except Exception as e:
            print(f"[t+{t}s] 异常: {e}")
        time.sleep(2)
    print(">>> 监控结束。")


if __name__ == "__main__":
    main()
