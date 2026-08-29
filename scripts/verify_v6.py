"""验证 v6：初始睡眠 + 提醒唤醒。"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet.window import PetWindow
from pet.brain import PetBrain


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    w.show()

    print("初始状态:", w.brain.state, "(期望 sleep)")
    print("初始帧:", w._current_frame_name(), "(期望 sleep)")

    def remind():
        was = w._begin_reminder()
        print("提醒前是否在睡:", was)
        w._notify("起来活动一下～")
        print("提醒后状态:", w.brain.state, "(期望 idle)")
        print("提醒后帧:", w._current_frame_name())

    def done():
        app.quit()

    QTimer.singleShot(300, remind)
    QTimer.singleShot(1200, done)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
