"""量化 IM 未读监听的轮询开销：优化前 vs 优化后（实机 UIA 遍历计时）。

用途：确认自适应降频 + 任务栏缓存 + 标题复用到底省了多少，以及省下来的
CPU 是不是值得。数字会随机器和当前开了多少窗口而变，看相对比例即可。

运行：
    python scripts/bench_im_polling.py [轮次]
"""
import sys
import time

sys.path.insert(0, r"D:\杂\桌宠")

import uiautomation as auto  # noqa: E402

from pet.im_unread_watcher import ImUnreadWatcher as W  # noqa: E402

APPS = {
    "灵犀": ["灵犀"],
    "QQ": ["QQ"],
    "微信": ["微信", "WeChat"],
    "企业微信": ["企业微信", "WeCom"],
}


def bench(fn, n: int) -> float:
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n * 1000  # 毫秒/轮


def old_round():
    """优化前：每轮全量递归找任务栏 + 每个应用各枚举一次顶层窗口。"""
    root = auto.GetRootControl()
    tb = W._find_taskbar(root)
    if tb is None:
        return
    btns = []
    W._collect_buttons(tb, btns)
    for _name, kws in APPS.items():
        b = W._match_button(btns, kws)
        raw = W._is_unread(b) if b is not None else False
        if not raw:
            W._window_title_unread_from(W._collect_window_titles(root), kws)


def new_round(w, root_holder):
    """优化后：任务栏走缓存，标题每轮只收一次。"""
    root = auto.GetRootControl()
    root_holder["root"] = root
    btns = []
    tb = w._get_taskbar(root)
    if tb is not None:
        W._collect_buttons(tb, btns)
    if tb is not None and not btns:
        w._taskbar = None
        tb = w._get_taskbar(root, force=True)
        if tb is not None:
            W._collect_buttons(tb, btns)
    if tb is None:
        return
    titles = None
    for _name, kws in APPS.items():
        b = W._match_button(btns, kws)
        raw = W._is_unread(b) if b is not None else False
        if not raw:
            if titles is None:
                titles = W._collect_window_titles(root)
            W._window_title_unread_from(titles, kws)


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    auto.InitializeUIAutomationInCurrentThread()

    # 预热，避免首次 COM 调用的冷启动成本计入
    old_round()

    old_ms = bench(old_round, n)

    w = W()
    w._stop.set()
    holder: dict = {}
    new_round(w, holder)          # 预热（首轮要真找一次任务栏）
    new_ms = bench(lambda: new_round(w, holder), n)

    print(f"轮次: {n}")
    print(f"优化前: {old_ms:7.2f} ms/轮")
    print(f"优化后: {new_ms:7.2f} ms/轮")
    if new_ms > 0:
        print(f"减少:   {(1 - new_ms / old_ms) * 100:6.1f}%  （提速 {old_ms / new_ms:.2f}×）")

    print()
    print("折算成每秒开销（4 个受监测应用）：")
    print(f"  常速 2s 轮询: 优化前 {old_ms / 2000 * 100:.2f}% 单核 → 优化后 {new_ms / 2000 * 100:.2f}%")
    print(f"  空闲 15s 轮询: 优化后 {new_ms / 15000 * 100:.3f}% 单核")
    return 0


if __name__ == "__main__":
    sys.exit(main())
