"""开机自启：HKCU 注册表 Run 键（无需管理员权限，标准做法）。

- 打包后（PyInstaller frozen）：写/删 `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`
  下的 `DesktopPet` 项，值为 exe 绝对路径（含空格时加引号）；
- 开发环境（非 frozen）：不写入注册表，set_auto_start 返回 False，避免污染用户环境；
- 状态查询读注册表实际值，而非内存缓存，防止用户手动改过启动项后界面不同步。
"""
import logging
import sys

logger = logging.getLogger("autostart")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "DesktopPet"


def _frozen_exe() -> str:
    """打包后返回 exe 绝对路径；开发环境返回空串。"""
    if getattr(sys, "frozen", False):
        return sys.executable
    return ""


def is_auto_start() -> bool:
    """查询当前是否已设置开机自启（读注册表实际状态）。"""
    if not _frozen_exe():
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE
        )
        try:
            winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError as e:
        logger.warning("查询开机自启状态失败: %s", e)
        return False


def set_auto_start(enabled: bool) -> bool:
    """写入/删除开机自启项。开发环境（非打包）不生效，返回 False。"""
    exe = _frozen_exe()
    if not exe:
        logger.info("开发环境跳过开机自启设置")
        return False
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE
        )
        try:
            if enabled:
                # 路径含空格时需加引号，否则开机启动解析失败
                winreg.SetValueEx(
                    key, RUN_VALUE_NAME, 0, winreg.REG_SZ, f'"{exe}"'
                )
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass  # 本来就没设置，忽略
        finally:
            winreg.CloseKey(key)
        logger.info("开机自启已%s", "开启" if enabled else "关闭")
        return True
    except OSError as e:
        logger.warning("设置开机自启失败: %s", e)
        return False
