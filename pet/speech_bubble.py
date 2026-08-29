"""说话气泡：圆角白底 + 阴影 + 小尾巴。"""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QLabel,
    QWidget,
)

TAIL_H = 10
RADIUS = 16
PAD_L, PAD_T, PAD_R, PAD_B = 18, 12, 18, 16
MARGIN = 22  # 四周留白，容纳阴影
MAX_W = 280


class BubbleBody(QWidget):
    """气泡主体：白底圆角 + 底部小尾巴，带投影。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 65))
        self.setGraphicsEffect(shadow)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        body_h = h - TAIL_H
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255))
        p.drawRoundedRect(0, 0, w, body_h, RADIUS, RADIUS)
        cx = w // 2
        tw = 18
        p.drawPolygon(QPolygon([
            QPoint(cx - tw // 2, body_h - 2),
            QPoint(cx + tw // 2, body_h - 2),
            QPoint(cx, h),
        ]))


class SpeechBubble(QWidget):
    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self.body = BubbleBody(self)
        self.label = QLabel(self.body)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(
            "color:#3a3a3a; font-size:14px; font-weight:600;"
            "font-family:'Microsoft YaHei','PingFang SC','Microsoft YaHei UI';"
        )

        self._anchor = None
        self._offset_y = -6

    def _layout(self, text: str) -> None:
        self.label.setText(text)
        lw = min(self.label.sizeHint().width(), MAX_W)
        self.label.setFixedWidth(lw)
        lh = self.label.heightForWidth(lw)
        self.label.setFixedSize(lw, lh)
        bw = lw + PAD_L + PAD_R
        bh = lh + PAD_T + PAD_B + TAIL_H
        self.body.setGeometry(MARGIN, MARGIN, bw, bh)
        self.label.move(PAD_L, PAD_T)
        self.setFixedSize(bw + MARGIN * 2, bh + MARGIN * 2)

    def show_text(self, text: str, anchor: QWidget, offset_y: int = -6) -> None:
        self._layout(text)
        self._anchor = anchor
        self._offset_y = offset_y
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self) -> None:
        if self._anchor is None:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        a = self._anchor
        tail_y = MARGIN + self.body.height()  # 尾巴尖相对本窗口顶部的位置
        x = a.x() + (a.width() - self.width()) // 2
        y = a.y() - tail_y + self._offset_y
        x = max(screen.left() + 2, min(x, screen.right() - self.width() - 2))
        y = max(screen.top() + 2, y)
        self.move(x, y)

    def reposition(self) -> None:
        self._reposition()

