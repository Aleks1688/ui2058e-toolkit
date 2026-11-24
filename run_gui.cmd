@echo off
rem Запуск окна замера без лишнего окна консоли.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0measure_gui.ps1"