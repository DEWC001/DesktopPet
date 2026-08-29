"""dump 当前通知中心所有 toast 的应用名，用于找出「灵犀」的确切显示名。"""
import sys

try:
    from winrt.windows.ui.notifications import NotificationKinds
    from winrt.windows.ui.notifications.management import UserNotificationListener
except Exception as e:
    print("import 失败:", e)
    sys.exit(1)

listener = UserNotificationListener.current
status = listener.get_access_status()
print("访问状态:", status, "(1 == ALLOWED)")
if status != 1:
    print("通知访问未授权，无法继续")
    sys.exit(2)

notifs = listener.get_notifications_async(NotificationKinds.TOAST).get()
print("当前通知条数:", len(notifs))
print("=" * 60)
seen = {}
for n in notifs:
    app_name = "?"
    try:
        app_name = n.app_info.display_info.display_name
    except Exception as e:
        app_name = f"<读取失败:{e}>"
    seen.setdefault(app_name, 0)
    seen[app_name] += 1
    texts = []
    try:
        for binding in n.notification.visual.bindings:
            for el in binding.get_text_elements():
                texts.append(el.text)
    except Exception as e:
        texts = [f"<读取失败:{e}>"]
    print(f"[{app_name}] id={n.id}")
    for t in texts:
        print("    ", repr(t))
    print("-" * 60)

print("=" * 60)
print("应用名汇总:")
for name, cnt in seen.items():
    print(f"  {name!r}  x{cnt}")
