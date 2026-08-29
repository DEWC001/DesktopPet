"""验证喝水提醒完整流程：跑到中心 -> 气泡 -> 回到原位。"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet import config
from pet.window import PetWindow


def main() -> int:
    config.set_value("drink_enabled", True)
    config.set_value("drink_location", "center")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = PetWindow()
    w.show()

    origin = w.pos()
    print(f"原位: ({origin.x()}, {origin.y()})")

    QTimer.singleShot(300, w.remind_drink)

    def at_center():
        screen = QApplication.primaryScreen().availableGeometry()
        cx = screen.left() + (screen.width() - w.width()) // 2
        cy = screen.top() + (screen.height() - w.height()) // 2
        print(f"[1s] 宠物位置=({w.pos().x()},{w.pos().y()}), 期望中心=({cx},{cy})")
        print(f"[1s] 气泡可见={w.bubble.isVisible()}, 气泡文字={w.bubble.label.text()}")
        w.grab().save(os.path.join(_ROOT, "preview_drink_pet.png"))
        w.bubble.grab().save(os.path.join(_ROOT, "preview_drink_bubble.png"))

    def at_end():
        print(f"[6s] 宠物位置=({w.pos().x()},{w.pos().y()}), 原位=({origin.x()},{origin.y()})")
        print(f"[6s] 已回原位={w.pos() == origin}")
        print(f"[6s] 气泡可见={w.bubble.isVisible()}")
        app.quit()

    QTimer.singleShot(1200, at_center)
    QTimer.singleShot(6200, at_end)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
