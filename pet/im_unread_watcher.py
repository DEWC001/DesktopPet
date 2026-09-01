"""通用 IM 未读消息提醒：后台线程轮询任务栏按钮状态，支持多应用。

原理（继承自原 lingxi_watcher，推广到 QQ / 微信 / 企业微信）：
- 大多数 IM 桌面端收到新消息且窗口在后台时，会调用 flashFrame 让任务栏图标
  「请求注意」，任务栏按钮的 UIA HelpText（LegacyIAccessible.Help）变为
  「已请求注意」，平时为空或「xxx 已固定」；
- 部分应用（如 QQ）还会把未读数写进任务栏按钮标题角标，形如「QQ (3)」；
- 后台线程轮询这两个信号，检测「未读出现 / 消失」的翻转，Signal 回传主线程。

注意：
- 依赖 uiautomation（纯 Python + comtypes），加载失败优雅降级；
- UIA 是同步 COM 调用，不能阻塞 Qt 主线程，故放到后台线程，Signal 回传；
- 该信号只能得到「有未读」，拿不到未读数和消息内容（IM 不对外暴露）；
- 任务栏按钮名匹配规则：按钮名 == 关键词，或以「关键词 -」「关键词 (」开头
  （如「灵犀 - 1 个运行窗口」「QQ (3)」），避免把「QQ音乐」误判成 QQ。
"""
import logging
import re
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import config

logger = logging.getLogger("im_unread")

POLL_SECONDS = 2.0          # 有受监测 IM 运行时的轮询间隔（秒）
POLL_SECONDS_IDLE = 15.0    # 无受监测 IM 运行时的降频间隔（秒）
HOLD_SECONDS = 10.0         # 未读信号消失后的保持时长（秒）：避免短暂闪烁被误判成已读
TASKBAR_CACHE_SECONDS = 300.0  # 任务栏控件缓存时长（秒），超时或取不到按钮时强制重找

# Name 角标正则：如「QQ (3)」表示 3 条未读
_BADGE_RE = re.compile(r"\(\d+\)")


