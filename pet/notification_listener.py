"""飞书新消息监听：后台线程轮询 Windows 通知中心，识别飞书来源，解析消息摘要。

原理：
- 飞书桌面客户端收到新消息会弹 Windows 系统通知；
- 用 winrt 的 UserNotificationListener 读取系统 toast 通知（不调用飞书 API，
  从而绕过飞书「机器人/应用身份读不到个人未读消息」的隐私限制）；
- Qt 主线程是 STA（单线程公寓），winrt 的阻塞调用 .get() 在 STA 里会抛
  RuntimeError，因此把轮询放到独立后台线程（MTA），通过 Signal 跨线程
  回传到主线程（Qt 自动队列投递）。

注意：
- winrt 依赖仅 Windows 可用，加载失败时优雅降级（不启动监听，程序照常运行）；
- 打包时需把 winrt 相关包列为 hiddenimports（PyInstaller 无法自动发现其动态加载）。
"""
import logging
import threading

from PySide6.QtCore import QObject, Signal

from . import config

logger = logging.getLogger("feishu")

POLL_SECONDS = 3.0   # 轮询间隔（秒）
MAX_TEXT_LEN = 40    # 摘要中消息内容最大字符数
MAX_PER_POLL = 2     # 单次轮询最多处理的飞书消息条数（防连发刷屏）


class NotificationWatcher(QObject):
    message_received = Signal(str, str)  # (来源/发送者, 消息内容)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._thread = None
        self._available = False
        self._init()

    # ---------- 启动 / 停止 ----------
    def _init(self) -> None:
        """启动后台监听线程（幂等）。"""
        if not bool(config.get("feishu_enabled")):
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_enabled(self, enabled: bool) -> None:
        config.set_value("feishu_enabled", enabled)
        if enabled:
            self._init()
        else:
            self._stop.set()
            self._available = False

    # ---------- 后台线程 ----------
    def _run(self) -> None:
        try:
            from winrt.windows.ui.notifications import NotificationKinds
            from winrt.windows.ui.notifications.management import (
                UserNotificationListener,
            )

            listener = UserNotificationListener.current
            if listener.get_access_status() != 1:  # 1 == ALLOWED
                logger.warning("飞书监听未获通知访问授权，已跳过")
                self._available = False
                return
            # 记录已有通知 id，避免把历史通知误当新消息
            known = self._snapshot_ids(listener)
            self._available = True
            logger.info("飞书新消息监听已启动（轮询 %.0fs）", POLL_SECONDS)
        except Exception as e:
            logger.warning("飞书监听启动失败: %s", e)
            self._available = False
            return

        while not self._stop.is_set():
            try:
                notifs = listener.get_notifications_async(
                    NotificationKinds.TOAST
                ).get()
                fresh = [n for n in notifs if n.id not in known]
                known = {n.id for n in notifs}

                count = 0
                for n in fresh:
                    app, texts = self._parse(n)
                    # 诊断日志：记录每次捕获到的新通知来源，便于定位「灵犀」等
                    # 定制版应用的确切显示名（避免猜错匹配关键词）。
                    logger.info("捕获新通知来源: %r, 文本数=%d", app, len(texts))
                    if self._is_feishu(app) and texts and count < MAX_PER_POLL:
                        sender, content = self._summarize(texts)
                        # 从后台线程 emit，Qt 自动队列投递到主线程
                        self.message_received.emit(sender, content)
                        count += 1
            except Exception:
                pass
            self._stop.wait(POLL_SECONDS)

    def _snapshot_ids(self, listener) -> set:
        ids = set()
        try:
            from winrt.windows.ui.notifications import NotificationKinds

            notifs = listener.get_notifications_async(NotificationKinds.TOAST).get()
            for n in notifs:
                ids.add(n.id)
        except Exception:
            pass
        return ids

    # ---------- 解析 ----------
    def _parse(self, n) -> tuple:
        app = ""
        try:
            app = n.app_info.display_info.display_name or ""
        except Exception:
            app = ""
        texts = []
        try:
            for b in n.notification.visual.bindings:
                for el in b.get_text_elements():
                    texts.append(el.text)
        except Exception:
            pass
        return app, texts

    def _is_feishu(self, app: str) -> bool:
        a = (app or "").lower()
        return any(kw.lower() in a for kw in config.FEISHU_APP_NAMES)

    def _summarize(self, texts: list) -> tuple:
        """把通知文本列表拆成 (来源, 内容)。"""
        if len(texts) >= 2:
            sender = texts[0]
            content = " ".join(texts[1:]).strip()
        else:
            sender = "飞书"
            content = (texts[0] if texts else "").strip()
        if len(content) > MAX_TEXT_LEN:
            content = content[:MAX_TEXT_LEN] + "…"
        if not content:
            content = "新消息"
        return sender, content
