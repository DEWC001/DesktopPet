"""活跃度调节对话框（1.7.0 需求4）。

活跃度 0-100 联动两块：
- 睡觉占比：低活跃睡得久、容易回睡；高活跃睡得短、清醒久
- 活动强度：跳跃高度 / 散步步速（低活跃轻柔，高活跃活泼）
50 为默认档，与旧版行为一致。对话框只负责收集值，写配置由调用方做。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from . import config

# (档位下限, 说明文字)，取 value >= 下限的最后一条
_HINTS = [
    (0, "像猫一样慵懒：大部分时间在睡觉，偶尔醒来轻轻活动一下。"),
    (20, "比较安静：睡得偏多、动作轻，偶尔散步发呆。"),
    (40, "略偏安静：睡觉稍多，动作和缓。"),
    (50, "默认状态：睡觉与活动均衡，保持经典观感。"),
    (70, "比较活泼：睡觉变少，跳跃、散步更频繁。"),
    (100, "精力旺盛：很少睡觉，蹦蹦跳跳停不下来。"),
]


def hint_for(value: int) -> str:
    """按活跃度档位取说明文字。"""
    best = _HINTS[0][1]
    for level, text in _HINTS:
        if value >= level:
            best = text
        else:
            break
    return best


class ActivityDialog(QDialog):
    """滑块 + 数字框联动调节活跃度。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("活跃度调节")
        self.resize(400, 230)

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setValue(config.activity())

        self.spin = QSpinBox(self)
        self.spin.setRange(0, 100)
        self.spin.setSuffix(" %")
        self.spin.setValue(self.slider.value())
        self.slider.valueChanged.connect(self.spin.setValue)
        self.spin.valueChanged.connect(self.slider.setValue)

        self.lab_hint = QLabel(hint_for(self.slider.value()), self)
        self.lab_hint.setWordWrap(True)
        self.slider.valueChanged.connect(lambda v: self.lab_hint.setText(hint_for(v)))

        intro = QLabel(
            "活跃度 = 睡觉占比 + 活动强度（跳跃高度 / 散步速度）\n50 为默认档，与旧版行为一致",
            self,
        )
        intro.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(self.slider, 1)
        row.addWidget(self.spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(row)
        layout.addWidget(self.lab_hint)
        layout.addWidget(buttons)

    def result_value(self) -> int:
        """对话框确认后的活跃度（0-100）。"""
        return self.slider.value()
