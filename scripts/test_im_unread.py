"""自测 IM 未读监视器的匹配 / 未读判断逻辑（不启动 Qt 主循环）。

直接复用 ImUnreadWatcher 的静态方法，对当前任务栏按钮做一次检测，
确认灵犀能被正确匹配、未读判断符合预期。
"""
import sys

sys.path.insert(0, r"D:\杂\桌宠")

import uiautomation as auto
from pet.im_unread_watcher import HOLD_SECONDS, ImUnreadWatcher as W


def main():
    # 1) 纯逻辑自测：按钮名匹配
    cases = [
        ("灵犀 - 1 个运行窗口", ["灵犀"], True),
        ("QQ (3)", ["QQ"], True),
        ("QQ - 1 个运行窗口", ["QQ"], True),
        ("QQ音乐 - 1 个运行窗口", ["QQ"], False),   # 不能误匹配
        ("微信", ["微信", "WeChat"], True),
        ("企业微信 - 2 个运行窗口", ["企业微信", "WeCom"], True),
        ("Google Chrome - 1 个运行窗口", ["QQ", "微信"], False),
    ]
    print("== 按钮名匹配自测 ==")
    for name, kws, expect in cases:
        got = any(W._name_matches(name, kw) for kw in kws)
        print(f"  {'PASS' if got == expect else 'FAIL'}  {name!r} vs {kws} -> {got} (期望 {expect})")

    # 2) 未读判断逻辑自测（用假对象）
    print("== 未读判断自测 ==")
    class FakeBtn:
        def __init__(self, help_text, name):
            self._help = help_text
            self.Name = name
        def GetLegacyIAccessiblePattern(self):
            return type("P", (), {"Help": self._help})()
    for help_text, name, expect in [
        ("已请求注意", "QQ", True),       # flashFrame 信号
        ("", "QQ", False),
        ("QQ 已固定", "QQ", False),       # 固定按钮不是未读
        ("", "QQ (5)", True),             # 角标信号
        ("", "灵犀 - 1 个运行窗口", False),
        ("需要关注", "微信", True),
    ]:
        got = W._is_unread(FakeBtn(help_text, name))
        print(f"  {'PASS' if got == expect else 'FAIL'}  help={help_text!r} name={name!r} -> {got} (期望 {expect})")

    # 2b) 窗口标题角标兜底自测
    print("== 窗口标题角标兜底自测 ==")
    class FakeWin:
        def __init__(self, name):
            self.Name = name
    class FakeRoot:
        def __init__(self, wins):
            self._wins = wins
        def GetChildren(self):
            return self._wins
    for wins, kws, expect in [
        ([FakeWin("QQ (3)")], ["QQ"], True),
        ([FakeWin("QQ - 2 个运行窗口")], ["QQ"], False),  # 多窗口合并名，角标不在这里
        ([FakeWin("QQ音乐 (3)")], ["QQ"], False),          # 不能误匹配
        ([FakeWin("企业微信 (2)"), FakeWin("Chrome")], ["企业微信", "WeCom"], True),
        ([FakeWin("Chrome - Google")], ["QQ", "微信"], False),
        ([FakeWin("灵犀")], ["灵犀", "lingxi"], False),     # 无角标
    ]:
        got = W._window_title_unread(FakeRoot(wins), kws)
        print(f"  {'PASS' if got == expect else 'FAIL'}  wins={[w.Name for w in wins]} vs {kws} -> {got} (期望 {expect})")

    # 2c) 未读保持（去抖）自测
    print("== 未读去抖保持自测 ==")
    watcher = W()           # 实例化（若配置开启会拉起后台线程）
    watcher._stop.set()     # 立即停线程，测试仅用 _debounce 纯逻辑
    watcher._last_true_time.clear()
    now = 1000.0
    cases = [
        # (首次检测未读 -> True)
        (True, now, True),
        # 信号短暂消失(2s < HOLD) -> 仍保持 True
        (False, now + 2.0, True),
        # 超过 HOLD(HOLD+2s) -> 回落 False
        (False, now + HOLD_SECONDS + 2.0, False),
        # 再次未读 -> True 并重置计时
        (True, now + HOLD_SECONDS + 3.0, True),
        # 消失 5s -> 仍保持
        (False, now + HOLD_SECONDS + 8.0, True),
    ]
    for raw, t, expect in cases:
        got = watcher._debounce("测试应用", raw, t)
        print(f"  {'PASS' if got == expect else 'FAIL'}  raw={raw} t=+{t - now:.0f}s -> {got} (期望 {expect})")

    # 3) 实机检测：对当前任务栏真实按钮跑一遍
    print("== 实机任务栏检测 ==")
    root = auto.GetRootControl()
    taskbar = W._find_taskbar(root)
    if taskbar is None:
        print("  未找到任务栏")
        return
    buttons = []
    W._collect_buttons(taskbar, buttons)
    for app_name, kws in [("灵犀", ["灵犀"]), ("QQ", ["QQ"]), ("微信", ["微信"]), ("企业微信", ["企业微信"])]:
        btn = W._match_button(buttons, kws)
        if btn is None:
            print(f"  {app_name}: 按钮不存在（未运行）")
        else:
            unread = W._is_unread(btn)
            print(f"  {app_name}: 按钮名={btn.Name!r}, 未读={unread}")


if __name__ == "__main__":
    main()
