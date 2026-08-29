"""桌面宠物入口：单实例守护、全局异常兜底、启动窗口与托盘。"""
import logging
import os
import sys
import traceback

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from pet import config
from pet.tray import TrayIcon
from pet.window import PetWindow


def setup_logging() -> None:
    config.ensure_dirs()
    log_file = os.path.join(config.LOG_DIR, "pet.log")
    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def excepthook(exc_type, exc_value, exc_tb):
    logging.error("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))
    traceback.print_exception(exc_type, exc_value, exc_tb)


def main() -> int:
    config.ensure_dirs()
    setup_logging()
    sys.excepthook = excepthook

    # 单实例守护：防止双击开启多个
    lock = QLockFile(os.path.join(config.DATA_DIR, "pet.lock"))
    if not lock.tryLock(100):
        logging.info("已有实例在运行，本次启动退出")
        # 已有实例：弹提示而非静默退出
        app = QApplication(sys.argv)
        QMessageBox.information(
            None, "桌面宠物", "桌面宠物已经在运行啦～\n请在右下角系统托盘找到它。"
        )
        return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    window.show()
    tray = TrayIcon(window)
    tray.show()
    window.tray = tray  # 宠物右键复用托盘菜单

    # 持有引用，防止被垃圾回收
    app._window = window
    app._tray = tray

    logging.info("桌面宠物启动")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
