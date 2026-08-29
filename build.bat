@echo off
setlocal

REM 一键打包：产出 dist\DesktopPet.exe 单文件
set VENV_PY=C:\Users\chenwen15\.workbuddy\binaries\python\envs\default\Scripts\python.exe
set ROOT=%~dp0

%VENV_PY% -m pip install --quiet pyinstaller || goto :err

%VENV_PY% -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name DesktopPet ^
    --icon "%ROOT%assets\icon.ico" ^
    --add-data "%ROOT%assets;assets" ^
    --hidden-import winrt ^
    --hidden-import winrt.system ^
    --hidden-import winrt.windows.foundation ^
    --hidden-import winrt.windows.foundation.collections ^
    --hidden-import winrt.windows.ui.notifications ^
    --hidden-import winrt.windows.ui.notifications.management ^
    --hidden-import winrt.windows.applicationmodel ^
    --hidden-import uiautomation ^
    --collect-all comtypes ^
    "%ROOT%main.py"

if errorlevel 1 goto :err
echo.
echo Build OK: %ROOT%dist\DesktopPet.exe
exit /b 0

:err
echo Build FAILED
exit /b 1
