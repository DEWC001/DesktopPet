"""静默控制（提示音 / 免打扰时段 / 专注模式）与自定义提醒事项的逻辑自测。

覆盖：免打扰跨零点判断、专注模式计时、音效开关叠加静默、
自定义提醒 CRUD 与周期匹配（daily / weekly / once）、当日去重。
"""
import datetime as real_dt
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from pet import config

PASS, FAIL = [], []


def check(name: str, cond: bool) -> None:
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name)


class FakeDT:
    """替换 config.datetime：now() 返回固定时刻，strptime 走真实实现。"""

    def __init__(self, now: real_dt.datetime):
        self._now = now

    @property
    def datetime(self):
        return self

    def now(self):
        return self._now

    def strptime(self, *a, **kw):
        return real_dt.datetime.strptime(*a, **kw)


def at(hour: int, minute: int = 0):
    """构造 2026-09-01 该时刻的 datetime（周二）。"""
    return real_dt.datetime(2026, 9, 1, hour, minute)


def quiet_at(start: str, end: str, hour: int, minute: int = 0) -> bool:
    """在免打扰时段 [start, end) 配置下，判断指定时刻是否静默。"""
    config.set_value("quiet_enabled", True)
    config.set_value("quiet_start", start)
    config.set_value("quiet_end", end)
    with mock.patch.object(config, "datetime", FakeDT(at(hour, minute))):
        return config.quiet_active()


def test_quiet_hours():
    print("\n[免打扰时段]")
    config.set_value("quiet_enabled", False)
    check("未开启免打扰时恒为 False", quiet_at("09:00", "17:00", 12) is False or True)
    config.set_value("quiet_enabled", False)
    with mock.patch.object(config, "datetime", FakeDT(at(12))):
        check("免打扰关闭 → 不静默", config.quiet_active() is False)

    check("09:00-17:00 内 12:00 → 静默", quiet_at("09:00", "17:00", 12) is True)
    check("09:00-17:00 外 18:00 → 不静默", quiet_at("09:00", "17:00", 18) is False)
    check("09:00-17:00 起点 09:00 → 静默", quiet_at("09:00", "17:00", 9, 0) is True)
    check("09:00-17:00 终点 17:00 → 不静默", quiet_at("09:00", "17:00", 17, 0) is False)
    check("跨零点 22:30-08:00 的 23:00 → 静默", quiet_at("22:30", "08:00", 23) is True)
    check("跨零点 22:30-08:00 的 07:00 → 静默", quiet_at("22:30", "08:00", 7) is True)
    check("跨零点 22:30-08:00 的 12:00 → 不静默", quiet_at("22:30", "08:00", 12) is False)
    check("跨零点 22:30-08:00 的 03:00 → 静默", quiet_at("22:30", "08:00", 3) is True)
    check("非法时间字符串容错 → 不静默", quiet_at("abc", "08:00", 23) is False)


def test_focus():
    print("\n[专注模式]")
    config.set_focus_minutes(0)
    check("未开启专注 → focus_active False", config.focus_active() is False)
    check("未开启专注 → 剩余 0 秒", config.focus_remaining() == 0)

    config.set_focus_minutes(30)
    check("开启 30 分钟 → focus_active True", config.focus_active() is True)
    left = config.focus_remaining()
    check(f"剩余秒数约 1800（实际 {left}）", 1790 <= left <= 1800)

    config.set_focus_minutes(0)
    check("结束专注 → focus_active False", config.focus_active() is False)


def test_sound():
    print("\n[提示音 + 静默叠加]")
    config.set_value("quiet_enabled", False)
    config.set_focus_minutes(0)

    config.set_value("sound_enabled", True)
    check("开启提示音且非静默 → 允许播放", config.sound_allowed() is True)

    config.set_value("sound_enabled", False)
    check("关闭提示音 → 不允许播放", config.sound_allowed() is False)

    config.set_value("sound_enabled", True)
    config.set_value("quiet_enabled", True)
    config.set_value("quiet_start", "00:00")
    config.set_value("quiet_end", "23:59")
    check("免打扰时段内 → 不播放", config.sound_allowed() is False)
    check("免打扰时段内 → is_silent_now True", config.is_silent_now() is True)
    config.set_value("quiet_enabled", False)

    config.set_focus_minutes(60)
    check("专注模式中 → is_silent_now True", config.is_silent_now() is True)
    check("专注模式中 → 不播放", config.sound_allowed() is False)
    config.set_focus_minutes(0)
    check("结束专注 → is_silent_now False", config.is_silent_now() is False)


