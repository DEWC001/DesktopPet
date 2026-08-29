"""验证：创建窗口、渲染、截图，供确认形象效果。"""
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

    window = PetWindow()
    window.show()

    def shot():
        pix = window.grab()
        pix.save(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview.png"))
        print(f"preview saved: {pix.width()}x{pix.height()}, window size: {window.width()}x{window.height()}, state={window.brain.state}")
        app.quit()

    QTimer.singleShot(1500, shot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
