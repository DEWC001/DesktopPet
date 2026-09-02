"""打包版 exe 实机启动验证（1.7.0）。

在**真实桌面平台**运行（不要设 offscreen）。脚本自带「启动 exe → 验证 → 收尾」，
验证完主动结束桌宠进程并清理，绝不把桌宠留在后台。

覆盖打包环境特有的风险（PyInstaller onefile 才有漏网 AttributeError 的历史）：
  1. exe 能正常启动（onefile 解包 + bootloader fork 后子进程建窗）
  2. 主窗口（标题 DesktopPet）出现、尺寸合理、可见
  3. 运行数秒后日志无 Traceback / AttributeError

注：菜单点选/对话框这类交互逻辑由 scripts/test_sticky_menu.py（StickyMenu +
ActivityDialog）与 test_menu_smoke.py 在 offscreen 真构造下覆盖；Win11 托盘溢出区
UIA 读取受限、Qt popup 菜单需前台激活，合成右键/托盘自动驱动在无头自动化环境
不稳定，故不放入 exe 启动验证的硬性断言。

运行：
    python scripts/verify_exe_170.py
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXE = os.path.join(_ROOT, "dist", "DesktopPet.exe")
_LOG = os.path.join(os.path.expanduser("~"), ".desktop_pet", "logs", "pet.log")

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


# ---------- 进程 / 窗口工具（ctypes，避开 tasklist 中文 GBK 崩溃） ----------
k32 = ctypes.WinDLL("kernel32")
u32 = ctypes.WinDLL("user32")

_PROCESS_TERMINATE = 0x0001
_SNAP_PROCESS = 0x00000002


class _PE32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def find_pet_pids() -> list:
    snap = k32.CreateToolhelp32Snapshot(_SNAP_PROCESS, 0)
    pids = []
    pe = _PE32()
    pe.dwSize = ctypes.sizeof(_PE32)
    ok = k32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        if pe.szExeFile.lower() == "desktoppet.exe":
            pids.append(int(pe.th32ProcessID))
        ok = k32.Process32NextW(snap, ctypes.byref(pe))
    k32.CloseHandle(snap)
    return pids


def kill_pets() -> None:
    for pid in find_pet_pids():
        h = k32.OpenProcess(_PROCESS_TERMINATE, False, pid)
        if h:
            k32.TerminateProcess(h, 0)
            k32.CloseHandle(h)


def find_main_hwnd(timeout=25.0) -> int:
    """按「标题==DesktopPet + 属于桌宠进程 + 可见小窗」定位主窗口。"""
    from ctypes import wintypes as wt

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    deadline = time.time() + timeout
    while time.time() < deadline:
        pids = set(find_pet_pids())
        if not pids:
            time.sleep(0.3)
            continue
        found = {}

        def cb(hwnd, lparam):
            if not u32.IsWindowVisible(hwnd):
                return True
            pid = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pids:
                return True
            buf = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buf, 256)
            if buf.value != "DesktopPet":
                return True
            r = _RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(r))
            w, h = r.right - r.left, r.bottom - r.top
            found[int(hwnd)] = (w, h, (r.left, r.top, r.right, r.bottom))
            return True

        u32.EnumWindows(_WNDENUMPROC(cb), 0)
        if found:
            hwnd = min(found, key=lambda k: found[k][0] * found[k][1])
            return int(hwnd)
        time.sleep(0.3)
    return 0


def rect_of(hwnd: int):
    r = _RECT()
    u32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def read_tail_log(lines=100) -> str:
    try:
        with open(_LOG, "r", encoding="utf-8", errors="replace") as f:
            data = f.read().splitlines()
        return "\n".join(data[-lines:])
    except OSError:
        return ""


def tail_size() -> int:
    try:
        return os.path.getsize(_LOG)
    except OSError:
        return 0


def main() -> int:
    if not os.path.exists(_EXE):
        print(f"  未找到 {_EXE}，请先打包")
        return 1

    print("== 阶段A：启动 exe ==")
    kill_pets()
    time.sleep(0.5)
    log_before = tail_size()
    proc = subprocess.Popen([_EXE], cwd=_ROOT)

    hwnd = {"v": 0}

    def t_start():
        h = find_main_hwnd()
        assert_true(h != 0, "25s 内未找到主窗口（标题 DesktopPet）")
        hwnd["v"] = h

    check("exe 启动并出现主窗口", t_start)

    def t_window_ok():
        h = hwnd["v"]
        assert_true(h, "无窗口句柄")
        x1, y1, x2, y2 = rect_of(h)
        w, h2 = x2 - x1, y2 - y1
        assert_true(40 <= w <= 500 and 40 <= h2 <= 500, f"窗口尺寸异常：{w}x{h2}")
        assert_true(u32.IsWindowVisible(wintypes.HWND(h)), "窗口应可见")

    check("主窗口尺寸与可见性", t_window_ok)

    def t_log_clean():
        time.sleep(3.0)  # 等启动日志与首轮行为落盘
        tail = read_tail_log()
        assert_true("Traceback" not in tail, "日志出现 Traceback")
        assert_true("AttributeError" not in tail, "日志出现 AttributeError")
        assert_true("桌面宠物启动" in tail, "日志应含启动标记（主流程走到 app.exec）")
        assert_true(tail_size() > log_before, "日志应有新内容")

    check("日志干净且主流程启动完成", t_log_clean)

    # 稳定运行观察（无异常即认为打包版基本盘 OK）
    def t_stay_alive():
        time.sleep(5.0)
        pids = find_pet_pids()
        assert_true(len(pids) >= 1, "运行 5s 后进程应仍在")
        assert_true("Traceback" not in read_tail_log(), "运行期间日志出现 Traceback")

    check("运行 5 秒稳定无异常", t_stay_alive)

    print("== 阶段B：收尾 ==")
    kill_pets()
    time.sleep(0.5)
    remaining = find_pet_pids()
    print(f"  残留 DesktopPet 进程: {remaining if remaining else '无'}")
    try:
        proc.wait(timeout=2)
    except Exception:
        pass

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
