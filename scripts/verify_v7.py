"""验证 v7：Zzz 睡眠气泡 + 气泡统一管理。"""
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

    def check():
        print("状态:", w.brain.state, "(期望 sleep)")
        print("Zzz 气泡可见:", w.zzz_bubble.isVisible(), "(期望 True)")
        print("Zzz 文字:", w.zzz_bubble.label.text())
        # 测试说话气泡
        w._show_bubble("测试气泡文案", 12000)
        print("说话气泡可见:", w.bubble.isVisible(), "(期望 True)")
        print("说话气泡文字:", w.bubble.label.text())
        # 唤醒，Zzz 应隐藏
        w.brain.wake()
        print("唤醒后状态:", w.brain.state)
        print("唤醒后 Zzz 可见:", w.zzz_bubble.isVisible(), "(期望 False)")
        app.quit()

    QTimer.singleShot(500, check)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
