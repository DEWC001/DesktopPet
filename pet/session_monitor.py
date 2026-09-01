"""锁屏 / 解锁感知（Windows 会话通知）。

用途：用户离开电脑（Win+L、屏保、休眠唤醒）时让桌宠自动静默，回来时补报。

实现方式：通过 wtsapi32 的 WTSRegisterSessionNotification 注册窗口接收
WM_WTSSESSION_CHANGE 消息，锁屏/解锁时系统直接推送，无需轮询。

为什么不用轮询检测：
- 轮询（如 OpenInputDesktop / GetLastInputInfo）要么区分不了锁屏和单纯
  没操作，要么拿不到解锁瞬间，且要给每个检测点埋定时器。
- 会话通知是事件驱动的，零轮询开销，锁屏/解锁两个瞬间都精确。

注意：注册需要在窗口 HWND 创建之后（showEvent 里做，不能在 __init__）。
注销不是必须的（窗口销毁时系统自动清理），但显式注销更干净。
"""
import ctypes
import logging
from ctypes import wintypes

logger = logging.getLogger("session")

WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
NOTIFY_FOR_THIS_SESSION = 0

_wtsapi32 = None


# 注意导出名是 WTSUnRegisterSessionNotification —— Un 后面是**大写 R**。
# 这是 Win32 API 的历史命名不一致（Register 有，Unregister 没有），
# 写成 WTSUnregisterSessionNotification 会找不到符号。
_UNREGISTER_NAME = "WTSUnRegisterSessionNotification"


def _lib():
    """惰性加载 wtsapi32，失败时缓存 False 避免反复重试。

    逐个符号设置签名：任一符号缺失只让它自己不可用，不能让整个模块瘫痪
    （曾经因为把注销函数名写错，连注册都一起失效了）。
    """
    global _wtsapi32
    if _wtsapi32 is None:
        try:
            lib = ctypes.WinDLL("wtsapi32")
        except Exception as e:  # noqa: BLE001
            logger.warning("wtsapi32 加载失败，锁屏感知不可用: %s", e)
            _wtsapi32 = False
            return None

        register_ok = False
        try:
            lib.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
            lib.WTSRegisterSessionNotification.restype = wintypes.BOOL
            register_ok = True
        except AttributeError as e:
            logger.warning("WTSRegisterSessionNotification 不可用: %s", e)

        try:
            fn = getattr(lib, _UNREGISTER_NAME)
            fn.argtypes = [wintypes.HWND]
            fn.restype = wintypes.BOOL
        except AttributeError as e:
            # 注销缺失不影响注册：窗口销毁时系统会自行清理
            logger.warning("%s 不可用（不影响注册）: %s", _UNREGISTER_NAME, e)

        _wtsapi32 = lib if register_ok else False
    return _wtsapi32 or None


def available() -> bool:
    """当前环境是否支持会话通知。"""
    return _lib() is not None


def register(hwnd: int) -> bool:
    """注册窗口接收会话变更通知。hwnd 必须是已创建的窗口句柄。"""
    lib = _lib()
    if lib is None:
        return False
    try:
        ok = lib.WTSRegisterSessionNotification(wintypes.HWND(hwnd), NOTIFY_FOR_THIS_SESSION)
        if not ok:
            logger.warning(
                "WTSRegisterSessionNotification 失败: %s",
                ctypes.WinError(ctypes.get_last_error()),
            )
        return bool(ok)
    except Exception as e:  # noqa: BLE001
        logger.warning("会话通知注册异常: %s", e)
        return False


def unregister(hwnd: int) -> None:
    """注销会话变更通知（关闭功能或退出时调用）。"""
    lib = _lib()
    if lib is None:
        return
    fn = getattr(lib, _UNREGISTER_NAME, None)
    if fn is None:
        return
    try:
        fn(wintypes.HWND(hwnd))
    except Exception:  # noqa: BLE001
        pass


def _message_address(message):
    """从 nativeEvent 传进来的 message 取出内存地址。

    PySide6 不同版本给的类型不一致（voidptr / PyCapsule / int），逐个尝试。

    返回值必须严格校验：MSG.from_address() 不做任何合法性检查，传个负数或
    野指针会**直接段错误**（进程崩溃），比抛异常严重得多。所以这里对非正
    整数和超出 64 位地址空间的值一律拒绝。
    """
    candidates = [message]
    if not isinstance(message, int):
        candidates = []
        for getter in (lambda: int(message), lambda: message.__int__()):
            try:
                candidates.append(getter())
            except Exception:  # noqa: BLE001
                continue
    for addr in candidates:
        if not isinstance(addr, int):
            continue
        if addr <= 0 or addr >= (1 << 63):
            continue
        return addr
    return None


def parse_message(message) -> str | None:
    """解析 nativeEvent 的 message，返回 'lock' / 'unlock' / None。

    None 表示不是会话变更消息（其它消息一律忽略）。
    """
    addr = _message_address(message)
    if not addr:
        return None
    try:
        msg = wintypes.MSG.from_address(addr)
    except Exception:  # noqa: BLE001
        return None
    if int(msg.message) != WM_WTSSESSION_CHANGE:
        return None
    wparam = int(msg.wParam)
    if wparam == WTS_SESSION_LOCK:
        return "lock"
    if wparam == WTS_SESSION_UNLOCK:
        return "unlock"
    return None


# 测试用缓冲区保活列表。make_message 返回的裸地址本身不带引用，
# 若 buf 是局部变量，函数返回后就被回收，地址变成悬空指针（读出来是垃圾值）。
_TEST_BUFFERS: list = []


def make_message(kind: str) -> int:
    """构造一个 WM_WTSSESSION_CHANGE 消息并返回其内存地址（仅供测试使用）。

    缓冲区必须存进模块级列表保活，否则函数一返回就被 GC，
    拿到的地址解析出来全是随机值。
    """
    wparam = WTS_SESSION_LOCK if kind == "lock" else WTS_SESSION_UNLOCK
    buf = (ctypes.c_char * ctypes.sizeof(wintypes.MSG))()
    msg = wintypes.MSG.from_buffer(buf)
    msg.message = WM_WTSSESSION_CHANGE
    msg.wParam = wparam
    _TEST_BUFFERS.append(buf)
    if len(_TEST_BUFFERS) > 64:      # 测试用的，别无上限增长
        _TEST_BUFFERS.clear()
    return ctypes.addressof(buf)
