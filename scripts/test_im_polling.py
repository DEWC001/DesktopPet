"""IM 未读监听的自适应降频 + 轮询优化自测（不启动 Qt 主循环）。

背景：改造前每 2 秒做一轮全量 UIA 遍历，且每个受监测应用各枚举一遍顶层
窗口（4 个应用 = 每秒 2 轮 × 4 次）。改成：
  1. 任务栏控件缓存（TTL + 取不到按钮时强制重找）
  2. _find_taskbar 先扫根的直接子节点（Shell_TrayWnd 通常就在这一层）
  3. 顶层窗口标题每轮只收集一次，各应用复用
  4. 没有任何受监测 IM 在跑时降频到 POLL_SECONDS_IDLE

本测试的核心诉求：**优化不能改变检测结果**。所以大量用例是「改造前后行为
必须一致」的等价性校验，并用计数器验证遍历次数确实降下来了。

运行：
    python scripts/test_im_polling.py
"""
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pet.im_unread_watcher import (  # noqa: E402
    POLL_SECONDS,
    POLL_SECONDS_IDLE,
    TASKBAR_CACHE_SECONDS,
    ImUnreadWatcher as W,
)

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
        traceback.print_exc()


def assert_eq(got, expect, what=""):
    if got != expect:
        raise AssertionError(f"{what} 实际 {got!r}，期望 {expect!r}")


# ---------------- 假 UIA 对象 ----------------
class FakeNode:
    def __init__(self, class_name="", name="", children=None):
        self.ClassName = class_name
        self.Name = name
        self._children = children if children is not None else []
        self.children_calls = 0

    def GetChildren(self):
        self.children_calls += 1
        return self._children


class FakeRoot:
    def __init__(self, children):
        self.ClassName = "#32769"       # 桌面根
        self.Name = "Desktop"
        self._children = children
        self.children_calls = 0

    def GetChildren(self):
        self.children_calls += 1
        return self._children


class FakeAuto:
    """伪装成 uiautomation 模块，只提供 _poll 用到的 GetRootControl。"""

    def __init__(self, root):
        self.root = root
        self.root_calls = 0

    def GetRootControl(self):
        self.root_calls += 1
        return self.root


def make_watcher(apps=None) -> W:
    """构造一个不跑后台线程的 watcher（测试只测轮询逻辑）。"""
    w = W()
    w._stop.set()
    if apps is not None:
        w._enabled_apps = apps
    return w


def build_scenario(with_qq_button: bool, qq_unread: bool = False):
    """构造：根 -> [大子树, 任务栏, QQ 顶层窗口(带角标)]。"""
    deep = FakeNode("Chrome_WidgetWin_1", "Chrome - 1", [
        FakeNode("Pane", "p1", [FakeNode("Button", "b1")]),
        FakeNode("Pane", "p2", [FakeNode("Button", "b2")]),
    ])
    buttons = []
    if with_qq_button:
        name = "QQ (3)" if qq_unread else "QQ"
        buttons.append(FakeNode("TaskListButton", name))
    buttons.append(FakeNode("TaskListButton", "Chrome - 1"))
    taskbar = FakeNode("Shell_TrayWnd", "", buttons)
    qq_window = FakeNode("Window", "QQ (3)" if qq_unread else "QQ")
    root = FakeRoot([deep, taskbar, qq_window])
    return root, taskbar, deep


# ---------------- 用例 ----------------
def t_find_taskbar_fast_path():
    """任务栏在根的直接子节点时，不应递归进其他顶层窗口的子树。"""
    root, taskbar, deep = build_scenario(True)
    got = W._find_taskbar(root)
    assert_eq(got is taskbar, True, "应找到任务栏")
    assert_eq(deep.children_calls, 0, "快路径命中后不应递归进无关子树")


def t_find_taskbar_deep_fallback():
    """任务栏不在直接子节点时，递归兜底仍要能找到（不能因为优化而漏检）。"""
    taskbar = FakeNode("Shell_TrayWnd", "")
    mid = FakeNode("Pane", "mid", [FakeNode("Pane", "inner", [taskbar])])
    root = FakeRoot([FakeNode("Chrome_WidgetWin_1", "Chrome"), mid])
    got = W._find_taskbar(root)
    assert_eq(got is taskbar, True, "深层任务栏也应能找到")


def t_find_taskbar_missing():
    root = FakeRoot([FakeNode("Chrome_WidgetWin_1", "Chrome")])
    assert_eq(W._find_taskbar(root), None, "没有任务栏应返回 None")


def t_collect_titles():
    root = FakeRoot([
        FakeNode("Window", "QQ (3)"),
        FakeNode("Window", "Chrome"),
        FakeNode("Window", ""),          # 空标题应跳过
    ])
    titles = W._collect_window_titles(root)
    assert_eq(titles, ["QQ (3)", "Chrome"], "标题收集")


