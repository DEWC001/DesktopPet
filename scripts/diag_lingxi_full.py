"""灵犀综合诊断：任务栏按钮（UIA）+ 全窗口枚举（Win32）+ 托盘 Toolbar 按钮（Win32）。

一次跑出灵犀当前在哪些位置、各信号源状态如何。
"""
import ctypes
from ctypes import wintypes

import uiautomation as auto

user32 = ctypes.windll.user32

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
TB_GETBUTTON = 0x0417
TB_BUTTONCOUNT = 0x0418
TB_GETBUTTONTEXTW = 0x041D
TB_GETBUTTONINFOW = 0x043F


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


def get_pid(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def get_title(hwnd):
    length = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, length + 1, buf)
    return buf.value


def main():
    print("===== 1) Win32 顶层窗口（含隐藏，找灵犀）=====")
    wins = []

    def enum_proc(hwnd, _):
        try:
            pid = get_pid(hwnd)
            title = get_title(hwnd)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            vis = bool(user32.IsWindowVisible(hwnd))
            wins.append((hwnd, pid, cls.value, title, vis))
        except Exception:
            pass
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
    for hwnd, pid, cls, title, vis in wins:
        if "lingxi" in cls.lower() or "灵犀" in title or "lingxi" in title.lower():
            print(f"  hwnd={hwnd} pid={pid} class={cls!r} title={title!r} 可见={vis}")

    print("===== 2) UIA 任务栏按钮（找灵犀）=====")
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
    if tb[0]:
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
        found = False
        for b in btns:
            try:
                n = b.Name or ""
                if "灵犀" in n:
                    found = True
                    la = b.GetLegacyIAccessiblePattern()
                    help_t = (la.Help or "") if la is not None else "<无模式>"
                    print(f"  任务栏按钮: Name={n!r} Help={help_t!r}")
            except Exception:
                pass
        if not found:
            print("  任务栏无灵犀按钮")
    else:
        print("  未找到任务栏")

    print("===== 3) Win32 托盘 Toolbar 按钮（找灵犀）=====")
    tray = user32.FindWindowW("Shell_TrayWnd", None)
    notify = None
    if tray:
        notify = user32.FindWindowExW(tray, 0, "TrayNotifyWnd", None)
    toolbars = []
    if notify:
        tbw = user32.FindWindowExW(notify, 0, "ToolbarWindow32", None)
        while tbw:
            toolbars.append(tbw)
            tbw = user32.FindWindowExW(notify, tbw, "ToolbarWindow32", None)
    if not toolbars:
        print("  未找到托盘 Toolbar")
    for tbw in toolbars:
        count = user32.SendMessageW(tbw, TB_BUTTONCOUNT, 0, 0)
        for i in range(count):
            try:
                btn = TBBUTTON()
                got = user32.SendMessageW(
                    tbw, TB_GETBUTTON, i, ctypes.byref(btn)
                )
                if not got:
                    continue
                # 按钮文本（iString 指向的字符串）
                text = ""
                if btn.iString and btn.iString != -1:
                    buf = ctypes.create_unicode_buffer(256)
                    n = user32.SendMessageW(
                        tbw, TB_GETBUTTONTEXTW, btn.idCommand, buf
                    )
                    if n > 0:
                        text = buf.value
                if "灵犀" in text or "lingxi" in text.lower():
                    print(f"  托盘按钮(id={btn.idCommand}): text={text!r}")
            except Exception:
                pass
    print("===== 结束 =====")


if __name__ == "__main__":
    main()
