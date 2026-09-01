"""打包版 exe 的摸头实机验证。

跑通逻辑测试还不够：这是给 exe 用的，得证明「真把鼠标挪到宠物身上蹭」
在打包环境下确实有反应。做法：

  1. 按 PID 找到桌宠窗口
  2. 截图（带上方可容纳气泡的余量）
  3. 真实移动系统光标到宠物身上来回蹭
  4. 再截图，比较像素差异——有反应 = 图像变了（切笑帧 / 弹气泡）

用法（需先启动 dist/DesktopPet.exe）：
    python scripts/verify_pet_exe.py
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageGrab  # noqa: E402

user32 = ctypes.windll.user32


def enum_pet_hwnds() -> list:
    """枚举属于 DesktopPet 进程的可见窗口。"""
    import subprocess

    out = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq DesktopPet.exe", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
    )
    pids = set()
    for line in out.stdout.splitlines():
        parts = [p.strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[0].startswith("DesktopPet"):
            try:
                pids.add(int(parts[1]))
            except ValueError:
                pass
    if not pids:
        return []

    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        # 桌宠精灵窗口：小尺寸、正方形量级；气泡窗口更宽扁，也一起收
        if 40 <= w <= 900 and 40 <= h <= 900:
            found.append((int(hwnd), (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found


def main() -> int:
    wins = enum_pet_hwnds()
    if not wins:
        print("  未找到运行的 DesktopPet.exe，请先启动 dist/DesktopPet.exe")
        return 1

    # 桌宠本体是最小的那个（气泡更宽扁，托盘无关窗口已按尺寸过滤）
    hwnd, rect = min(wins, key=lambda item: (item[1][2] - item[1][0]) * (item[1][3] - item[1][1]))
    x1, y1, x2, y2 = rect
    print(f"  桌宠窗口 hwnd={hwnd} rect={rect} 尺寸 {x2 - x1}x{y2 - y1}")

    pad = 220  # 上方留够气泡空间
    box = (max(0, x1 - pad), max(0, y1 - pad), x2 + pad, y2 + pad)

    before = ImageGrab.grab(bbox=box)
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

    # 先挪开，确保是「进入」动作
    user32.SetCursorPos(max(0, x1 - 300), max(0, y1 - 200))
    time.sleep(0.4)
    # 再挪到身上，来回蹭（累计位移要跨过 48px 阈值）
    user32.SetCursorPos(cx, cy)
    time.sleep(0.5)
    for i in range(12):
        off = 26 if i % 2 == 0 else -26
        user32.SetCursorPos(cx + off, cy + (i % 3))
        time.sleep(0.09)
    time.sleep(0.6)
    after = ImageGrab.grab(bbox=box)

    diff = sum(1 for a, b in zip(before.convert("RGB").getdata(), after.convert("RGB").getdata()) if a != b)
    total = before.width * before.height
    pct = 100.0 * diff / total
    print(f"  蹭之前 vs 之后：{diff}/{total} 像素不同（{pct:.2f}%）")

    os.makedirs(os.path.join(os.path.dirname(__file__), "_out"), exist_ok=True)
    bp = os.path.join(os.path.dirname(__file__), "_out", "pet_before.png")
    ap = os.path.join(os.path.dirname(__file__), "_out", "pet_after.png")
    before.save(bp)
    after.save(ap)
    print(f"  截图已存：{bp} / {ap}")

    if pct < 0.5:
        print("  FAIL  蹭了半天图像几乎没变（<0.5%），摸头互动在打包版里没生效")
        return 1
    print("  PASS  摸头互动在打包版 exe 中生效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