def t_collect_titles_exception():
    class Boom:
        ClassName = "#32769"

        def GetChildren(self):
            raise RuntimeError("COM 挂了")

    assert_eq(W._collect_window_titles(Boom()), [], "异常应返回空列表而不是抛出")


def t_title_unread_from_equivalence():
    """与改造前 _window_title_unread 完全相同的判定用例，确保行为没变。"""
    cases = [
        (["QQ (3)"], ["QQ"], True),
        (["QQ - 2 个运行窗口"], ["QQ"], False),
        (["QQ音乐 (3)"], ["QQ"], False),
        (["企业微信 (2)", "Chrome"], ["企业微信", "WeCom"], True),
        (["Chrome - Google"], ["QQ", "微信"], False),
        (["灵犀"], ["灵犀", "lingxi"], False),
        ([], ["QQ"], False),
    ]
    for titles, kws, expect in cases:
        got = W._window_title_unread_from(titles, kws)
        assert_eq(got, expect, f"titles={titles} kws={kws}")


def t_window_title_unread_backward_compat():
    """老的 root 版接口要继续可用（scripts/test_im_unread.py 在用）。"""

    class FakeWin:
        def __init__(self, name):
            self.Name = name

    class FR:
        def __init__(self, wins):
            self._wins = wins

        def GetChildren(self):
            return self._wins

    assert_eq(W._window_title_unread(FR([FakeWin("QQ (3)")]), ["QQ"]), True)
    assert_eq(W._window_title_unread(FR([FakeWin("QQ")]), ["QQ"]), False)


def t_taskbar_cache_hit():
    """缓存有效期内不应重新查找任务栏。"""
    w = make_watcher()
    root, taskbar, _ = build_scenario(True)
    first = w._get_taskbar(root)
    calls_after_first = root.children_calls
    assert_eq(first is taskbar, True, "首次应找到任务栏")
    second = w._get_taskbar(root)
    assert_eq(second is first, True, "缓存内应返回同一对象")
    assert_eq(root.children_calls, calls_after_first, "缓存命中不应再次遍历")


def t_taskbar_cache_ttl():
    w = make_watcher()
    root, taskbar, _ = build_scenario(True)
    w._get_taskbar(root)
    calls = root.children_calls
    w._taskbar_time = time.monotonic() - TASKBAR_CACHE_SECONDS - 1
    w._get_taskbar(root)
    assert root.children_calls > calls, "超过 TTL 应重新查找"


def t_taskbar_cache_force():
    w = make_watcher()
    root, taskbar, _ = build_scenario(True)
    w._get_taskbar(root)
    calls = root.children_calls
    w._get_taskbar(root, force=True)
    assert root.children_calls > calls, "force=True 应强制重新查找"


def t_stale_cache_retry():
    """缓存失效（静默返回空按钮）时必须重找一次，不能长时间漏检。"""
    w = make_watcher({"QQ": ["QQ"]})
    root, taskbar, _ = build_scenario(True)
    # 塞一个「已失效」的空任务栏缓存
    w._taskbar = FakeNode("Shell_TrayWnd", "", [])
    w._taskbar_time = time.monotonic()
    auto = FakeAuto(root)
    w._poll(auto, silent=True)
    assert_eq(w._idle, False, "应通过重找发现 QQ 在运行，而不是误判空闲")


def t_titles_collected_once():
    """一轮轮询里，顶层窗口标题只能枚举一次（改造前是每应用一次）。"""
    w = make_watcher({"QQ": ["QQ"], "微信": ["微信"], "企业微信": ["企业微信"], "灵犀": ["灵犀"]})
    root, _, _ = build_scenario(False)
    auto = FakeAuto(root)
    w._poll(auto, silent=True)          # 首轮：找任务栏 + 收标题
    root.children_calls = 0
    w._poll(auto, silent=True)          # 次轮：任务栏走缓存，只应再收一次标题
    assert_eq(root.children_calls, 1, "次轮顶层窗口只应枚举一次（任务栏走缓存）")


def t_idle_when_no_app():
    """没有任何受监测 IM 运行 → 降频。"""
    w = make_watcher({"QQ": ["QQ"]})
    root, _, _ = build_scenario(False)
    w._enabled_apps = {"QQ": ["QQ"]}
    w._poll(FakeAuto(root), silent=True)
    assert_eq(w._idle, True, "无 IM 运行应进入降频")
    assert_eq(w._current_interval(), POLL_SECONDS_IDLE, "降频间隔")


def t_active_when_app_running():
    """只要检测到目标应用就恢复常速，不能因为优化漏掉。"""
    w = make_watcher({"QQ": ["QQ"]})
    root, _, _ = build_scenario(True)
    w._enabled_apps = {"QQ": ["QQ"]}
    w._poll(FakeAuto(root), silent=True)
    assert_eq(w._idle, False, "检测到 QQ 应恢复常速")
    assert_eq(w._current_interval(), POLL_SECONDS, "常速间隔")