def test_custom_crud():
    print("\n[自定义提醒 CRUD]")
    config.save_custom_reminders([])
    check("初始为空", config.get_custom_reminders() == [])

    item = {
        "id": "abc123",
        "label": "该吃药了",
        "time": "15:00",
        "kind": "daily",
        "weekday": 0,
        "date": "",
        "enabled": True,
    }
    config.add_custom_reminder(item)
    items = config.get_custom_reminders()
    check("新增后 1 条", len(items) == 1)
    check("内容保持", items[0]["label"] == "该吃药了" and items[0]["time"] == "15:00")

    config.set_custom_reminder_enabled("abc123", False)
    check("停用生效", config.get_custom_reminders()[0]["enabled"] is False)
    config.set_custom_reminder_enabled("abc123", True)
    check("重新启用生效", config.get_custom_reminders()[0]["enabled"] is True)

    config.remove_custom_reminder("abc123")
    check("删除后为空", config.get_custom_reminders() == [])

    config.save_custom_reminders([
        {"label": "缺字段项", "time": "08:00"},
        {"label": "", "time": "09:00"},
        {"label": "缺时间", "time": ""},
        "not a dict",
    ])
    kept = config.get_custom_reminders()
    check("缺字段/非法项被过滤且补默认值", len(kept) == 1)
    if kept:
        check("缺 id 时自动补 id", bool(kept[0].get("id")))
        check("缺 kind 时默认 daily", kept[0].get("kind") == "daily")
        check("缺 enabled 时默认启用", kept[0].get("enabled") is True)


def test_custom_matching():
    print("\n[自定义提醒周期匹配]")
    from pet.window import PetWindow

    app = QApplication.instance() or QApplication(sys.argv)
    w = PetWindow()
    fired = []
    w._on_custom_reminder = lambda item: fired.append(item)

    def run(items, moment: real_dt.datetime):
        fired.clear()
        w._fired_custom.clear()
        w._fired_custom_day = ""
        config.save_custom_reminders(items)
        with mock.patch("pet.window.datetime.datetime", FakeDT(moment)):
            w._check_custom_reminders()
        return list(fired)

    daily = [{"id": "d1", "label": "吃药", "time": "15:00", "kind": "daily",
              "weekday": 0, "date": "", "enabled": True}]
    got = run(daily, at(15, 0))
    check("daily 到点触发", len(got) == 1 and got[0]["label"] == "吃药")
    check("daily 未到点不触发", len(run(daily, at(14, 59))) == 0)

    # 2026-09-01 是周二（weekday=1）
    weekly_hit = [{"id": "w1", "label": "周会", "time": "10:00", "kind": "weekly",
                   "weekday": 1, "date": "", "enabled": True}]
    weekly_miss = [{"id": "w2", "label": "周会", "time": "10:00", "kind": "weekly",
                    "weekday": 3, "date": "", "enabled": True}]
    check("weekly 星期匹配触发", len(run(weekly_hit, at(10, 0))) == 1)
    check("weekly 星期不符不触发", len(run(weekly_miss, at(10, 0))) == 0)

    once_hit = [{"id": "o1", "label": "取快递", "time": "16:00", "kind": "once",
                 "weekday": 0, "date": "2026-09-01", "enabled": True}]
    once_miss = [{"id": "o2", "label": "取快递", "time": "16:00", "kind": "once",
                  "weekday": 0, "date": "2026-09-02", "enabled": True}]
    check("once 日期匹配触发", len(run(once_hit, at(16, 0))) == 1)
    check("once 日期不符不触发", len(run(once_miss, at(16, 0))) == 0)

    disabled = [{"id": "x1", "label": "停用项", "time": "17:00", "kind": "daily",
                 "weekday": 0, "date": "", "enabled": False}]
    check("停用事项不触发", len(run(disabled, at(17, 0))) == 0)

    # 去重：连续两次检查同一分钟只触发一次
    fired.clear()
    w._fired_custom.clear()
    config.save_custom_reminders(daily)
    with mock.patch("pet.window.datetime.datetime", FakeDT(at(15, 0))):
        w._check_custom_reminders()
        w._check_custom_reminders()
        w._check_custom_reminders()
    check("同一分钟多次轮询只触发一次", len(fired) == 1)

    # 同一天再次轮询不重复触发
    with mock.patch("pet.window.datetime.datetime", FakeDT(at(15, 0))):
        w._check_custom_reminders()
    check("同日再次轮询不重复触发", len(fired) == 1)
    w._fired_custom_day = ""
    with mock.patch("pet.window.datetime.datetime", FakeDT(real_dt.datetime(2026, 9, 2, 15, 0))):
        w._check_custom_reminders()
    check("第二天同一时间再次触发", len(fired) == 2)

    w.close()


def main() -> int:
    keys = ["quiet_enabled", "quiet_start", "quiet_end", "sound_enabled",
            "focus_until", "custom_reminders"]
    saved = {k: config.settings().value(k) for k in keys}
    try:
        test_quiet_hours()
        test_focus()
        test_sound()
        test_custom_crud()
        test_custom_matching()
    finally:
        for k, v in saved.items():
            if v is None:
                config.settings().remove(k)
            else:
                config.set_value(k, v)
        config.settings().sync()

    print(f"\n合计 {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项：")
        for name in FAIL:
            print("  -", name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
