"""点选项不关闭的右键菜单（1.7.0 需求1）。

Windows 托盘如果通过 QSystemTrayIcon.setContextMenu() 注册，右键时走的是
系统原生菜单（TrackPopupMenu），QMenu 子类的事件钩子完全不生效——要拦截
点击保持菜单打开，必须放弃 setContextMenu，改由 activated(Context) 手动
popup() 出本类菜单。宠物本体右键复用同一个菜单对象（window.contextMenuEvent
里已经用 tray.menu.popup()），所以只要这一个类就能同时覆盖两个入口。

原理：QMenu 默认在鼠标松开于某个 action 上时触发动作并收起整个菜单。
这里拦下 mouseReleaseEvent，改成"手动 trigger 该 action 且不关菜单"，
用户就能连续点多个选项（比如一次勾掉好几个提醒开关）。
"""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu


class StickyMenu(QMenu):
    """点选项后保持弹出状态的菜单。

    - 点在可用的叶子 action 上：手动触发动作，菜单不关闭
    - 点在带子菜单的父项上：交给默认逻辑（子菜单导航）
    - 点在空白处 / 菜单外点击 / Esc：仍按默认方式收起
    """

    def mouseReleaseEvent(self, e) -> None:
        pos = e.position().toPoint() if hasattr(e.position(), "toPoint") else QPoint(e.x(), e.y())
        act = self.actionAt(pos)
        if act is not None and not act.isSeparator() and act.menu() is None and act.isEnabled():
            # 命中可执行选项：手动触发并保持菜单打开
            e.accept()
            act.trigger()
            return
        # 空白处 / 子菜单父项 / 分隔符：交给默认行为
        super().mouseReleaseEvent(e)
