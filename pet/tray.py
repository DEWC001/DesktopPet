"""系统托盘 + 右键菜单。"""
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QSystemTrayIcon

from . import autostart
from . import config


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

        self.act_quit = QAction("退出", self.menu)
        self.act_quit.triggered.connect(self._on_quit)

        self.menu.addAction(self.act_top)
        self.menu.addAction(self.act_hide)
        self.menu.addAction(self.act_auto)
        self.menu.addSeparator()
        self.menu.addMenu(self.drink_menu)
        self.menu.addMenu(self.sit_menu)
        self.menu.addMenu(self.offwork_menu)
        self.menu.addAction(self.act_hourly)
        self.menu.addMenu(self.im_menu)
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
        self.window.update_drink_settings()

    def _sync_interval_checks(self, mins=None) -> None:
        if mins is None:
            mins = int(config.get("drink_interval"))
        for m, act in self._interval_acts.items():
            act.setChecked(m == mins)

    def _on_interval(self, mins: int) -> None:
        config.set_value("drink_interval", mins)
        self._sync_interval_checks(mins)
        self.window.update_drink_settings()

    def _on_custom_interval(self) -> None:
        current = int(config.get("drink_interval"))
        val, ok = QInputDialog.getInt(
            None, "自定义喝水间隔", "每隔多少分钟提醒喝水？", current, 1, 1440, 1
        )
        if ok:
            config.set_value("drink_interval", val)
            self._sync_interval_checks(val)
            self.window.update_drink_settings()

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
        self._sync_interval_checks()
        self._sync_size_checks()
        self._sync_sit_interval_checks()
        self._sync_offwork_checks()
        self._sync_delay_checks()
        self._sync_skin_checks()

    def _on_location(self, loc: str) -> None:
        config.set_value("drink_location", loc)
        self.window.update_drink_settings()

    def _on_hourly(self, checked: bool) -> None:
        config.set_value("hourly_enabled", checked)
        self.window.refresh_reminders()

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
        self.window.refresh_reminders()

    def _on_sit_interval(self, mins: int) -> None:
        config.set_value("sit_interval", mins)
        self._sync_sit_interval_checks(mins)
        self.window.refresh_reminders()

    def _sync_offwork_checks(self, t=None) -> None:
        if t is None:
            t = config.get("offwork_time")
        for tm, act in self._offwork_acts.items():
            act.setChecked(tm == t)

    def _on_offwork_enabled(self, checked: bool) -> None:
        config.set_value("offwork_enabled", checked)
        self.window.refresh_reminders()

    def _on_offwork_time(self, t: str) -> None:
        config.set_value("offwork_time", t)
        self._sync_offwork_checks(t)
        self.window.refresh_reminders()

    def _on_custom_offwork_time(self) -> None:
        current = config.get("offwork_time")
        text, ok = QInputDialog.getText(
            None, "自定义下班时间", "下班时间（HH:MM，如 18:30）", text=current
        )
        if ok and text:
            config.set_value("offwork_time", text)
            self._sync_offwork_checks(text)
            self.window.refresh_reminders()

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

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.window.show()

    def _on_quit(self) -> None:
        self.window.close()
        QApplication.instance().quit()
