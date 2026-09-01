"""系统托盘 + 右键菜单。"""
import datetime

from PySide6.QtGui import QAction, QActionGroup, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QSystemTrayIcon

from . import autostart
from . import config
from .custom_reminder_dialog import (
    ReminderEditDialog,
    ReminderManageDialog,
    describe,
)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window, parent=None):
        icon = self._build_idle_icon()
        super().__init__(icon, parent)
        self.window = window

        self.menu = QMenu()

        # 置顶
        self.act_top = QAction("置顶显示", self.menu)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(bool(config.get("always_on_top")))
        self.act_top.toggled.connect(self._on_toggle_top)

        self.act_hide = QAction("隐藏 / 显示", self.menu)
        self.act_hide.triggered.connect(self._on_toggle_visible)

        # 开机自启（HKCU Run 键）
        self.act_auto = QAction("开机自启", self.menu)
        self.act_auto.setCheckable(True)
        self.act_auto.setChecked(autostart.is_auto_start())
        self.act_auto.toggled.connect(self._on_auto_start)

        # 提示音总开关（关闭后提醒只弹气泡不响铃）
        self.act_sound = QAction("提示音", self.menu)
        self.act_sound.setCheckable(True)
        self.act_sound.setChecked(config.sound_enabled())
        self.act_sound.toggled.connect(self._on_sound)

        # 贴边隐藏（静止 N 秒自动滑到边缘只露一角，鼠标靠近再滑回）
        self.act_edge_hide = QAction("贴边隐藏", self.menu)
        self.act_edge_hide.setCheckable(True)
        self.act_edge_hide.setChecked(config.flag("edge_hide_enabled"))
        self.act_edge_hide.toggled.connect(self._on_edge_hide)

        # 离开感知（锁屏时自动静默，回来补报未读与错过的提醒）
        self.act_away = QAction("离开时静默", self.menu)
        self.act_away.setCheckable(True)
        self.act_away.setToolTip("锁屏/离开时自动静默，回来补报未读消息与错过的提醒事项")
        self.act_away.setChecked(config.flag("away_detect_enabled"))
        self.act_away.toggled.connect(self._on_away_detect)

        # 摸头互动（鼠标移到宠物身上会蹭你，摸够次数触发大反应）
        self.act_pet = QAction("摸头互动", self.menu)
        self.act_pet.setCheckable(True)
        self.act_pet.setToolTip("鼠标移到宠物身上会蹭你，多摸几下会开心得跳起来")
        self.act_pet.setChecked(config.flag("pet_enabled"))
        self.act_pet.toggled.connect(self._on_pet)

        # 喝水提醒子菜单
        self.drink_menu = QMenu("喝水提醒", self.menu)
        self.act_drink_enabled = QAction("开启提醒", self.drink_menu)
        self.act_drink_enabled.setCheckable(True)
        self.act_drink_enabled.setChecked(bool(config.get("drink_enabled")))
        self.act_drink_enabled.toggled.connect(self._on_drink_enabled)

        # 间隔（手动管理勾选，支持自定义）
        self.interval_menu = QMenu("提醒间隔", self.drink_menu)
        self._interval_acts = {}
        for mins in config.DRINK_INTERVALS:
            act = QAction(f"每 {mins} 分钟", self.interval_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, m=mins: self._on_interval(m))
            self._interval_acts[mins] = act
            self.interval_menu.addAction(act)
        self.interval_menu.addSeparator()
        act_custom = QAction("自定义...", self.interval_menu)
        act_custom.triggered.connect(self._on_custom_interval)
        self.interval_menu.addAction(act_custom)

        # 位置
        self.location_menu = QMenu("提醒位置", self.drink_menu)
        self._location_group = QActionGroup(self)
        self._location_group.setExclusive(True)
        self.act_loc_center = QAction("跑到屏幕中心", self.location_menu)
        self.act_loc_center.setCheckable(True)
        self.act_loc_center.setChecked(config.get("drink_location") == "center")
        self.act_loc_center.triggered.connect(lambda: self._on_location("center"))
        self.act_loc_current = QAction("原地提醒", self.location_menu)
        self.act_loc_current.setCheckable(True)
        self.act_loc_current.setChecked(config.get("drink_location") == "current")
        self.act_loc_current.triggered.connect(lambda: self._on_location("current"))
        self._location_group.addAction(self.act_loc_center)
        self._location_group.addAction(self.act_loc_current)
        self.location_menu.addAction(self.act_loc_center)
        self.location_menu.addAction(self.act_loc_current)

        self.drink_menu.addAction(self.act_drink_enabled)
        self.drink_menu.addSeparator()
        self.drink_menu.addMenu(self.interval_menu)
        self.drink_menu.addMenu(self.location_menu)

        # 宠物大小子菜单
        self.size_menu = QMenu("宠物大小", self.menu)
        self._size_acts = {}
        for label, val in config.SCALE_PRESETS:
            act = QAction(label, self.size_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, v=val: self._on_scale(v))
            self._size_acts[val] = act
            self.size_menu.addAction(act)
        self.size_menu.addSeparator()
        act_custom_size = QAction("自定义...", self.size_menu)
        act_custom_size.triggered.connect(self._on_custom_scale)
        self.size_menu.addAction(act_custom_size)

        # 更换皮肤子菜单（动态扫描可用皮肤）
        self.skin_menu = QMenu("更换皮肤", self.menu)
        self._skin_acts = {}
        self._skin_group = QActionGroup(self)
        self._skin_group.setExclusive(True)
        for skin_name in config.list_skins():
            # 显示名：default 翻译为「默认（企鹅）」，其他用原名
            display = "默认（企鹅）" if skin_name == "default" else skin_name
            act = QAction(display, self.skin_menu)
            act.setCheckable(True)
            act.setData(skin_name)
            act.triggered.connect(lambda checked, n=skin_name: self._on_skin(n))
            self._skin_acts[skin_name] = act
            self._skin_group.addAction(act)
            self.skin_menu.addAction(act)

        # 整点报时
        self.act_hourly = QAction("整点报时", self.menu)
        self.act_hourly.setCheckable(True)
        self.act_hourly.setChecked(bool(config.get("hourly_enabled")))
        self.act_hourly.toggled.connect(self._on_hourly)

        # 消息提醒子菜单（任务栏未读：灵犀/QQ/微信/企微）
        self.im_menu = QMenu("消息提醒", self.menu)
        self.act_im_master = QAction("开启消息提醒", self.im_menu)
        self.act_im_master.setCheckable(True)
        self.act_im_master.setChecked(bool(config.get("feishu_enabled")))
        self.act_im_master.toggled.connect(self._on_im_master)
        self._im_app_acts = {}
        for app_name in config.IM_APPS.keys():
            act = QAction(app_name, self.im_menu)
            act.setCheckable(True)
            act.setChecked(bool(config.get_im_enabled(app_name)))
            act.toggled.connect(lambda checked, a=app_name: self._on_im_app(a, checked))
            self._im_app_acts[app_name] = act
        self.im_menu.addAction(self.act_im_master)
        self.im_menu.addSeparator()
        for app_name in config.IM_APPS.keys():
            self.im_menu.addAction(self._im_app_acts[app_name])

        # 超时强提醒时长（持续未读超过 N 分钟 → 跑到屏幕中心）
        self.delay_menu = QMenu("超时强提醒", self.im_menu)
        self._delay_acts = {}
        for mins in config.UNREAD_CENTER_PRESETS:
            act = QAction(f"未读 {mins} 分钟后", self.delay_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, m=mins: self._on_center_delay(m))
            self._delay_acts[mins] = act
            self.delay_menu.addAction(act)
        self.delay_menu.addSeparator()
        act_custom_delay = QAction("自定义...", self.delay_menu)
        act_custom_delay.triggered.connect(self._on_custom_center_delay)
        self.delay_menu.addAction(act_custom_delay)
        self.im_menu.addSeparator()
        self.im_menu.addMenu(self.delay_menu)

        # 自定义提醒子菜单（用户自加事项：吃药 / 周会 / 一次性提醒）
        self.custom_menu = QMenu("自定义提醒", self.menu)
        act_add_custom = QAction("添加提醒...", self.custom_menu)
        act_add_custom.triggered.connect(self._on_add_custom)
        act_manage_custom = QAction("管理 / 删除...", self.custom_menu)
        act_manage_custom.triggered.connect(self._on_manage_custom)
        self.custom_menu.addAction(act_add_custom)
        self.custom_menu.addAction(act_manage_custom)
        self.custom_menu.addSeparator()
        self._custom_acts = {}

        # 久坐提醒子菜单
        self.sit_menu = QMenu("久坐提醒", self.menu)
        self.act_sit_enabled = QAction("开启提醒", self.sit_menu)
        self.act_sit_enabled.setCheckable(True)
        self.act_sit_enabled.setChecked(bool(config.get("sit_enabled")))
        self.act_sit_enabled.toggled.connect(self._on_sit_enabled)
        self.sit_interval_menu = QMenu("提醒间隔", self.sit_menu)
        self._sit_interval_acts = {}
        for mins in config.SIT_INTERVALS:
            act = QAction(f"每 {mins} 分钟", self.sit_interval_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, m=mins: self._on_sit_interval(m))
            self._sit_interval_acts[mins] = act
            self.sit_interval_menu.addAction(act)
        self.sit_menu.addAction(self.act_sit_enabled)
        self.sit_menu.addSeparator()
        self.sit_menu.addMenu(self.sit_interval_menu)

        # 下班提醒子菜单
        self.offwork_menu = QMenu("下班提醒", self.menu)
        self.act_offwork_enabled = QAction("开启提醒", self.offwork_menu)
        self.act_offwork_enabled.setCheckable(True)
        self.act_offwork_enabled.setChecked(bool(config.get("offwork_enabled")))
        self.act_offwork_enabled.toggled.connect(self._on_offwork_enabled)
        self.offwork_time_menu = QMenu("下班时间", self.offwork_menu)
        self._offwork_acts = {}
        for t in config.OFFWORK_PRESETS:
            act = QAction(t, self.offwork_time_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, tm=t: self._on_offwork_time(tm))
            self._offwork_acts[t] = act
            self.offwork_time_menu.addAction(act)
        self.offwork_time_menu.addSeparator()
        act_custom_off = QAction("自定义...", self.offwork_time_menu)
        act_custom_off.triggered.connect(self._on_custom_offwork_time)
        self.offwork_time_menu.addAction(act_custom_off)
        self.offwork_menu.addAction(self.act_offwork_enabled)
        self.offwork_menu.addSeparator()
        self.offwork_menu.addMenu(self.offwork_time_menu)

        # 专注模式子菜单（一段时间内静默所有提醒，菜单标题显示剩余时间）
        self.focus_menu = QMenu("专注模式", self.menu)
        for mins in config.FOCUS_PRESETS:
            act = QAction(f"专注 {mins} 分钟", self.focus_menu)
            act.triggered.connect(lambda checked, m=mins: self._on_focus(m))
            self.focus_menu.addAction(act)
        self.focus_menu.addSeparator()
        act_focus_off = QAction("结束专注", self.focus_menu)
        act_focus_off.triggered.connect(lambda: self._on_focus(0))
        self.focus_menu.addAction(act_focus_off)

        # 番茄钟子菜单（1.5.0）：循环 25+5（每 4 个 work 后长休 15）。
        # 与专注模式并存：番茄钟是"循环阶段静默"，专注模式是"任意时长静默"，
        # 都通过 is_silent_now() 通道抑制提醒，但用独立的状态机管理阶段。
        self.pomodoro_menu = QMenu("番茄钟", self.menu)
        self.act_pomodoro_start = QAction("启动经典 25+5", self.pomodoro_menu)
        self.act_pomodoro_start.triggered.connect(self._on_pomodoro_start)
        self.act_pomodoro_stop = QAction("结束番茄钟", self.pomodoro_menu)
        self.act_pomodoro_stop.triggered.connect(self._on_pomodoro_stop)
        self.pomodoro_menu.addAction(self.act_pomodoro_start)
        self.pomodoro_menu.addAction(self.act_pomodoro_stop)
        self.pomodoro_menu.addSeparator()
        self.act_pomodoro_today = QAction("今日完成：0", self.pomodoro_menu)
        self.act_pomodoro_today.setEnabled(False)
        self.pomodoro_menu.addAction(self.act_pomodoro_today)

        # 免打扰时段子菜单（每天固定时段静默，支持跨零点）
        self.quiet_menu = QMenu("免打扰时段", self.menu)
        self.act_quiet_enabled = QAction("开启免打扰", self.quiet_menu)
        self.act_quiet_enabled.setCheckable(True)
        self.act_quiet_enabled.setChecked(config.quiet_enabled())
        self.act_quiet_enabled.toggled.connect(self._on_quiet_enabled)
        self.quiet_menu.addAction(self.act_quiet_enabled)
        self.quiet_menu.addSeparator()
        self._quiet_acts = {}
        for label, s, e in config.QUIET_PRESETS:
            act = QAction(label, self.quiet_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda checked, a=s, b=e: self._on_quiet_preset(a, b))
            self._quiet_acts[(s, e)] = act
            self.quiet_menu.addAction(act)
        self.quiet_menu.addSeparator()
        act_qs = QAction("自定义开始时间...", self.quiet_menu)
        act_qs.triggered.connect(self._on_quiet_start)
        act_qe = QAction("自定义结束时间...", self.quiet_menu)
        act_qe.triggered.connect(self._on_quiet_end)
        self.quiet_menu.addAction(act_qs)
        self.quiet_menu.addAction(act_qe)

        self.act_quit = QAction("退出", self.menu)
        self.act_quit.triggered.connect(self._on_quit)

        self.menu.addAction(self.act_top)
        self.menu.addAction(self.act_hide)
        self.menu.addAction(self.act_auto)
        self.menu.addAction(self.act_sound)
        self.menu.addAction(self.act_edge_hide)
        self.menu.addAction(self.act_pet)
        self.menu.addSeparator()
        self.menu.addMenu(self.drink_menu)
        self.menu.addMenu(self.sit_menu)
        self.menu.addMenu(self.offwork_menu)
        self.menu.addAction(self.act_hourly)
        self.menu.addMenu(self.im_menu)
        self.menu.addMenu(self.custom_menu)
        self.menu.addSeparator()
        self.menu.addMenu(self.focus_menu)
        self.menu.addMenu(self.pomodoro_menu)
        self.menu.addMenu(self.quiet_menu)
        self.menu.addSeparator()
        self.menu.addMenu(self.size_menu)
        self.menu.addMenu(self.skin_menu)
        self.menu.addSeparator()
        self.menu.addAction(self.act_quit)
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)

        self._sync_interval_checks()
        self._sync_size_checks()
        self._sync_sit_interval_checks()
        self._sync_offwork_checks()
        self._sync_delay_checks()
        self._sync_skin_checks()
        self._sync_quiet_checks()
        self._sync_focus_menu()
        self._sync_pomodoro_menu()
        self._sync_custom_menu()

    # ---------- 图标 ----------
    def _build_idle_icon(self) -> QIcon:
        """按当前皮肤构造托盘图标。"""
        skin = config.current_skin()
        if skin == "default":
            path = config.resource_path("skins", "idle.png")
        else:
            path = config.resource_path("skins", skin, "idle.png")
        return QIcon(QPixmap(path))

    def refresh_icon(self) -> None:
        """皮肤切换后更新托盘图标。"""
        self.setIcon(self._build_idle_icon())

    # ---------- 回调 ----------
    def _on_toggle_top(self, checked: bool) -> None:
        config.set_value("always_on_top", checked)
        self.window.apply_topmost(checked)

    def _on_toggle_visible(self) -> None:
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()

    def _on_auto_start(self, checked: bool) -> None:
        ok = autostart.set_auto_start(checked)
        if not ok:
            # 设置失败（如开发环境/注册表被拒）：回滚勾选到实际状态
            self.act_auto.blockSignals(True)
            self.act_auto.setChecked(autostart.is_auto_start())
            self.act_auto.blockSignals(False)

    def _on_drink_enabled(self, checked: bool) -> None:
        config.set_value("drink_enabled", checked)
        self.window.refresh_reminder("drink")

    def _sync_interval_checks(self, mins=None) -> None:
        if mins is None:
            mins = int(config.get("drink_interval"))
        for m, act in self._interval_acts.items():
            act.setChecked(m == mins)

    def _on_interval(self, mins: int) -> None:
        config.set_value("drink_interval", mins)
        self._sync_interval_checks(mins)
        self.window.refresh_reminder("drink")

    def _on_custom_interval(self) -> None:
        current = int(config.get("drink_interval"))
        val, ok = QInputDialog.getInt(
            None, "自定义喝水间隔", "每隔多少分钟提醒喝水？", current, 1, 1440, 1
        )
        if ok:
            config.set_value("drink_interval", val)
            self._sync_interval_checks(val)
            self.window.refresh_reminder("drink")

    def _sync_size_checks(self, scale=None) -> None:
        if scale is None:
            scale = float(config.get("scale"))
        for val, act in self._size_acts.items():
            act.setChecked(abs(val - scale) < 0.01)

    def _on_scale(self, val: float) -> None:
        self.window.set_scale(val)
        self._sync_size_checks(val)

    def _on_custom_scale(self) -> None:
        current = float(config.get("scale"))
        val, ok = QInputDialog.getDouble(
            None, "自定义宠物大小", "缩放系数（0.3~2.0，默认 0.65）", current, 0.3, 2.0, 2
        )
        if ok:
            self.window.set_scale(val)
            self._sync_size_checks(val)

    def refresh_menu_checks(self) -> None:
        """弹出菜单前刷新勾选状态（供宠物右键复用菜单时调用）。"""
        self.act_top.setChecked(bool(config.get("always_on_top")))
        self.act_auto.setChecked(autostart.is_auto_start())
        self.act_drink_enabled.setChecked(bool(config.get("drink_enabled")))
        self.act_hourly.setChecked(bool(config.get("hourly_enabled")))
        self.act_sit_enabled.setChecked(bool(config.get("sit_enabled")))
        self.act_offwork_enabled.setChecked(bool(config.get("offwork_enabled")))
        self.act_im_master.setChecked(bool(config.get("feishu_enabled")))
        for app_name, act in self._im_app_acts.items():
            act.setChecked(bool(config.get_im_enabled(app_name)))
        self.act_sound.setChecked(config.sound_enabled())
        self.act_edge_hide.setChecked(config.flag("edge_hide_enabled"))
        self.act_away.setChecked(config.flag("away_detect_enabled"))
        self.act_pet.setChecked(config.flag("pet_enabled"))
        self._sync_interval_checks()
        self._sync_size_checks()
        self._sync_sit_interval_checks()
        self._sync_offwork_checks()
        self._sync_delay_checks()
        self._sync_skin_checks()
        self._sync_quiet_checks()
        self._sync_focus_menu()
        self._sync_pomodoro_menu()
        self._sync_custom_menu()

    def _on_location(self, loc: str) -> None:
        config.set_value("drink_location", loc)
        self.window.refresh_reminder("drink")

    def _on_hourly(self, checked: bool) -> None:
        config.set_value("hourly_enabled", checked)
        self.window.refresh_reminder("hourly")

    def _on_im_master(self, checked: bool) -> None:
        config.set_value("feishu_enabled", checked)
        self.window.notifier.set_enabled(checked)
        self.window.im_watcher.set_enabled(checked)

    def _on_im_app(self, app: str, checked: bool) -> None:
        self.window.im_watcher.set_app_enabled(app, checked)

    def _sync_delay_checks(self, mins=None) -> None:
        if mins is None:
            mins = max(1, int(config.get("unread_center_delay")) // 60)
        for m, act in self._delay_acts.items():
            act.setChecked(m == mins)

    def _on_center_delay(self, mins: int) -> None:
        config.set_value("unread_center_delay", mins * 60)
        self._sync_delay_checks(mins)

    def _on_custom_center_delay(self) -> None:
        current = max(1, int(config.get("unread_center_delay")) // 60)
        val, ok = QInputDialog.getInt(
            None, "自定义超时强提醒", "持续未读多少分钟后强提醒？", current, 1, 60, 1
        )
        if ok:
            config.set_value("unread_center_delay", val * 60)
            self._sync_delay_checks(val)

    def _sync_sit_interval_checks(self, mins=None) -> None:
        if mins is None:
            mins = int(config.get("sit_interval"))
        for m, act in self._sit_interval_acts.items():
            act.setChecked(m == mins)

    def _on_sit_enabled(self, checked: bool) -> None:
        config.set_value("sit_enabled", checked)
        self.window.refresh_reminder("sit")

    def _on_sit_interval(self, mins: int) -> None:
        config.set_value("sit_interval", mins)
        self._sync_sit_interval_checks(mins)
        self.window.refresh_reminder("sit")

    def _sync_offwork_checks(self, t=None) -> None:
        if t is None:
            t = config.get("offwork_time")
        for tm, act in self._offwork_acts.items():
            act.setChecked(tm == t)

    def _on_offwork_enabled(self, checked: bool) -> None:
        config.set_value("offwork_enabled", checked)
        self.window.refresh_reminder("offwork")

    def _on_offwork_time(self, t: str) -> None:
        config.set_value("offwork_time", t)
        self._sync_offwork_checks(t)
        self.window.refresh_reminder("offwork")

    def _on_custom_offwork_time(self) -> None:
        current = config.get("offwork_time")
        text, ok = QInputDialog.getText(
            None, "自定义下班时间", "下班时间（HH:MM，如 18:30）", text=current
        )
        if ok and text:
            config.set_value("offwork_time", text)
            self._sync_offwork_checks(text)
            self.window.refresh_reminder("offwork")

    # ---------- 换肤 ----------
    def _sync_skin_checks(self, skin_name: str = None) -> None:
        if skin_name is None:
            skin_name = config.current_skin()
        for name, act in self._skin_acts.items():
            act.setChecked(name == skin_name)

    def _on_skin(self, skin_name: str) -> None:
        if skin_name == config.current_skin():
            return
        self.window.set_skin(skin_name)
        self._sync_skin_checks(skin_name)

    # ---------- 提示音 / 免打扰 / 专注模式 ----------
    def _on_sound(self, checked: bool) -> None:
        config.set_value("sound_enabled", checked)

    def _on_edge_hide(self, checked: bool) -> None:
        config.set_value("edge_hide_enabled", checked)
        if checked:
            self.window._setup_edge_hide_timer()
        else:
            self.window._disable_edge_hide()

    def _on_away_detect(self, checked: bool) -> None:
        """离开感知开关：注册/注销 Windows 会话通知。"""
        self.window.set_away_detect(checked)

    def _on_pet(self, checked: bool) -> None:
        """摸头互动开关。"""
        self.window.set_pet_enabled(checked)

    def _on_focus(self, mins: int) -> None:
        """开启专注模式若干分钟；0 表示立即结束专注。"""
        config.set_focus_minutes(mins)
        self._sync_focus_menu()

    # ---------- 番茄钟 ----------
    def _on_pomodoro_start(self) -> None:
        """启动番茄钟（从 work round 1 开始）。已运行时点这个就是 noop。"""
        if config.pomodoro_active():
            return
        self.window.start_pomodoro()

    def _on_pomodoro_stop(self) -> None:
        if not config.pomodoro_active():
            return
        self.window.stop_pomodoro()

    def _sync_pomodoro_menu(self) -> None:
        """刷新番茄钟菜单状态：今日完成数 / 启动/结束按钮可用性。"""
        try:
            count = config.pomodoro_today_count()
            self.act_pomodoro_today.setText(f"今日完成：{count}")
            running = config.pomodoro_active()
            self.act_pomodoro_start.setEnabled(not running)
            self.act_pomodoro_stop.setEnabled(running)
        except Exception:
            pass

    def _on_quiet_enabled(self, checked: bool) -> None:
        config.set_value("quiet_enabled", checked)
        self._sync_quiet_checks()

    def _on_quiet_preset(self, start: str, end: str) -> None:
        config.set_value("quiet_start", start)
        config.set_value("quiet_end", end)
        config.set_value("quiet_enabled", True)
        self._sync_quiet_checks()

    def _on_quiet_start(self) -> None:
        text, ok = QInputDialog.getText(
            None, "免打扰开始时间", "开始时间（HH:MM，如 22:30）", text=config.quiet_start()
        )
        if ok and self._valid_hm(text):
            config.set_value("quiet_start", str(text).strip())
            self._sync_quiet_checks()

    def _on_quiet_end(self) -> None:
        text, ok = QInputDialog.getText(
            None, "免打扰结束时间", "结束时间（HH:MM，如 08:00）", text=config.quiet_end()
        )
        if ok and self._valid_hm(text):
            config.set_value("quiet_end", str(text).strip())
            self._sync_quiet_checks()

    @staticmethod
    def _valid_hm(text: str) -> bool:
        try:
            datetime.datetime.strptime(str(text).strip(), "%H:%M")
            return True
        except Exception:
            return False

    def _sync_quiet_checks(self) -> None:
        self.act_quiet_enabled.setChecked(config.quiet_enabled())
        start, end = config.quiet_start(), config.quiet_end()
        for (s, e), act in self._quiet_acts.items():
            act.setChecked(s == start and e == end)

    def _sync_focus_menu(self) -> None:
        """菜单标题显示专注 / 番茄钟剩余时间，用户不点进去也能看到状态。

        优先级：番茄钟 > 专注模式 > 番茄菜单（独立项）。番茄钟期间显示
        「🍅 工作中 剩 X」 / 「☕ 休息中 剩 X」，否则按专注模式状态显示。
        """
        if config.pomodoro_active():
            phase = config.pomodoro_phase()
            left = config.pomodoro_phase_remaining()
            mins = max(0, left // 60)
            if phase == "work":
                self.focus_menu.setTitle(f"🍅 工作中 · 剩 {mins} 分")
            elif phase == "short_break":
                self.focus_menu.setTitle(f"☕ 休息中 · 剩 {mins} 分")
            elif phase == "long_break":
                self.focus_menu.setTitle(f"☕ 长休中 · 剩 {mins} 分")
            return
        left = config.focus_remaining()
        if left <= 0:
            self.focus_menu.setTitle("专注模式")
            return
        mins = max(1, left // 60)
        if mins >= 60:
            self.focus_menu.setTitle(f"专注中 · 剩 {mins // 60} 小时 {mins % 60} 分")
        else:
            self.focus_menu.setTitle(f"专注中 · 剩 {mins} 分钟")

    # ---------- 自定义提醒 ----------
    def _on_add_custom(self) -> None:
        dlg = ReminderEditDialog()
        if not dlg.exec():
            return
        item = dlg.result_item()
        if not item or not item.get("label"):
            return
        config.add_custom_reminder(item)
        self._sync_custom_menu()
        self.window.refresh_reminder("custom")

    def _on_manage_custom(self) -> None:
        ReminderManageDialog().exec()
        self._sync_custom_menu()
        self.window.refresh_reminder("custom")

    def _on_toggle_custom(self, item: dict, checked: bool) -> None:
        config.set_custom_reminder_enabled(item.get("id"), checked)
        self.window.refresh_reminder("custom")

    def _sync_custom_menu(self) -> None:
        """重建自定义提醒列表项（前两个固定项保持不变）。"""
        for act in self._custom_acts.values():
            self.custom_menu.removeAction(act)
        self._custom_acts.clear()
        for item in config.get_custom_reminders():
            act = QAction(describe(item), self.custom_menu)
            act.setCheckable(True)
            act.setChecked(bool(item.get("enabled", True)))
            act.toggled.connect(lambda checked, i=item: self._on_toggle_custom(i, checked))
            self._custom_acts[item.get("id")] = act
            self.custom_menu.addAction(act)

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.window.show()

    def _on_quit(self) -> None:
        self.window.close()
        QApplication.instance().quit()
