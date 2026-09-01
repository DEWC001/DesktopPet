"""自定义提醒事项的编辑与管理对话框。

提醒事项数据结构（存 config 的 custom_reminders，JSON 序列化）：
    {
        "id": str,            # 唯一标识
        "label": str,         # 提醒内容
        "time": "HH:MM",      # 触发时间
        "kind": "daily" | "weekly" | "once",
        "weekday": int,       # weekly 用，0=周一 ... 6=周日（对齐 datetime.weekday()）
        "date": "YYYY-MM-DD", # once 用
        "enabled": bool,
    }
"""
import uuid

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
)

from . import config

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def describe(item: dict) -> str:
    """把提醒事项格式化成一行人类可读文本。"""
    kind = item.get("kind", "daily")
    mark = "√" if item.get("enabled", True) else "×"
    if kind == "weekly":
        when = f"每周{WEEKDAY_NAMES[int(item.get('weekday', 0)) % 7]}"
    elif kind == "once":
        when = str(item.get("date", ""))
    else:
        when = "每天"
    return f"[{mark}] {when} {item.get('time')} · {item.get('label')}"


class ReminderEditDialog(QDialog):
    """新增提醒事项：内容 + 时间 + 重复方式。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加自定义提醒")
        self.resize(340, 200)

        self.edit_label = QLineEdit(self)
        self.edit_label.setPlaceholderText("例如：该吃药了 / 周会要开始了")

        self.edit_time = QTimeEdit(self)
        self.edit_time.setDisplayFormat("HH:mm")
        self.edit_time.setTime(QTime.currentTime().addSecs(3600))

        self.combo_kind = QComboBox(self)
        self.combo_kind.addItem("每天", "daily")
        self.combo_kind.addItem("每周", "weekly")
        self.combo_kind.addItem("仅一次", "once")
        self.combo_kind.currentIndexChanged.connect(self._sync_visible)

        self.combo_week = QComboBox(self)
        for i, name in enumerate(WEEKDAY_NAMES):
            self.combo_week.addItem(name, i)
        # QDate.dayOfWeek() 是 1=周一，转成 0-based 对齐 datetime.weekday()
        self.combo_week.setCurrentIndex(QDate.currentDate().dayOfWeek() - 1)

        self.edit_date = QDateEdit(self)
        self.edit_date.setCalendarPopup(True)
        self.edit_date.setDisplayFormat("yyyy-MM-dd")
        self.edit_date.setDate(QDate.currentDate())

        self.lab_week = QLabel("星期", self)
        self.lab_date = QLabel("日期", self)

        form = QFormLayout()
        form.addRow("提醒内容", self.edit_label)
        form.addRow("提醒时间", self.edit_time)
        form.addRow("重复方式", self.combo_kind)
        form.addRow(self.lab_week, self.combo_week)
        form.addRow(self.lab_date, self.edit_date)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self._sync_visible()

    def _sync_visible(self) -> None:
        """按重复方式显示/隐藏星期和日期行。"""
        kind = self.combo_kind.currentData()
        self.lab_week.setVisible(kind == "weekly")
        self.combo_week.setVisible(kind == "weekly")
        self.lab_date.setVisible(kind == "once")
        self.edit_date.setVisible(kind == "once")
        self.adjustSize()

    def _on_accept(self) -> None:
        if not self.edit_label.text().strip():
            self.edit_label.setFocus()
            return
        self.accept()

    def result_item(self):
        """返回用户输入构成的提醒事项字典。"""
        return {
            "id": uuid.uuid4().hex[:8],
            "label": self.edit_label.text().strip(),
            "time": self.edit_time.time().toString("HH:mm"),
            "kind": self.combo_kind.currentData(),
            "weekday": int(self.combo_week.currentData() or 0),
            "date": self.edit_date.date().toString("yyyy-MM-dd"),
            "enabled": True,
        }


class ReminderManageDialog(QDialog):
    """管理已添加的提醒事项：查看列表 + 删除。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理自定义提醒")
        self.resize(440, 280)

        self._items = config.get_custom_reminders()
        self.list_widget = QListWidget(self)
        self._reload()

        self.btn_delete = QPushButton("删除选中", self)
        self.btn_delete.clicked.connect(self._on_delete)
        btn_close = QPushButton("关闭", self)
        btn_close.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_delete)
        row.addWidget(btn_close)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("启用/停用请在托盘菜单里点对应条目切换", self))
        layout.addWidget(self.list_widget)
        layout.addLayout(row)

    def _reload(self) -> None:
        self.list_widget.clear()
        for item in self._items:
            self.list_widget.addItem(describe(item))

    def _on_delete(self) -> None:
        row = self.list_widget.currentRow()
        if row < 0 or row >= len(self._items):
            return
        config.remove_custom_reminder(self._items[row].get("id"))
        self._items = config.get_custom_reminders()
        self._reload()
