"""配置持久化与资源路径定位。

打包成 PyInstaller onefile 后，程序运行目录是临时解压目录，
因此数据（日志/配置）写入用户目录，资源从 sys._MEIPASS 读取。
"""
import datetime
import json
import os
import sys
import time
import uuid

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
    # 提示音总开关（关闭后所有提醒只弹气泡、不响铃）
    "sound_enabled": True,
    # 免打扰时段：生效期间提醒只弹气泡、不响铃不跳跃不移动
    "quiet_enabled": False,
    "quiet_start": "22:30",
    "quiet_end": "08:00",
    # 专注模式：截止时间戳（time.time()），0 或已过期表示未开启
    "focus_until": 0,
    # 贴边隐藏：静止多少秒后滑到屏幕边缘只露一角，鼠标靠近再滑回来
    "edge_hide_enabled": True,
    # 离开感知：锁屏/离开时自动静默，回来补报（Windows 会话通知，零轮询开销）
    "away_detect_enabled": True,
    # 摸头互动：鼠标移到宠物身上会蹭你，累计抚摸会触发大反应
    "pet_enabled": True,
}

# 摸头互动参数
PET_STROKE_DISTANCE = 48   # 在身体上累计移动多少 px 算「摸了一下」
PET_BIG_REACTION = 8       # 累计摸多少下触发一次大反应（连跳 + 大笑）
PET_QUOTE_COOLDOWN = 6     # 摸头台词冷却（秒），避免移动鼠标时刷屏
PET_HIT_ALPHA = 24         # 像素 alpha 大于该值才算摸到身体（精灵图四周是透明的）
PET_BOUNCE_HEIGHT = 8      # 摸头反馈的弹动高度（px）。注意必须是「图片上下晃」而不是
                           # 移动窗口：窗口一动就从光标底下溜走，Qt 立刻发 leave 事件，
                           # 悬停状态被打断，实际效果变成「摸一下就断」。

# 免打扰时段预设（显示名, 开始, 结束）
QUIET_PRESETS = [
    ("22:30 - 08:00（夜间）", "22:30", "08:00"),
    ("23:00 - 07:00（夜间）", "23:00", "07:00"),
    ("12:30 - 14:00（午休）", "12:30", "14:00"),
]

# 专注模式时长预设（分钟）
FOCUS_PRESETS = [30, 60, 120]

# 番茄钟：经典 Pomodoro Technique。work → short_break → work → ... → long_break → work
# 阶段切换时不弹系统通知（番茄钟是"温和"循环），仅在桌宠身上切表情 + 弹气泡。
# 这与 1.2.0 专注模式完全独立：用户可以同时存在一个专注模式（任意时长静默）
# 和一个番茄钟（循环阶段静默），统一通过 is_silent_now() 通道抑制提醒。
POMODORO_PHASES = ("work", "short_break", "long_break")
POMODORO_WORK_MIN = 25          # 单段工作时长
POMODORO_SHORT_BREAK_MIN = 5    # 短休时长
POMODORO_LONG_BREAK_MIN = 15    # 长休时长
POMODORO_LONG_EVERY = 4         # 多少个 work 后进入长休

# 贴边隐藏：静止超过 N 秒后自动贴边（默认 30s）
EDGE_HIDE_IDLE_SECONDS = 30

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


def get(key, default=None):
    """读取配置。

    default 为 None 时回落到 DEFAULTS 里的值；显式传值则用调用方的兜底。
    """
    if default is None:
        default = DEFAULTS.get(key)
    return settings().value(key, default)


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
]

# feidudu（肥嘟嘟）皮肤专属台词（与全局台词混合使用，凸显个性）
FEIDUDU_MESSAGES = [
    "你的胆子真是肥嘟嘟的～",
    "我的胆子，肥嘟嘟的！",
    "别看我软，胆子很肥～",
    "肚子嘟嘟，胆子鼓鼓",
    "肥嘟嘟的胆子，在此！",
    "胆子肥嘟嘟，干啥都不怵",
    "摸我一下，胆子也会变肥哦",
]


def get_random_messages():
    """按当前皮肤返回随机台词：feidudu 皮肤追加专属台词。"""
    if current_skin() == "feidudu":
        return RANDOM_MESSAGES + FEIDUDU_MESSAGES
    return RANDOM_MESSAGES