class ImUnreadWatcher(QObject):
    unread_changed = Signal(str, bool)  # (应用显示名, 是否有未读)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._unread = {}        # app_name -> bool（后台线程写，主线程 is_unread 读）
        self._last_true_time = {}  # app_name -> monotonic 时间戳（未读保持去抖，仅后台线程）
        self._enabled_apps = {}  # app_name -> 关键词列表（主线程维护，引用替换）
        self._dump_counter = 0
        self._available = False
        # 自适应降频：没有任何受监测 IM 在跑时降到 POLL_SECONDS_IDLE，
        # 一旦检测到目标应用立即恢复 POLL_SECONDS（仅后台线程读写 _idle）
        self._idle = False
        self._taskbar = None       # 任务栏控件缓存（UIA 遍历开销大头）
        self._taskbar_time = 0.0
        self._load_apps()
        self._init()

    # ---------- 启用应用列表（主线程维护） ----------
    def _load_apps(self) -> None:
        """从配置重载启用应用列表（主线程调用，整体引用替换）。"""
        self._enabled_apps = {
            name: kws for name, kws in config.IM_APPS.items()
            if config.get_im_enabled(name)
        }

    def set_app_enabled(self, name: str, enabled: bool) -> None:
        """主线程调用：切换某应用是否监测。"""
        config.set_im_enabled(name, enabled)
        self._load_apps()

    def refresh_apps(self) -> None:
        """重读配置（托盘切换开关后调用）。"""
        self._load_apps()

    def monitored_apps(self) -> list:
        """当前受监测的应用名列表（主线程调用）。"""
        return list(self._enabled_apps.keys())

    def unread_apps(self) -> list:
        """当前仍未读的应用名列表（主线程调用）。"""
        return [app for app in self._enabled_apps if self.is_unread(app)]

    # ---------- 启动 / 停止 ----------
    def _init(self) -> None:
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
            self._last_true_time.clear()  # 重开时清空去抖残留，避免旧状态干扰
            self._init()
        else:
            self._stop.set()
            self._available = False

    def is_unread(self, app: str) -> bool:
        """主线程查询某应用当前是否仍未读（线程安全）。"""
        with self._lock:
            return self._unread.get(app, False)

    # ---------- 后台线程 ----------
    def _run(self) -> None:
        try:
            import uiautomation as auto
        except Exception as e:
            logger.warning("IM 未读监听启动失败: uiautomation 不可用 (%s)", e)
            return

        # 显式初始化当前线程 COM：UIA 是 COM 接口，uiautomation 要求
        # 在非主线程使用前调用 InitializeUIAutomationInCurrentThread（即 CoInitializeEx）。
        # 若缺失，GetRootControl/GetLegacyIAccessiblePattern 会静默失败，未读永远读不到。
        try:
            auto.InitializeUIAutomationInCurrentThread()
        except Exception as e:
            logger.warning("IM 未读监听 COM 初始化失败: %s", e)
            return

        # 首次快照当前状态，避免把「启动前已有未读」误当新消息
        try:
            self._poll(auto, silent=True)
            self._available = True
            logger.info(
                "IM 未读监听已启动（轮询 %.0fs，应用: %s）",
                POLL_SECONDS,
                list(self._enabled_apps.keys()),
            )
        except Exception as e:
            logger.warning("IM 未读监听启动失败: %s", e)
            return

        while not self._stop.is_set():
            try:
                self._poll(auto, silent=False)
            except Exception as e:
                logger.warning("IM 未读监听轮询异常: %s", e)
            self._stop.wait(self._current_interval())

    def _current_interval(self) -> float:
        """当前轮询间隔：没有任何受监测 IM 运行时降频。"""
        return POLL_SECONDS_IDLE if self._idle else POLL_SECONDS

    def _set_idle(self, idle: bool) -> None:
        """切换降频状态，只在变化时打日志，避免刷屏。"""
        if idle == self._idle:
            return
        self._idle = idle
        if idle:
            logger.info(
                "IM 未读监听降频：未发现受监测的 IM 运行（%.0fs → %.0fs）",
                POLL_SECONDS, POLL_SECONDS_IDLE,
            )
        else:
            logger.info("IM 未读监听恢复常速（%.0fs）", POLL_SECONDS)

    def _get_taskbar(self, root, force: bool = False):
        """取任务栏控件，带缓存。缓存超时或调用方强制时重新查找。"""
        now = time.monotonic()
        if (
            not force
            and self._taskbar is not None
            and (now - self._taskbar_time) < TASKBAR_CACHE_SECONDS
        ):
            return self._taskbar
        self._taskbar = self._find_taskbar(root)
        self._taskbar_time = now
        return self._taskbar

    def _poll(self, auto, silent: bool) -> None:
        root = auto.GetRootControl()
        buttons = []
        taskbar = self._get_taskbar(root)
        if taskbar is not None:
            try:
                self._collect_buttons(taskbar, buttons)
            except Exception as e:
                logger.debug("任务栏按钮遍历失败，丢弃缓存: %s", e)
                self._taskbar = None
                buttons = []
        if taskbar is not None and not buttons:
            # 缓存的任务栏可能已失效（如资源管理器重启后旧控件静默返回空），
            # 放弃缓存重找一次再试，避免长时间漏检未读
            self._taskbar = None
            taskbar = self._get_taskbar(root, force=True)
            if taskbar is not None:
                try:
                    self._collect_buttons(taskbar, buttons)
                except Exception as e:
                    logger.debug("任务栏按钮遍历重试失败: %s", e)
                    self._taskbar = None
        if taskbar is None:
            self._set_idle(True)
            return

        found_any = False    # 本轮是否发现任何受监测 IM 在运行
        titles = None        # 顶层窗口标题，懒加载：一轮只枚举一次

        for app_name, keywords in list(self._enabled_apps.items()):
            btn = self._match_button(buttons, keywords)
            if btn is not None:
                found_any = True
            raw = self._is_unread(btn) if btn is not None else False
            # 兜底：任务栏按钮读不到未读时，枚举顶层窗口标题是否带未读角标
            #（多窗口合并时任务栏按钮名可能丢角标，如「QQ - 2 个运行窗口」）
            if not raw:
                if titles is None:
                    titles = self._collect_window_titles(root)
                if self._window_title_unread_from(titles, keywords):
                    raw = True
                    found_any = True

            # 未读保持（去抖）：检测到未读后，即使信号短暂消失也保持 HOLD 秒，
            # 防止「闪几下就停」的应用被误判成已读、导致超时强提醒被提前取消
            effective = self._debounce(app_name, raw, time.monotonic())

            with self._lock:
                prev = self._unread.get(app_name, False)
            if effective != prev:
                with self._lock:
                    self._unread[app_name] = effective
                logger.info("IM 未读变化: %s -> %s", app_name, effective)
                if not silent:
                    self.unread_changed.emit(app_name, effective)

        # 一个受监测 IM 都没跑 → 降频；只要发现任何一个就立刻恢复常速
        self._set_idle(not found_any)

        # 周期性 dump 任务栏按钮名，便于定位「QQ/微信/企微」的确切按钮名
        self._dump_counter += 1
        if self._dump_counter >= 60:
            self._dump_counter = 0
            self._log_buttons(buttons)

    def _log_buttons(self, buttons) -> None:
        names = []
        for b in buttons:
            try:
                names.append(b.Name)
            except Exception:
                pass
        logger.info("任务栏按钮名快照: %r", names)

    # ---------- 去抖保持 ----------
    def _debounce(self, app_name: str, raw: bool, now: float) -> bool:
        """未读保持（去抖）：raw=True 记录时刻并返回 True；raw=False 时，
        若距上次检测到未读不足 HOLD_SECONDS 则仍保持 True，避免「闪几下就停」
        的应用被误判成已读、导致超时强提醒被提前取消。仅后台线程调用。
        """
        if raw:
            self._last_true_time[app_name] = now
            return True
        last = self._last_true_time.get(app_name)
        if last is not None and (now - last) < HOLD_SECONDS:
            return True
        return False

    # ---------- 检测 ----------
    @staticmethod
    def _find_taskbar(ctrl, depth=0):
        if depth > 8:
            return None
        try:
            if ctrl.ClassName == "Shell_TrayWnd":
                return ctrl
        except Exception:
            pass
        try:
            children = ctrl.GetChildren()
        except Exception:
            return None
        # Shell_TrayWnd 通常是桌面的直接子节点：先只扫一层，命中就直接返回，
        # 免掉「为了找任务栏而把每个顶层窗口的整棵子树都翻一遍」这个开销大头
        if depth == 0:
            for c in children:
                try:
                    if c.ClassName == "Shell_TrayWnd":
                        return c
                except Exception:
                    pass
        for c in children:
            r = ImUnreadWatcher._find_taskbar(c, depth + 1)
            if r is not None:
                return r
        return None

    @staticmethod
    def _collect_buttons(ctrl, out, depth=0):
        if depth > 10:
            return
        try:
            if "TaskListButton" in ctrl.ClassName:
                out.append(ctrl)
        except Exception:
            pass
        try:
            for c in ctrl.GetChildren():
                ImUnreadWatcher._collect_buttons(c, out, depth + 1)
        except Exception:
            pass

    @staticmethod
    def _match_button(buttons, keywords):
        for b in buttons:
            try:
                name = b.Name or ""
            except Exception:
                name = ""
            for kw in keywords:
                if ImUnreadWatcher._name_matches(name, kw):
                    return b
        return None

    @staticmethod
    def _name_matches(name: str, kw: str) -> bool:
        if name == kw:
            return True
        if name.startswith(kw + " -"):   # 「灵犀 - 1 个运行窗口」
            return True
        if name.startswith(kw + " ("):   # 「QQ (3)」带未读角标
            return True
        return False

    @staticmethod
    def _collect_window_titles(root):
        """一次性收集所有顶层窗口标题。

        每轮轮询只调一次，供所有受监测应用复用；改造前每个应用各枚举一遍，
        4 个应用 = 每秒 2 轮 × 4 次全量顶层窗口遍历。
        """
        titles = []
        try:
            windows = root.GetChildren()
        except Exception:
            return titles
        for w in windows:
            try:
                title = w.Name or ""
            except Exception:
                continue
            if title:
                titles.append(title)
        return titles

    @staticmethod
    def _window_title_unread_from(titles, keywords) -> bool:
        """在已收集的标题列表里找「匹配应用 且 带未读角标」的窗口。"""
        for title in titles:
            if not _BADGE_RE.search(title):
                continue
            for kw in keywords:
                if ImUnreadWatcher._name_matches(title, kw):
                    return True
        return False

    @staticmethod
    def _window_title_unread(root, keywords) -> bool:
        """枚举顶层窗口，检测是否有匹配应用、且标题带未读角标的窗口（如「QQ (3)」）。

        任务栏按钮名在多窗口合并时可能丢失角标（如「QQ - 2 个运行窗口」），
        而主窗口标题仍带角标，这里作为兜底信号。
        """
        return ImUnreadWatcher._window_title_unread_from(
            ImUnreadWatcher._collect_window_titles(root), keywords
        )

    @staticmethod
    def _is_unread(btn) -> bool:
        # 信号 1：任务栏「请求注意」（flashFrame）
        try:
            la = btn.GetLegacyIAccessiblePattern()
            if la is not None:
                help_text = la.Help or ""
                if "请求注意" in help_text or "需要关注" in help_text:
                    return True
        except Exception:
            pass
        # 信号 2：按钮标题带未读角标，如「QQ (3)」
        try:
            name = btn.Name or ""
            if _BADGE_RE.search(name):
                return True
        except Exception:
            pass
        return False
