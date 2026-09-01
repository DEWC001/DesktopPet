"""实机验证桌宠「落地不弹跳 / 抚摸才弹跳」（1.5.1 摸头反馈层次修复）。

为什么用日志而不是像素 diff：
  8px 弹跳在 146px 画面上只占 5%，肉眼看拼接图时会被 think 帧的
  「抬手摸自己头」动作完全盖住，呼吸缩放、散步位移产生的像素差
  （上万像素）也会把 8px 信号淹没。日志是直接、可靠、可量化的。

用法（必须先在 pet/window.py 的 _pet_bounce() 里加临时日志，再打包）：

    # 在 _pet_bouncing = True 这一行后加：
    #   import logging
    #   logging.getLogger("pet").info("[pet-bounce] hover=%s" % self._hovering)

    python scripts/verify_pet_bounce.py

验证完记得把那两行日志删掉再打包正式版。

判定：
  - 落地静止 3s        → 期望 0 次
  - 在身上来回蹭 3s    → 期望 >= 2 次（弹跳机制还在）
  - 移开再落地 2.5s    → 期望 0 次（行为可重复）
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
LOG = os.path.expanduser(r"~\.desktop_pet\logs\pet.log")
EXE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dist",
    "DesktopPet.exe",
)


def find_pids(name: str) -> list:
    k = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    snap = k.CreateToolhelp32Snapshot(0x00000002, 0)
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    out = []
    if k.Process32FirstW(snap, ctypes.byref(e)):
        while True:
            if e.szExeFile.lower() == name.lower():
                out.append(e.th32ProcessID)
            if not k.Process32NextW(snap, ctypes.byref(e)):
                break
    k.CloseHandle(snap)
    return out


def kill_all_pets() -> None:
    for pid in find_pids("DesktopPet.exe"):
        h = ctypes.windll.kernel32.OpenProcess(0x0001, False, pid)
        if h:
            ctypes.windll.kernel32.TerminateProcess(h, 0)
            ctypes.windll.kernel32.CloseHandle(h)
    k = ctypes.windll.kernel32
    k.DeleteFileW.argtypes = [ctypes.c_wchar_p]
    lock = os.path.expanduser(r"~\.desktop_pet\pet.lock")
    if os.path.exists(lock):
        k.DeleteFileW(lock)


def find_pet_window():
    pids = set(find_pids("DesktopPet.exe"))
    if not pids:
        return None, None
    found = []
    W = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        if 40 <= w <= 400 and 40 <= h <= 400:
            found.append((int(hwnd), (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(W(cb), 0)
    if not found:
        return None, None
    hwnd, rect = min(found, key=lambda i: (i[1][2] - i[1][0]) * (i[1][3] - i[1][1]))
    return hwnd, rect


def bounce_count() -> int:
    if not os.path.exists(LOG):
        return 0
    return open(LOG, encoding="utf-8", errors="replace").read().count("[pet-bounce]")


def safe_move(x, y):
    cur = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cur))
    if cur.x == x and cur.y == y:
        user32.SetCursorPos(x + 1, y + 1)
        time.sleep(0.03)
    user32.SetCursorPos(x, y)


def main():
    kill_all_pets()
    time.sleep(1.0)

    if not os.path.exists(EXE):
        print(f"  找不到 {EXE}，请先打包")
        return 1
    subprocess.Popen([EXE])
    for _ in range(40):
        time.sleep(1)
        hwnd, rect = find_pet_window()
        if hwnd:
            break
    if not hwnd:
        print("启动失败")
        return 1

    x1, y1, x2, y2 = rect
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    print(f"hwnd={hwnd} rect={rect} 中心=({cx},{cy})")

    # 阶段 1：落地后一动不动（3 秒）
    safe_move(max(0, x1 - 300), max(0, y1 - 200))
    time.sleep(1.5)
    n_hover_start = bounce_count()
    safe_move(cx, cy)
    time.sleep(3.0)
    n_hover = bounce_count() - n_hover_start
    print(f"\n[HOVER] 落地静止 3s → 弹跳 {n_hover} 次")

    # 阶段 2：在身上来回蹭 3 秒
    n_stroke_start = bounce_count()
    t_end = time.time() + 3.0
    i = 0
    while time.time() < t_end:
        off = 26 if i % 2 == 0 else -26
        safe_move(cx + off, cy + (i % 3))
        time.sleep(0.08)
        i += 1
    n_stroke = bounce_count() - n_stroke_start
    print(f"[STROKE] 来回蹭 3s → 弹跳 {n_stroke} 次")

    # 阶段 3：移开后再放上去一次（确认可重复）
    safe_move(max(0, x1 - 300), max(0, y1 - 200))
    time.sleep(1.2)
    n_re_start = bounce_count()
    safe_move(cx, cy)
    time.sleep(2.5)
    n_re = bounce_count() - n_re_start
    print(f"[HOVER-2] 移开后再落地 2.5s → 弹跳 {n_re} 次")

    print("\n--- 判定 ---")
    ok = True
    if n_hover == 0 and n_re == 0:
        print("  PASS  落地不弹跳（两次落地都是 0 次）")
    else:
        print(f"  FAIL  落地仍在弹跳（{n_hover} / {n_re}）")
        ok = False

    if n_stroke >= 2:
        print(f"  PASS  抚摸仍会弹跳（{n_stroke} 次）")
    else:
        print(f"  FAIL  抚摸弹跳异常（{n_stroke} 次，期望 >= 2）")
        ok = False

    kill_all_pets()
    print("\n收尾完成")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
