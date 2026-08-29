"""自测开机自启读写闭环：模拟 frozen 环境写/删 HKCU Run 键，测完清理。"""
import sys

sys.path.insert(0, r"D:\杂\桌宠")

# 模拟 PyInstaller 打包环境（frozen + 真实 exe 路径）
sys.frozen = True
sys.executable = r"D:\杂\桌宠\dist\DesktopPet.exe"

from pet import autostart

failed = False


def check(label, got, expect):
    global failed
    ok = got == expect
    if not ok:
        failed = True
    print(f"  {'PASS' if ok else 'FAIL'}  {label} -> {got!r} (期望 {expect!r})")


print("== 开机自启读写闭环 ==")

# 初始清理，确保从关闭状态开始
autostart.set_auto_start(False)
check("初始状态", autostart.is_auto_start(), False)

# 开启
autostart.set_auto_start(True)
check("开启后状态", autostart.is_auto_start(), True)

# 直接读注册表确认写入内容（路径应带引号）
import winreg

key = winreg.OpenKey(
    winreg.HKEY_CURRENT_USER, autostart.RUN_KEY_PATH, 0, winreg.KEY_QUERY_VALUE
)
try:
    val, t = winreg.QueryValueEx(key, autostart.RUN_VALUE_NAME)
finally:
    winreg.CloseKey(key)
check("注册表值", val, '"D:\\杂\\桌宠\\dist\\DesktopPet.exe"')
check("注册表类型", t, winreg.REG_SZ)

# 重复开启（幂等）
autostart.set_auto_start(True)
check("重复开启仍为真", autostart.is_auto_start(), True)

# 关闭
autostart.set_auto_start(False)
check("关闭后状态", autostart.is_auto_start(), False)

print()
print("全部通过" if not failed else "存在失败项")
sys.exit(1 if failed else 0)
