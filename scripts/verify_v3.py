"""验证 v3：右键菜单复用 + 单击/双击交互。"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet.window import PetWindow
from pet.tray import TrayIcon


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    w.show()
    tray = TrayIcon(w)
    tray.show()
    w.tray = tray

    def run():
        # 右键菜单复用检查
        tray.refresh_menu_checks()
        print("refresh_menu_checks OK, tray 引用:", w.tray is not None)
        # 单击
        w._do_single_click()
        print("单击 OK, 气泡:", w.bubble.label.text())
        # 双击
        w._do_double_click()
        print("双击 OK, 气泡:", w.bubble.label.text())
        app.quit()

    QTimer.singleShot(400, run)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