# 点击回应（单击宠物）
CLICK_MESSAGES = [
    "哎呀，别戳我～",
    "痒痒的，哈哈",
    "找我干嘛呀？",
    "在的在的！",
    "抱抱！",
    "给你比个心～",
    "别闹，我在认真站岗呢",
    "摸我头会变好运哦",
    "嗯？怎么了？",
    "叮！收到你的互动～",
    "嘿嘿，就知道你会点我",
    "乖，摸摸头～",
]

# feidudu 皮肤专属点击回应
FEIDUDU_CLICK_MESSAGES = [
    "你的胆子真是肥嘟嘟的～",
    "轻点戳，我的胆子会漏气",
    "肥嘟嘟本嘟在此",
    "别闹，我在认真地肥着",
    "戳我？胆子不小嘛",
    "嘿嘿，肥嘟嘟的肚子禁摸",
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
    """按当前皮肤返回点击回应：feidudu 皮肤追加专属回应。"""
    if current_skin() == "feidudu":
        return CLICK_MESSAGES + FEIDUDU_CLICK_MESSAGES
    return CLICK_MESSAGES


# 动作切换台词（状态机切换时弹气泡，增强互动性）
# 结构：{state: {"default": [...], "feidudu": [...]}}
ACTION_QUOTES = {
    "walk": {
        "default": [
            "出去溜达一圈～",
            "迈开小短腿，散步去",
            "溜达溜达～",
        ],
        "feidudu": [
            "肥嘟嘟去巡逻了～",
            "肚子胖胖，脚步稳当",
            "溜达溜达，消化消化",
        ],
    },
    "jump": {
        "default": [
            "跳一个！",
            "蹦跶两下",
            "飞起来啦！",
        ],
        "feidudu": [
            "胆子肥，跳得高！",
            "蹦跶蹦跶，肉肉晃悠",
            "跳起来给你看～",
        ],
    },
    "sleep": {
        "default": [
            "困了，眯一会儿～",
            "眼皮打架了",
            "先睡为敬",
            "呼噜…",
        ],
        "feidudu": [
            "胆子鼓鼓，先睡为敬～",
            "吃饱了，歇会儿",
            "呼噜呼噜…",
        ],
    },
    "wander": {
        "default": [
            "去那边看看",
            "我巡逻一下",
        ],
        "feidudu": [
            "肥嘟嘟巡逻时间到",
            "转转肚皮，找点乐子",
        ],
    },
    "idle": {
        "default": [
            "待机中…",
        ],
        "feidudu": [
            "肥嘟嘟在此待命",
        ],
    },
    "chat": {
        "default": RANDOM_MESSAGES,
        "feidudu": RANDOM_MESSAGES + FEIDUDU_MESSAGES,
    },
    # 喝水/喝水提醒（drink 状态或喝水提醒时弹）
    "drink": {
        "default": [
            "喝口水润润嗓",
            "干杯～",
            "咕嘟咕嘟…",
        ],
        "feidudu": [
            "肚皮嘟嘟，喝水补补",
            "肥嘟嘟干杯！",
            "咕嘟咕嘟，肚皮圆了",
        ],
    },
}


def get_action_quotes(state: str) -> list[str]:
    """按当前皮肤返回指定状态的切换台词。空列表表示不弹台词。"""
    table = ACTION_QUOTES.get(state, {})
    skin = current_skin()
    if skin == "feidudu" and "feidudu" in table:
        return table["feidudu"]
    return table.get("default", [])


# 动作台词冷却时间（秒）：同一状态切换在该时间内不重复弹台词，避免刷屏
ACTION_QUOTE_COOLDOWN = 8


def get_happy_messages():
    return HAPPY_MESSAGES


# 摸头互动台词（鼠标在宠物身上移动时按冷却随机弹）
PET_MESSAGES = [
    "哎呀，痒痒的～",
    "嘿嘿，摸摸头",
    "舒服…再摸两下",
    "被你摸得好开心",
    "呼噜呼噜…",
    "头可断，发型不能乱！",
    "别停，继续～",
    "你手好暖呀",
    "摸头是要收费的（开玩笑）",
]

# 睡觉时被摸醒的迷糊台词
PET_SLEEPY_MESSAGES = [
    "唔…别闹，再睡五分钟",
    "嗯…谁在摸我…",
    "哈啊——被吵醒了",
    "困…但是被摸好舒服…",
    "（迷迷糊糊蹭了蹭你的手）",
]

# 累计抚摸到阈值的大反应台词
PET_BIG_MESSAGES = [
    "好舒服呀，转圈圈！",
    "摸够啦，我都要飘起来了～",
    "今天份的开心已充满！",
    "嘿嘿，最喜欢你了！",
    "全身都软乎乎的～",
]

FEIDUDU_PET_MESSAGES = [
    "摸肚子可以，摸头也行～",
    "肥嘟嘟的脑袋，随便摸",
    "再摸就要滚起来了",
    "胆子肥嘟嘟，随便rua",
]

FEIDUDU_PET_BIG_MESSAGES = [
    "肥嘟嘟被摸得圆了一圈！",
    "呼噜噜～肚皮也给你摸",
    "舒服得胆子都化了",
]


def get_pet_messages():
    """按当前皮肤返回摸头台词。"""
    if current_skin() == "feidudu":
        return PET_MESSAGES + FEIDUDU_PET_MESSAGES
    return PET_MESSAGES


def get_pet_sleepy_messages():
    return PET_SLEEPY_MESSAGES


def get_pet_big_messages():
    """按当前皮肤返回大反应台词。"""
    if current_skin() == "feidudu":
        return PET_BIG_MESSAGES + FEIDUDU_PET_BIG_MESSAGES
    return PET_BIG_MESSAGES


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


# ---------- 静默控制：提示音 / 免打扰时段 / 专注模式 ----------

def _flag(key: str) -> bool:
    """读取布尔配置，兼容 QSettings 返回字符串的情况（"false" 不能当真）。"""
    val = settings().value(key, DEFAULTS.get(key))
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def flag(key: str) -> bool:
    """公开布尔读取入口（_flag 的同义别名，供 UI 层使用）。"""
    return _flag(key)


def _parse_hm(text):
    """解析 HH:MM 字符串，失败返回 None。"""
    try:
        return datetime.datetime.strptime(str(text), "%H:%M").time()
    except Exception:
        return None


def quiet_active() -> bool:
    """当前是否处于免打扰时段。支持跨零点，如 22:30-08:00。"""
    if not _flag("quiet_enabled"):
        return False
    start = _parse_hm(settings().value("quiet_start", DEFAULTS["quiet_start"]))
    end = _parse_hm(settings().value("quiet_end", DEFAULTS["quiet_end"]))
    if start is None or end is None:
        return False
    now = datetime.datetime.now().time()
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def focus_active() -> bool:
    """专注模式是否生效中。"""
    try:
        return float(settings().value("focus_until", 0) or 0) > time.time()
    except (TypeError, ValueError):
        return False


def focus_remaining() -> int:
    """专注模式剩余秒数，未开启返回 0。"""
    try:
        left = float(settings().value("focus_until", 0) or 0) - time.time()
        return int(left) if left > 0 else 0
    except (TypeError, ValueError):
        return 0


def set_focus_minutes(mins: int) -> None:
    """开启专注模式若干分钟；mins <= 0 表示立即结束专注。"""
    set_value("focus_until", 0 if mins <= 0 else time.time() + mins * 60)


# ---------- 番茄钟（Pomodoro Timer）----------
# 阶段切换时不弹系统通知（番茄钟是"温和"循环），仅在桌宠身上切表情 + 弹气泡。
# 与 1.2.0 专注模式完全独立：用户可以同时存在一个专注模式（任意时长静默）
# 和一个番茄钟（循环阶段静默），统一通过 is_silent_now() 通道抑制提醒。
#
# 运行状态全部持久化在 QSettings（与离开状态不同——番茄钟是用户主动启动的
# 长任务，进程崩溃后应能从断点恢复，不要让用户重新开始）。
#
#   pomodoro_active: bool — 是否在跑
#   pomodoro_phase: "work" / "short_break" / "long_break"
#   pomodoro_round: int — 当前是第几个 work（1..POMODORO_LONG_EVERY）
#   pomodoro_phase_end: float — 当前阶段结束时间戳（time.time()）
#   pomodoro_phase_start: float — 当前阶段开始时间戳
#   pomodoro_today_date: str — YYYY-MM-DD，今日计数归属日
#   pomodoro_today_count: int — 今日已完成 work 数（番茄数）


def _pomodoro_state():
    """从 QSettings 读取番茄钟运行状态字段。返回 dict（不存在的字段返回空串/0）。"""
    s = settings()
    return {
        "active": _flag("pomodoro_active"),
        "phase": str(s.value("pomodoro_phase", "work") or "work"),
        "round": s.value("pomodoro_round", 1),
        "end": s.value("pomodoro_phase_end", 0),
        "start": s.value("pomodoro_phase_start", 0),
    }


def pomodoro_active() -> bool:
    """番茄钟是否在跑。"""
    return _flag("pomodoro_active")


def pomodoro_phase() -> str | None:
    """当前阶段：work / short_break / long_break，未启动返回 None。"""
    if not pomodoro_active():
        return None
    phase = str(_pomodoro_state()["phase"])
    return phase if phase in POMODORO_PHASES else None


def pomodoro_phase_end() -> float:
    """当前阶段结束时间戳。"""
    try:
        return float(_pomodoro_state()["end"] or 0)
    except (TypeError, ValueError):
        return 0.0


def pomodoro_round() -> int:
    """当前是第几个 work（番茄数）。"""
    try:
        return max(1, int(_pomodoro_state()["round"] or 1))
    except (TypeError, ValueError):
        return 1


def pomodoro_phase_remaining() -> int:
    """当前阶段剩余秒数。番茄钟未启动返回 0。"""
    if not pomodoro_active():
        return 0
    end = pomodoro_phase_end()
    if end <= 0:
        return 0
    left = end - time.time()
    return max(0, int(left))


def pomodoro_today_count() -> int:
    """今日已完成番茄数（归属日变更时自动重置）。"""
    s = settings()
    today = time.strftime("%Y-%m-%d")
    saved_date = str(s.value("pomodoro_today_date", "") or "")
    if saved_date != today:
        return 0
    try:
        return max(0, int(s.value("pomodoro_today_count", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _phase_minutes(phase: str) -> int:
    return {
        "work": POMODORO_WORK_MIN,
        "short_break": POMODORO_SHORT_BREAK_MIN,
        "long_break": POMODORO_LONG_BREAK_MIN,
    }[phase]


def _next_phase(current: str, round_num: int) -> str:
    """work → break（按 round 决定短/长），break → work。"""
    if current == "work":
        return "long_break" if round_num >= POMODORO_LONG_EVERY else "short_break"
    return "work"


def start_pomodoro() -> None:
    """启动番茄钟：从 work round 1 开始。已运行时 noop（避免重启阶段时间）。"""
    if pomodoro_active():
        return
    s = settings()
    now = time.time()
    s.setValue("pomodoro_active", True)
    s.setValue("pomodoro_phase", "work")
    s.setValue("pomodoro_round", 1)
    s.setValue("pomodoro_phase_end", now + POMODORO_WORK_MIN * 60)
    s.setValue("pomodoro_phase_start", now)
    s.sync()


def stop_pomodoro() -> None:
    """停止番茄钟（清阶段、关计时器，保留今日计数）。"""
    s = settings()
    s.setValue("pomodoro_active", False)
    s.setValue("pomodoro_phase", "work")
    s.setValue("pomodoro_phase_end", 0)
    s.setValue("pomodoro_phase_start", 0)
    s.sync()


def pomodoro_tick() -> tuple | None:
    """每秒调用：阶段结束则切换到下一阶段。

    返回 (old_phase, new_phase, finished_work) 或 None。
    finished_work = True 表示刚完成一个 work 阶段（番茄数 +1）。

    关键：判断"下一阶段是 short 还是 long"必须用**完成前**的 round_num
    （因为 round 1 完成 → 应该是 short_break，round 4 完成 → 才是 long_break）。
    """
    if not pomodoro_active():
        return None
    end = pomodoro_phase_end()
    if end <= 0 or time.time() < end:
        return None
    s = settings()
    old_phase = pomodoro_phase() or "work"
    finished_work = old_phase == "work"
    old_round = pomodoro_round()
    if finished_work:
        today = time.strftime("%Y-%m-%d")
        saved_date = str(s.value("pomodoro_today_date", "") or "")
        count = 0
        if saved_date == today:
            try:
                count = max(0, int(s.value("pomodoro_today_count", 0) or 0))
            except (TypeError, ValueError):
                count = 0
        s.setValue("pomodoro_today_date", today)
        s.setValue("pomodoro_today_count", count + 1)
        # 完成第 POMODORO_LONG_EVERY 个 work 后，下一轮 round 回到 1
        if old_round >= POMODORO_LONG_EVERY:
            s.setValue("pomodoro_round", 1)
        else:
            s.setValue("pomodoro_round", old_round + 1)
    # 用"完成前"的 round_num 决定下一阶段（修复 round 时机错位）
    new_phase = _next_phase(old_phase, old_round)
    new_minutes = _phase_minutes(new_phase)
    now = time.time()
    s.setValue("pomodoro_phase", new_phase)
    s.setValue("pomodoro_phase_end", now + new_minutes * 60)
    s.setValue("pomodoro_phase_start", now)
    s.sync()
    return (old_phase, new_phase, finished_work)


# 离开状态（锁屏）是纯内存标记：不写 QSettings，避免程序崩溃后残留
# 「一直在离开中」导致提醒永远静默。每次启动自然是 False。
_away = False


def set_away(value: bool) -> None:
    """标记用户是否离开（锁屏）。仅内存，不持久化。"""
    global _away
    _away = bool(value)


def is_away() -> bool:
    return _away


def is_silent_now() -> bool:
    """当前是否静默：免打扰时段、专注模式、离开（锁屏）、番茄钟任一生效。

    静默期间提醒只弹气泡，不响铃、不跳跃、不跑到屏幕中心。
    """
    return quiet_active() or focus_active() or is_away() or pomodoro_active()


def sound_allowed() -> bool:
    """是否允许播放提示音：总开关打开且不处于静默状态。"""
    return _flag("sound_enabled") and not is_silent_now()


def sound_enabled() -> bool:
    """提示音总开关当前值（供托盘勾选显示）。"""
    return _flag("sound_enabled")


def quiet_enabled() -> bool:
    """免打扰时段开关当前值。"""
    return _flag("quiet_enabled")


def quiet_start() -> str:
    return str(settings().value("quiet_start", DEFAULTS["quiet_start"]))


def quiet_end() -> str:
    return str(settings().value("quiet_end", DEFAULTS["quiet_end"]))


# ---------- 自定义提醒事项 ----------

def get_custom_reminders() -> list:
    """读取自定义提醒事项列表（JSON 存在 QSettings，字段缺失时补齐默认值）。"""
    raw = settings().value("custom_reminders", "[]")
    if isinstance(raw, list):
        items = raw
    else:
        try:
            items = json.loads(str(raw))
        except Exception:
            items = []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        label = str(it.get("label") or "").strip()
        time_text = str(it.get("time") or "").strip()
        if not label or not time_text:
            continue
        out.append({
            "id": str(it.get("id") or uuid.uuid4().hex[:8]),
            "label": label,
            "time": time_text,
            "kind": str(it.get("kind") or "daily"),
            "weekday": int(it.get("weekday") or 0),
            "date": str(it.get("date") or ""),
            "enabled": _flag_item(it.get("enabled", True)),
        })
    return out


def _flag_item(val) -> bool:
    """提醒事项的 enabled 字段容错（QSettings 可能回传字符串）。"""
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def save_custom_reminders(items: list) -> None:
    set_value("custom_reminders", json.dumps(items, ensure_ascii=False))


def add_custom_reminder(item: dict) -> None:
    items = get_custom_reminders()
    items.append(item)
    save_custom_reminders(items)


def remove_custom_reminder(rid: str) -> None:
    save_custom_reminders([i for i in get_custom_reminders() if i.get("id") != rid])


def set_custom_reminder_enabled(rid: str, enabled: bool) -> None:
    items = get_custom_reminders()
    for it in items:
        if it.get("id") == rid:
            it["enabled"] = bool(enabled)
    save_custom_reminders(items)
