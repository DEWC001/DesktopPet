"""摸头互动端到端验证（**必须在真实桌面平台运行，不要设 offscreen**）。

offscreen 冒烟测试是「手动喂事件」，能验证逻辑但验证不了投递链路：
Qt 到底会不会把**没有按下按键的鼠标移动**投递给一个
无边框 + 透明背景 + 始终置顶的 Tool 窗口？答案是不试不知道。

所以这里真开一个窗口、真移动系统光标，看互动状态有没有被驱动。

运行：
    python scripts/test_pet_e2e.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QCursor, QGuiApplication  # noqa: E402
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


def assert_true(cond, msg="断言失败"):
    if not cond:
        raise AssertionError(msg)


def spin(app, ms: int) -> None:
    """让事件循环真的转起来（setPos 产生的光标事件需要被分发）。"""
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def move_cursor(app, x: int, y: int, settle_ms: int = 120) -> None:
    """移动系统光标并保证真的产生了移动事件。

    坑：SetCursorPos 设到「光标当前已经在这个位置」时 Windows **不会**
    产生 WM_MOUSEMOVE，测试就会看到「事件没投递」的假象。所以目标点与
    当前位置相同时先抖一下。
    """
    if QCursor.pos() == QPoint(x, y):
        QCursor.setPos(max(0, x - 40), max(0, y - 40))
        spin(app, 60)
    QCursor.setPos(x, y)
    spin(app, settle_ms)


def main() -> int:
    from pet.brain import PetBrain
    from pet.window import PetWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    window.show()
    window.brain.state = PetBrain.IDLE
    spin(app, 300)

    screen = QGuiApplication.primaryScreen().availableGeometry()
    window.move(screen.left() + 200, screen.top() + 200)
    spin(app, 300)

    pm = window.label.pixmap()
    assert_true(pm is not None and not pm.isNull(), "精灵帧应已加载")

    def hit_fraction(fx: float, fy: float) -> bool:
        """相对坐标点是否落在身体上（换算成窗口局部坐标后做 alpha 命中）。"""
        gx = window.x() + window.label.x() + int(pm.width() * fx)
        gy = window.y() + window.label.y() + int(pm.height() * fy)
        return window._hit_body(window.mapFromGlobal(QPoint(gx, gy)))

    # 沿水平中线扫一遍，找出身体在横向的可见范围（精灵图四周是透明的）
    hits = [i / 100 for i in range(101) if hit_fraction(i / 100, 0.5)]
    assert_true(hits, "水平中线应能扫到身体像素")
    lo, hi = min(hits), max(hits)
    width_frac = hi - lo
    assert_true(width_frac > 0.2, f"身体横向占比太小，无法做抚摸测试：{width_frac:.2f}")

    fa = lo + width_frac * 0.25
    fb = lo + width_frac * 0.75

    def global_at(fx: float, fy: float = 0.5):
        return (
            window.x() + window.label.x() + int(pm.width() * fx),
            window.y() + window.label.y() + int(pm.height() * fy),
        )

    cx, cy = global_at((lo + hi) / 2)
    print(
        f"  宠物位置 ({window.x()}, {window.y()}) 尺寸 {pm.width()}x{pm.height()}"
        f"｜身体横向 {lo:.2f}~{hi:.2f}｜驱动中心 ({cx}, {cy})"
    )

    old_cursor = QCursor.pos()
    away_x = max(screen.left() + 5, window.x() - 300)
    away_y = screen.top() + 5

    try:
        def step_no_hover_when_away():
            move_cursor(app, away_x, away_y, 400)
            assert_true(not window._hovering, "光标不在身上时不应进入互动态")

        check("光标不在身上时不互动", step_no_hover_when_away)

        def step_enter():
            move_cursor(app, cx, cy, 500)
            assert_true(
                window._hovering,
                "光标移到身上应进入互动态"
                "（若失败：Qt 没把无按键的 move 事件投递给这个窗口）",
            )

        check("光标移到身上触发互动", step_enter)

        def step_enter_without_jiggle():
            """「挪上来就停住」也要有反应。

            Qt 行为：光标进入 layered（半透明）窗口时的第一条 WM_MOUSEMOVE
            只转成 Enter、**不转成 MouseMove**。只靠 mouseMoveEvent 的话，
            鼠标停在身上不动就永远没反应，必须再抖一像素。这条用例专门盯这个。
            """
            move_cursor(app, away_x, away_y, 300)
            QCursor.setPos(cx, cy)  # 不抖，模拟挪上来就停住
            spin(app, 500)
            assert_true(
                window._hovering,
                "只靠 enter 事件也应触发互动（Qt 不会为进窗口的第一下补 MouseMove）",
            )

        check("挪上来停住也有反应（Enter 兜底）", step_enter_without_jiggle)

        def step_strokes():
            window._pet_strokes = 0
            ax, ay = global_at(fa)
            bx, by = global_at(fb)
            for i in range(4):
                move_cursor(
                    app,
                    ax if i % 2 == 0 else bx,
                    ay if i % 2 == 0 else by,
                    120,
                )
            assert_true(
                window._pet_strokes >= 1,
                f"在身上来回移动应累计抚摸次数，实际 {window._pet_strokes}",
            )

        check("来回移动累计抚摸次数", step_strokes)

        def step_leave():
            move_cursor(app, away_x, away_y, 400)
            assert_true(not window._hovering, "移开光标应退出互动态")

        check("移开光标退出互动", step_leave)
    finally:
        QCursor.setPos(old_cursor)
        window.close()
        spin(app, 200)

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        code = main()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL  初始化异常: {type(exc).__name__}: {exc}")
        code = 1
    sys.exit(code)
