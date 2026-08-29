"""端到端验证飞书监听：启动宠物 -> 弹真实 toast -> 验证捕获并触发提醒。

用 Windows PowerShell 自带 AUMID 弹真实 toast（app name 显示为
"Windows PowerShell"），临时把识别关键词换成它来模拟飞书来源，
验证 后台轮询 -> 识别 -> Signal -> 气泡 完整链路。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import pet.config as config
from pet.window import PetWindow

FIRED = []


def on_msg(sender, content):
    FIRED.append((sender, content))
    print(f"[捕获] sender={sender!r} content={content!r}")


def send_toast():
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null; "
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType = WindowsRuntime] | Out-Null; "
        "$appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'; "
        "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
        "$texts = $t.GetElementsByTagName('text'); "
        "$null = $texts.Item(0).AppendChild($t.CreateTextNode('ZhangSan')); "
        "$null = $texts.Item(1).AppendChild($t.CreateTextNode('Hello meeting at 3pm')); "
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($t); "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast); "
        "Write-Output 'toast-shown'"
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        check=False,
    )
    print("[弹 toast] rc =", r.returncode, "| out =", (r.stdout or "").strip())


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 临时把识别关键词换成现有 AUMID 应用名，模拟飞书来源
    config.FEISHU_APP_NAMES = ["Windows PowerShell"]

    w = PetWindow()
    w.show()
    w.notifier.message_received.connect(on_msg)

    QTimer.singleShot(2500, send_toast)  # 等后台 snapshot 完成后再弹

    def finish():
        print(f"== 捕获 {len(FIRED)} 条: {FIRED} ==")
        app.quit()

    QTimer.singleShot(9000, finish)
    app.exec()
    sys.exit(0 if FIRED else 1)


if __name__ == "__main__":
    main()
