"""程序化动画工具：跳跃动画。

跳跃 = 上抛 + 水平位移，落地停在新位置（不再做落地挤压拉伸，
避免窗口 resize 导致头部被裁剪和落地后的卡顿）。
"""
import math

from PySide6.QtCore import QEasingCurve, QVariantAnimation


def jump_animation(widget, dx: int = 0, height: int = 26, duration: int = 380) -> QVariantAnimation:
    """跳跃：先上抛、同时水平位移，落地停在新位置 (base_x+dx, base_y)。"""
    base_x = widget.x()
    base_y = widget.y()
    target_x = base_x + dx
    anim = QVariantAnimation(widget)
    anim.setDuration(duration)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutQuad)

    def on_value(v: float):
        dy = -height * math.sin(math.pi * v)
        widget.move(base_x + int(dx * v), base_y + int(dy))

    anim.valueChanged.connect(on_value)
    anim.finished.connect(lambda: widget.move(target_x, base_y))
    return anim
