"""配置持久化与资源路径定位。

打包成 PyInstaller onefile 后，程序运行目录是临时解压目录，
因此数据（日志/配置）写入用户目录，资源从 sys._MEIPASS 读取。
"""
import os
import sys

from PySide6.QtCore import QSettings

APP_NAME = "DesktopPet"
ORG_NAME = "DesktopPet"

# 用户数据目录：日志 + 配置（跨升级保留）
DATA_DIR = os.path.join(os.path.expanduser("~"), ".desktop_pet")
LOG_DIR = os.path.join(DATA_DIR, "logs")


def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)


def resource_path(*parts: str) -> str:
    """定位打包内资源；开发环境指向项目目录。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", *parts)


def settings() -> QSettings:
    return QSettings(ORG_NAME, APP_NAME)


# 默认皮肤：'default' 表示使用 skins/ 根目录下的旧版（兼容）；其他为 skins/<子目录名>/
DEFAULT_SKIN = "default"

# 换肤支持的必需帧
SKIN_FRAMES = ("idle", "blink", "walk_a", "walk_b", "jump", "sleep")


def list_skins() -> list[str]:
    """扫描可用皮肤：返回 ['default', 'yellow_pet', ...] 列表。
    'default' 总是存在（指向 skins/ 根目录的旧版帧）；其他为 skins/ 下含全部必需帧的子目录。
    """
    base = resource_path("skins")
    found = ["default"]
    if not os.path.isdir(base):
        return found
    for name in sorted(os.listdir(base)):
        full = os.path.join(base, name)
        if not os.path.isdir(full):
            continue
        # 跳过下划线开头的开发目录（如 _dev, _raw）
        if name.startswith(("_", ".")):
            continue
        # 必须包含全部 6 个帧
        if all(os.path.isfile(os.path.join(full, f"{f}.png")) for f in SKIN_FRAMES):
            found.append(name)
    return found


def current_skin() -> str:
    """读取当前皮肤名（非法值回退 default）。"""
    val = settings().value("skin", DEFAULT_SKIN)
    if val in list_skins():
        return val
    return DEFAULT_SKIN


DEFAULTS = {
    "always_on_top": True,
    "auto_start": False,
    "scale": 0.65,  # 宠物缩放系数（1.0 = 260px 原始高度）
    "pos_x": -1,   # -1 表示未记录，默认吸附右下角
    "pos_y": -1,
    # 当前皮肤
    "skin": DEFAULT_SKIN,
    # 喝水提醒
    "drink_enabled": False,
    "drink_interval": 60,       # 分钟
    "drink_location": "center",  # "center" 跑到屏幕中心 / "current" 原地
    # 整点报时
    "hourly_enabled": False,
    # 久坐休息
    "sit_enabled": False,
    "sit_interval": 45,         # 分钟
    # 下班倒计时
    "offwork_enabled": False,
    "offwork_time": "18:00",
    # 飞书/灵犀新消息提醒（同时控制「通知中心监听」与「任务栏未读监听」两个 watcher）
    "feishu_enabled": True,
    # 未读超时强提醒：某 IM 持续未读超过该秒数，桌宠跑到屏幕中心再提醒
    "unread_center_delay": 120,
}

# 喝水提醒可选间隔（分钟）
DRINK_INTERVALS = [30, 60, 90, 120]

# 多样化喝水提示词（随机选取）
DRINK_MESSAGES = [
    "该喝水啦，起来活动一下～",
    "补充水分，保持满满活力！",
    "喝水时间到，别忘了哦",
    "干杯！记得喝口水",
    "工作再忙，也要照顾好自己，喝口水吧",
    "给你递杯水，快喝一口～",
    "定时喝水，健康一整天",
    "喝口水润润嗓，继续加油！",
    "滴——水分余额不足，请及时补水",
    "休息一下，喝口水再战～",
    "久坐伤身，起来接杯水吧",
    "今天的水喝够了吗？再喝一口～",
]


def get(key):
    return settings().value(key, DEFAULTS.get(key))


def set_value(key, value) -> None:
    s = settings()
    s.setValue(key, value)
    s.sync()


def get_drink_messages():
    """返回喝水提示词列表（后续可支持用户自定义）。"""
    return DRINK_MESSAGES


# 随机自言自语（随机事件 CHAT 使用，区别于喝水提醒）
RANDOM_MESSAGES = [
    "好无聊呀，陪我玩会儿～",
    "今天也要加油哦！",
    "有人吗？举个爪",
    "工作累了吧，伸个懒腰～",
    "偷偷看你一眼",
    "我在努力摸鱼中...",
    "记得坐直，别驼背～",
    "休息一下眼睛，看看远处吧",
    "今天过得怎么样呀？",
    "要不要起来走两步？",
    "嘿，我在呢！",
    "摸摸我会变好运哦～",
    "你的胆子真是肥嘟嘟的～",
]


def get_random_messages():
    return RANDOM_MESSAGES


# 点击回应（单击宠物）
CLICK_MESSAGES = [
    "哎呀，别戳我～",
    "痒痒的，哈哈",
    "找我干嘛呀？",
    "在的在的！",
    "抱抱！",
    "你的胆子真是肥嘟嘟的～",
    "给你比个心～",
    "别闹，我在认真站岗呢",
    "摸我头会变好运哦",
    "嗯？怎么了？",
    "叮！收到你的互动～",
    "嘿嘿，就知道你会点我",
    "乖，摸摸头～",
]


# 双击开心回应
HAPPY_MESSAGES = [
    "好开心！",
    "再跳一个！",
    "今天心情超好～",
    "嘿嘿，被你发现了",
    "冲鸭！",
    "耶！",
    "超喜欢你！",
    "开心得转圈圈～",
]


def get_click_messages():
    return CLICK_MESSAGES


def get_happy_messages():
    return HAPPY_MESSAGES


# 宠物大小可选档位（缩放系数）
SCALE_PRESETS = [("小", 0.5), ("中", 0.65), ("大", 0.85), ("特大", 1.0)]

# 久坐休息可选间隔（分钟）
SIT_INTERVALS = [30, 45, 60, 90]

# 下班时间预设
OFFWORK_PRESETS = ["17:00", "17:30", "18:00", "18:30", "19:00"]

# 消息未读超时强提醒可选档位（分钟）
UNREAD_CENTER_PRESETS = [1, 2, 3, 5]

# 整点报时台词（{h} 为小时数）
HOURLY_MESSAGES = [
    "现在是 {h} 点啦～",
    "{h} 点了，起来伸个懒腰吧",
    "叮！{h} 点整",
    "{h} 点啦，喝口水休息下眼睛",
    "报时：现在是 {h} 点",
]

# 久坐休息台词
SIT_MESSAGES = [
    "久坐伤身，起来活动活动吧",
    "坐了好久啦，站起来走两步～",
    "伸个懒腰，看看远处休息眼睛",
    "该起来活动一下啦，别一直坐着",
    "动一动，血液流通更健康～",
]

# 下班提醒台词
OFFWORK_MESSAGES = [
    "下班啦！辛苦一天了",
    "到点啦，可以下班啦！",
    "今天也辛苦啦，快下班休息～",
    "收工！享受下班时光吧",
]

# 飞书通知应用名关键词（用于识别系统通知来源，不区分大小写）
# 「灵犀 / lingxi」为飞书定制版（Lark 内核，应用名不同于官方飞书）
FEISHU_APP_NAMES = ["飞书", "feishu", "lark", "灵犀", "lingxi"]

# 任务栏未读提醒监测的 IM 应用：显示名 → 任务栏按钮名匹配关键词
# 按钮名匹配规则：== 关键词，或以「关键词 -」「关键词 (」开头（如「灵犀 - 1 个运行窗口」「QQ (3)」）
IM_APPS = {
    "灵犀": ["灵犀", "lingxi"],
    "QQ": ["QQ"],
    "微信": ["微信", "WeChat"],
    "企业微信": ["企业微信", "WeCom"],
}


def get_im_enabled(name):
    """某 IM 应用是否开启未读监测（默认开）。"""
    return settings().value(f"im_watch_{name}", True)


def set_im_enabled(name, value) -> None:
    s = settings()
    s.setValue(f"im_watch_{name}", value)
    s.sync()


def get_hourly_messages():
    return HOURLY_MESSAGES


def get_sit_messages():
    return SIT_MESSAGES


def get_offwork_messages():
    return OFFWORK_MESSAGES
