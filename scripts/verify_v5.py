"""验证 v5：呼吸缓存级别 + 跳跃位移落新位置。"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet.window import PetWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    w.show()
    print("呼吸缩放级别:", len(w._breath_cache["idle"]))

    origin = w.pos()

    def jump():
        w._do_jump(30)  # 固定向右位移 30

    def check():
        print(f"原位: ({origin.x()},{origin.y()}) -> 跳后: ({w.pos().x()},{w.pos().y()})")
        print(f"位移: x={w.pos().x()-origin.x()}, y={w.pos().y()-origin.y()}")
        app.quit()

    QTimer.singleShot(300, jump)
    QTimer.singleShot(900, check)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
