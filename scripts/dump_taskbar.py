"""dump 当前任务栏所有按钮的 UIA 信息，用于确认 QQ/微信/企微/灵犀按钮的定位字段。

重点看：ClassName / AutomationId / Name / LegacyIAccessible.Help（「请求注意」状态）。
"""
import uiautomation as auto


def find_taskbar(ctrl, depth=0):
    if depth > 10:
        return None
    try:
        if ctrl.ClassName == "Shell_TrayWnd":
            return ctrl
    except Exception:
        pass
    try:
        for c in ctrl.GetChildren():
            r = find_taskbar(c, depth + 1)
            if r is not None:
                return r
    except Exception:
        pass
    return None


def find_buttons(ctrl, out, depth=0):
    if depth > 12:
        return
    try:
        cls = ctrl.ClassName
        if "TaskListButton" in cls or "Taskbar" in cls or "Button" in cls:
            try:
                la = ctrl.GetLegacyIAccessiblePattern()
                help_text = (la.Help or "") if la is not None else "<无>"
            except Exception:
                help_text = "<读不到>"
            out.append((cls, ctrl.AutomationId, ctrl.Name, help_text))
    except Exception:
        pass
    try:
        for c in ctrl.GetChildren():
            find_buttons(c, out, depth + 1)
    except Exception:
        pass


def main():
    root = auto.GetRootControl()
    print("Root:", root.ClassName, "|", root.Name)
    taskbar = find_taskbar(root)
    if taskbar is None:
        print("!! 未找到 Shell_TrayWnd")
        return
    print("Taskbar:", taskbar.ClassName, "|", taskbar.Name)
    print("=" * 80)

    buttons = []
    find_buttons(taskbar, buttons)
    for cls, aid, name, help_text in buttons:
        # 只关注 TaskListButton 类型的任务栏应用按钮
        if "TaskListButton" in cls:
            print(f"Class    : {cls}")
            print(f"AutoId   : {aid}")
            print(f"Name     : {name!r}")
            print(f"Help     : {help_text!r}")
            print("-" * 80)


if __name__ == "__main__":
    main()
