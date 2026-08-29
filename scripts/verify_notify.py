"""探测 winrt 通知读取：dump 当前通知中心里的 toast 通知。
验证能否读到 应用名 / 标题 / 正文，为飞书监听做准备。
"""
import sys

try:
    from winrt.windows.ui.notifications.management import (
        UserNotificationListener,
        UserNotificationListenerAccessStatus,
    )
    from winrt.windows.ui.notifications import NotificationKinds
except Exception as e:
    print("import 失败:", e)
    sys.exit(1)

listener = UserNotificationListener.current
status = listener.get_access_status()
print("访问状态:", status, "(" + UserNotificationListenerAccessStatus(status).name + ")")

if status != UserNotificationListenerAccessStatus.ALLOWED:
    print("通知访问未授权，无法继续")
    sys.exit(2)

notifs = listener.get_notifications(NotificationKinds.toast)
print("当前通知条数:", len(notifs))
print("-" * 60)
for n in notifs:
    app_name = "?"
    try:
        app_name = n.app_info.display_info.display_name
    except Exception as e:
        app_name = f"<读取失败:{e}>"
    texts = []
    try:
        for binding in n.notification.visual.bindings:
            for el in binding.get_text_elements():
                texts.append(el.text)
    except Exception as e:
        texts = [f"<读取失败:{e}>"]
    print(f"[{app_name}] id={n.id}")
    for t in texts:
        print("   ", t)
    print("-" * 60)