def t_idle_recovery_transition():
    """空闲 → 应用启动 → 立刻恢复常速。"""
    w = make_watcher({"QQ": ["QQ"]})
    root_no, _, _ = build_scenario(False)
    w._enabled_apps = {"QQ": ["QQ"]}
    w._poll(FakeAuto(root_no), silent=True)
    assert_eq(w._idle, True, "先进入降频")
    root_yes, _, _ = build_scenario(True)
    w._taskbar = None                    # 换场景，丢掉缓存
    w._poll(FakeAuto(root_yes), silent=True)
    assert_eq(w._idle, False, "IM 出现后应立即恢复常速")


def t_active_to_idle_transition():
    """应用退出 → 降频。"""
    w = make_watcher({"QQ": ["QQ"]})
    root_yes, _, _ = build_scenario(True)
    w._enabled_apps = {"QQ": ["QQ"]}
    w._poll(FakeAuto(root_yes), silent=True)
    assert_eq(w._idle, False, "先常速")
    root_no, _, _ = build_scenario(False)
    w._taskbar = None
    w._poll(FakeAuto(root_no), silent=True)
    assert_eq(w._idle, True, "IM 退出后应降频")


def t_taskbar_none_goes_idle():
    """找不到任务栏时降频，避免无谓的高速重试。"""
    w = make_watcher({"QQ": ["QQ"]})
    w._enabled_apps = {"QQ": ["QQ"]}
    w._taskbar = None
    root = FakeRoot([FakeNode("Chrome_WidgetWin_1", "Chrome")])
    w._poll(FakeAuto(root), silent=True)
    assert_eq(w._idle, True, "无任务栏应降频")


def t_unread_detection_unchanged():
    """最关键的等价性：按钮带角标时仍要判为未读（优化不能改变检测结果）。"""
    w = make_watcher({"QQ": ["QQ"]})
    w._enabled_apps = {"QQ": ["QQ"]}
    w._last_true_time.clear()
    root, _, _ = build_scenario(True, qq_unread=True)
    w._poll(FakeAuto(root), silent=True)
    assert_eq(w.is_unread("QQ"), True, "QQ (3) 应判为未读")


def t_no_unread_when_clean():
    w = make_watcher({"QQ": ["QQ"]})
    w._enabled_apps = {"QQ": ["QQ"]}
    w._last_true_time.clear()
    root, _, _ = build_scenario(True, qq_unread=False)
    w._poll(FakeAuto(root), silent=True)
    assert_eq(w.is_unread("QQ"), False, "干净状态不应误报未读")


def t_window_title_fallback_still_works():
    """任务栏无按钮，但顶层窗口标题带角标 —— 兜底路径仍要生效。"""
    w = make_watcher({"QQ": ["QQ"]})
    w._enabled_apps = {"QQ": ["QQ"]}
    w._last_true_time.clear()
    root, taskbar, _ = build_scenario(False)
    taskbar._children = [FakeNode("TaskListButton", "Chrome - 1")]   # 任务栏里没有 QQ
    qq_window = FakeNode("Window", "QQ (7)")
    root._children = root._children[:-1] + [qq_window]
    w._poll(FakeAuto(root), silent=True)
    assert_eq(w.is_unread("QQ"), True, "窗口标题兜底应生效")
    assert_eq(w._idle, False, "兜底命中也算发现应用，不该降频")


def main() -> int:
    print("== 任务栏查找 ==")
    check("任务栏在直接子节点时走快路径", t_find_taskbar_fast_path)
    check("任务栏在深层时递归兜底仍能找到", t_find_taskbar_deep_fallback)
    check("无任务栏返回 None", t_find_taskbar_missing)

    print("== 顶层窗口标题 ==")
    check("标题收集（跳过空标题）", t_collect_titles)
    check("GetChildren 异常时安全返回空", t_collect_titles_exception)
    check("角标判定与改造前完全一致", t_title_unread_from_equivalence)
    check("老接口 _window_title_unread 仍可用", t_window_title_unread_backward_compat)

    print("== 任务栏缓存 ==")
    check("缓存有效期内不重复查找", t_taskbar_cache_hit)
    check("超过 TTL 重新查找", t_taskbar_cache_ttl)
    check("force=True 强制重新查找", t_taskbar_cache_force)
    check("缓存失效（空按钮）时重找一次", t_stale_cache_retry)

    print("== 轮询开销 ==")
    check("顶层窗口每轮只枚举一次", t_titles_collected_once)

    print("== 自适应降频 ==")
    check("无 IM 运行时降频", t_idle_when_no_app)
    check("有 IM 运行时常速", t_active_when_app_running)
    check("空闲→IM 出现→恢复常速", t_idle_recovery_transition)
    check("常速→IM 退出→降频", t_active_to_idle_transition)
    check("找不到任务栏时降频", t_taskbar_none_goes_idle)

    print("== 检测结果等价性（核心功能不能回退）==")
    check("按钮角标未读仍能检出", t_unread_detection_unchanged)
    check("干净状态不误报", t_no_unread_when_clean)
    check("窗口标题兜底仍生效", t_window_title_fallback_still_works)

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
