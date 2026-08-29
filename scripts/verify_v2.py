"""验证 v2：默认缩放、新状态、缩放切换。"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet import config
from pet.brain import PetBrain
from pet.window import PetWindow


def main() -> int:
    config.set_value("scale", 0.65)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    w.show()
    print(f"默认大小(scale 0.65): {w.width()}x{w.height()}")

    def test_states():
        for s in [PetBrain.JUMP, PetBrain.CHAT, PetBrain.WANDER, PetBrain.SLEEP, PetBrain.WALK, PetBrain.IDLE]:
            w._on_state(s)
        print("6 种状态切换 OK")

        w.set_scale(1.0)
        print(f"scale 1.0: {w.width()}x{w.height()}")
        w.set_scale(0.5)
        print(f"scale 0.5: {w.width()}x{w.height()}")
        w.set_scale(0.65)

    def shot():
        w.grab().save(os.path.join(_ROOT, "preview_v2.png"))
        print("preview_v2.png saved")
        app.quit()

    QTimer.singleShot(400, test_states)
    QTimer.singleShot(1600, shot)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
