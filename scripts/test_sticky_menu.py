"""StickyMenu（需求1：点选项不关闭）与 ActivityDialog（需求4）单元测试。

1.7.0 新增两类 UI 件的核心逻辑都在这两个类里：
- StickyMenu.mouseReleaseEvent：命中可用叶子 action 时手动 trigger 且不关菜单
- ActivityDialog：滑块/数字框双向联动 + 档位说明 + 默认值跟随配置

运行：
    QT_QPA_PLATFORM=offscreen python scripts/test_sticky_menu.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet import config  # noqa: E402
from pet.activity_dialog import ActivityDialog, hint_for  # noqa: E402
from pet.sticky_menu import StickyMenu  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()


def assert_true(cond, msg="断言失败"):
    if not cond:
        raise AssertionError(msg)


def release_at(menu, pos):
    """合成一次鼠标释放事件并派发给菜单（等价于用户点了一下）。"""
    e = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(pos),
        QPointF(pos),
        QPointF(pos),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    menu.mouseReleaseEvent(e)


def popup_menu(menu):
    menu.popup(QPoint(0, 0))
    QApplication.processEvents()


def geom_center(menu, act):
    g = menu.actionGeometry(act)
    assert_true(not g.isNull(), f"actionGeometry 为空（布局未生效？）: {act.text()}")
    return g.center()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    print("[1] StickyMenu：点选项不关闭")
    menu = StickyMenu()
    a_plain = menu.addAction("普通选项")
    a_check = menu.addAction("勾选项")
    a_check.setCheckable(True)
    a_check.setChecked(False)
    sub = menu.addMenu("子菜单")
    a_sub = sub.addAction("子项")
    menu.addSeparator()
    a_sep = None  # addSeparator 返回的 action 在 PySide6 里拿得到
    fired = []
    a_plain.triggered.connect(lambda: fired.append("plain"))
    a_check.toggled.connect(lambda on: fired.append(f"check:{on}"))

    def t_popup_visible():
        popup_menu(menu)
        assert_true(menu.isVisible(), "popup 后菜单应可见")

    check("popup 后菜单可见", t_popup_visible)

    def t_leaf_sticky():
        """点普通选项：trigger 发出且菜单保持打开（需求1 核心）。"""
        fired.clear()
        release_at(menu, geom_center(menu, a_plain))
        assert_true(fired == ["plain"], f"选项应被触发: {fired}")
        assert_true(menu.isVisible(), "点选项后菜单不应关闭")

    check("点普通选项触发且菜单不关闭", t_leaf_sticky)

    def t_checkable_toggle():
        """点勾选项：checked 翻转且菜单保持打开。"""
        fired.clear()
        before = a_check.isChecked()
        release_at(menu, geom_center(menu, a_check))
        assert_true(a_check.isChecked() == (not before), "勾选状态应翻转")
        assert_true(fired == [f"check:{not before}"], f"toggled 应发出: {fired}")
        assert_true(menu.isVisible(), "点勾选项后菜单不应关闭")
        # 还原
        release_at(menu, geom_center(menu, a_check))

    check("点勾选项翻转且菜单不关闭", t_checkable_toggle)

    def t_multiple_clicks():
        """连续点多个选项都能触发（这正是"不关闭"的价值）。"""
        fired.clear()
        release_at(menu, geom_center(menu, a_plain))
        release_at(menu, geom_center(menu, a_plain))
        release_at(menu, geom_center(menu, a_plain))
        assert_true(fired.count("plain") == 3, f"连点 3 次应触发 3 次: {fired}")

    check("连续点同一选项多次全部生效", t_multiple_clicks)

    def t_submenu_parent():
        """点在子菜单父项：不手动 trigger（交给默认导航弹出子菜单）。"""
        fired.clear()
        parent_geo = menu.actionGeometry(sub.menuAction())
        release_at(menu, parent_geo.center())
        assert_true(fired == [], "子菜单父项不应被当作叶子触发")
        assert_true(a_sub.parent() is sub, "子菜单结构保持")

    check("点子菜单父项不误触发", t_submenu_parent)

    def t_separator_noop():
        """点在分隔符：无动作不崩溃。"""
        seps = [a for a in menu.actions() if a.isSeparator()]
        assert_true(seps, "应有分隔符")
        fired.clear()
        g = menu.actionGeometry(seps[0])
        if not g.isNull():
            release_at(menu, g.center())
        assert_true(fired == [], "分隔符不应触发任何选项")

    check("点分隔符无副作用", t_separator_noop)

    def t_blank_noop():
        """点在菜单空白处：不触发任何 action（走默认行为收起）。"""
        fired.clear()
        # 菜单右下空白（若有布局空白区）；取一个肯定不属于 action 的坐标
        w = menu.width()
        pos = QPoint(min(w - 2, 3), menu.height() - 2)
        act = menu.actionAt(pos)
        if act is None:
            release_at(menu, pos)
            assert_true(fired == [], "空白处不应触发任何选项")
        # 若整窗都是 action（窄菜单），则跳过该分支

    check("点空白处不触发选项", t_blank_noop)

    menu.close()

    print("[2] ActivityDialog：滑块/数字联动 + 档位说明")

    def t_default_value():
        old = config.activity()
        config.set_value("activity", old)  # 确保与配置一致
        dlg = ActivityDialog()
        assert_true(dlg.slider.value() == old, f"slider 应默认 {old}")
        assert_true(dlg.spin.value() == old, f"spin 应默认 {old}")
        assert_true(dlg.result_value() == old, "result_value 应等于当前值")

    check("默认值跟随配置", t_default_value)

    def t_slider_spin_sync():
        dlg = ActivityDialog()
        dlg.slider.setValue(90)
        QApplication.processEvents()
        assert_true(dlg.spin.value() == 90, f"spin 应联动到 90: {dlg.spin.value()}")
        dlg.spin.setValue(10)
        QApplication.processEvents()
        assert_true(dlg.slider.value() == 10, f"slider 应联动到 10: {dlg.slider.value()}")
        assert_true(dlg.result_value() == 10, "result_value 应跟随")

    check("滑块与数字框双向联动", t_slider_spin_sync)

    def t_hint_updates():
        dlg = ActivityDialog()
        dlg.slider.setValue(5)
        QApplication.processEvents()
        assert_true(dlg.lab_hint.text() == hint_for(5), "hint 应显示低活跃说明")
        dlg.slider.setValue(95)
        QApplication.processEvents()
        assert_true(dlg.lab_hint.text() == hint_for(95), "hint 应显示高活跃说明")

    check("说明文字随档位变化", t_hint_updates)

    def t_hint_boundaries():
        expect = {0: 0, 19: 0, 20: 20, 49: 40, 50: 50, 69: 50, 70: 70, 100: 100}
        for v, level in expect.items():
            got = hint_for(v)
            assert_true(got == hint_for(level), f"hint_for({v}) 应等于 {level} 档文案")

    check("档位边界文案正确", t_hint_boundaries)

    def t_range_clamp():
        dlg = ActivityDialog()
        dlg.slider.setValue(-5)  # QSlider 会钳到最小值
        assert_true(dlg.slider.value() == 0, "越界输入应钳到 0")
        dlg.spin.setValue(500)
        assert_true(dlg.slider.value() == 100, "越界输入应钳到 100")

    check("输入越界自动钳制", t_range_clamp)

    def t_config_unchanged():
        """对话框本身不写配置（写配置是托盘回调的职责）。"""
        before = config.activity()
        dlg = ActivityDialog()
        dlg.slider.setValue(80)
        assert_true(config.activity() == before, "对话框不应直接改配置")

    check("对话框不直接写配置", t_config_unchanged)

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
