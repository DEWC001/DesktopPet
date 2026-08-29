"""诊断灵犀未读信号：实时监控任务栏按钮（Name/Help/角标）与窗口标题。

用法：运行本脚本后，请用户用另一账号给电脑端灵犀发一条消息，
观察输出中「灵犀」相关条目的变化（90 秒自动结束）。
"""
import time

import uiautomation as auto


def find_taskbar(root):
    tb = [None]

    def _walk(c, d=0):
        if d > 8 or tb[0]:
            return
        try:
            if c.ClassName == "Shell_TrayWnd":
                tb[0] = c
                return
        except Exception:
            pass
        try:
            for ch in c.GetChildren():
                _walk(ch, d + 1)
        except Exception:
            pass

    _walk(root)
    return tb[0]


def dump_state(tag):
    root = auto.GetRootControl()
    print(f"--- {tag} ---")
    # 1) 任务栏中灵犀相关按钮
    tb = find_taskbar(root)
    if tb is not None:
        btns = []

        def _btns(c, d=0):
            if d > 12:
                return
            try:
                if "TaskListButton" in c.ClassName:
                    btns.append(c)
            except Exception:
                pass
            try:
                for ch in c.GetChildren():
                    _btns(ch, d + 1)
            except Exception:
                pass

        _btns(tb)
        found = False
        for b in btns:
            try:
                n = b.Name or ""
                if ("灵犀" in n) or ("lingxi" in n.lower()):
                    found = True
                    la = b.GetLegacyIAccessiblePattern()
                    help_t = (la.Help or "") if la is not None else "<无模式>"
                    print(f"  [任务栏按钮] Name={n!r} Help={help_t!r}")
            except Exception as e:
                print(f"  [任务栏按钮] 读取失败: {e}")
        if not found:
            print("  [任务栏按钮] 未找到灵犀按钮（窗口可能已缩到托盘/最小化）")
    else:
        print("  [任务栏] 未找到 Shell_TrayWnd")
    # 2) 顶层窗口中的灵犀/飞书窗口标题
    try:
        wins = root.GetChildren()
    except Exception:
        wins = []
    for w in wins:
        try:
            n = w.Name or ""
            if ("灵犀" in n) or ("飞书" in n) or ("lingxi" in n.lower()):
                print(f"  [窗口] ClassName={w.ClassName!r} Name={n!r}")
        except Exception:
            pass
    sys.stdout.flush()


def main():
    print(">>> 开始监控 300 秒。请现在用另一账号向电脑端灵犀发一条消息（或让同事发）。")
    print(">>> 观察下面灵犀条目的变化：Name 是否带 (N) 角标 / Help 是否变「已请求注意」。")
    start = time.time()
    while time.time() - start < 300:
        try:
            dump_state(f"t+{int(time.time() - start)}s")
        except Exception as e:
            print("监控异常:", e)
        time.sleep(3)
    print(">>> 监控结束。")


if __name__ == "__main__":
    import sys

    main()
