"""dump 系统托盘（右下角通知区域）所有图标按钮的 UIA 信息。

用途：确认灵犀/飞书缩到托盘后，托盘图标的 Name / Tooltip 是否携带未读状态
（例如「灵犀 (3)」「灵犀 - 3 条新消息」或 Tooltip 变化）。
"""
import uiautomation as auto


def find_tray(root):
    """定位通知区域 TrayNotifyWnd。"""
    out = []

    def _walk(c, d=0):
        if d > 10:
            return
        try:
            if c.ClassName == "TrayNotifyWnd":
                out.append(c)
        except Exception:
            pass
        try:
            for ch in c.GetChildren():
                _walk(ch, d + 1)
        except Exception:
            pass

    _walk(root)
    return out


def dump_control(c, indent=0, depth=0):
    if depth > 8:
        return
    pad = "  " * indent
    try:
        cls = c.ClassName or ""
        name = c.Name or ""
        aid = c.AutomationId or ""
        # Tooltip：UIA 里 Name 常即 Tooltip；再尝试读 LegacyIAccessible
        help_t = ""
        try:
            la = c.GetLegacyIAccessiblePattern()
            if la is not None:
                help_t = la.Help or ""
        except Exception:
            pass
        if name or ("Button" in cls) or ("Toolbar" in cls):
            print(f"{pad}Class={cls!r} Name={name!r} AID={aid!r} Help={help_t!r}")
    except Exception:
        return
    try:
        for ch in c.GetChildren():
            dump_control(ch, indent + 1, depth + 1)
    except Exception:
        pass


def main():
    root = auto.GetRootControl()
    trays = find_tray(root)
    if not trays:
        print("!! 未找到 TrayNotifyWnd")
        return
    for i, t in enumerate(trays):
        print(f"===== 托盘区 #{i + 1} ({t.ClassName}) =====")
        dump_control(t)
        print()


if __name__ == "__main__":
    main()
