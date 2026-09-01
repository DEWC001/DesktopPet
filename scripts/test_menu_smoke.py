"""托盘菜单冒烟测试。

目的：抓 py_compile / 单元测试抓不到的运行时错误。
1.2.0 出过一次 TypeError：config.get() 只收 1 个参数，tray.py 却传了 2 个，
    编译和单测全绿，只有 exe 真跑起来构造 TrayIcon 时才崩。
本测试用 offscreen 平台真实构造 PetWindow + TrayIcon，并遍历点击所有菜单项，
确保每次改动后不会再出现「打包了但一启动就崩」的情况。

运行：
    QT_QPA_PLATFORM=offscreen python scripts/test_menu_smoke.py
"""
import os
import sys
import traceback

# 放在导入 PySide6 之前
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)


def stub_dialogs() -> None:
    """把模态对话框打桩，否则 offscreen 下 exec() 会挂住。"""
    QDialog.exec = lambda self, *a, **k: 0
    QDialog.open = lambda self, *a, **k: None
    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
    QInputDialog.getInt = staticmethod(lambda *a, **k: (0, False))
    QInputDialog.getDouble = staticmethod(lambda *a, **k: (0.0, False))
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("", ""))
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")


PASS = 0
FAIL = 0


def check(name: str, fn) -> None:
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()


def main() -> int:
    from pet import config
    from pet.tray import TrayIcon
    from pet.window import PetWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    stub_dialogs()

    print("[1] 构造 PetWindow")
    window = None
    try:
        window = PetWindow()
        window.show()
        print("  PASS  PetWindow 构造成功")
        globals()["PASS"] += 1
    except Exception as exc:  # noqa: BLE001
        globals()["FAIL"] += 1
        print(f"  FAIL  PetWindow 构造失败: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    print("[2] 构造 TrayIcon（1.2.0 崩溃点）")
    tray = None
    try:
        tray = TrayIcon(window)
        window.tray = tray
        print("  PASS  TrayIcon 构造成功")
        globals()["PASS"] += 1
    except Exception as exc:  # noqa: BLE001
        globals()["FAIL"] += 1
        print(f"  FAIL  TrayIcon 构造失败: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1

    print("[3] 刷新菜单勾选状态")
    check("refresh_menu_checks", tray.refresh_menu_checks)
    check("_sync_focus_menu", tray._sync_focus_menu)
    check("_sync_custom_menu", tray._sync_custom_menu)

    print("[4] 逐个触发所有菜单 action（可勾选的来回切一次）")
    actions = tray.menu.actions()
    print(f"  共 {len(actions)} 个顶层菜单项")
    for act in actions:
        name = act.text() or "(separator/menu)"
        if act.isSeparator():
            continue
        if act.menu():
            # 子菜单：只刷新标题，不展开触发
            check(f"子菜单 {name} 存在", lambda a=act: a.menu().actions())
            continue
        if act.isCheckable():
            def toggle(a=act):
                old = a.isChecked()
                a.setChecked(not old)
                a.setChecked(old)
            check(f"勾选切换 {name}", toggle)
        else:
            check(f"触发 {name}", act.trigger)

    print("[5] 关键配置读写往返")
    check("config.get 单参数", lambda: config.get("edge_hide_enabled"))
    check("config.get 双参数", lambda: config.get("edge_hide_enabled", True))
    check("config.flag", lambda: config.flag("edge_hide_enabled"))
    check("config.sound_allowed", config.sound_allowed)
    check("config.is_silent_now", config.is_silent_now)
    check("config.get_custom_reminders", config.get_custom_reminders)

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
