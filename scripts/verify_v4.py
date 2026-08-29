"""验证 v4：三个提醒 + 呼吸缓存优化。"""
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
        # 呼吸缓存验证
        print("呼吸缓存帧数:", len(w._breath_cache), "每帧级别:", len(w._breath_cache["idle"]))
        w._on_breath()
        print("呼吸渲染 OK")
        # 三个提醒
        w.remind_hourly()
        print("整点报时 OK:", w.bubble.label.text())
        w.remind_sit()
        print("久坐提醒 OK:", w.bubble.label.text())
        w.remind_offwork()
        print("下班提醒 OK:", w.bubble.label.text())
        # 统一刷新
        w.refresh_reminders()
        print("refresh_reminders OK")
        tray.refresh_menu_checks()
        print("菜单勾选刷新 OK")
        app.quit()

    QTimer.singleShot(400, run)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
