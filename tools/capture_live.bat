@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === UI2058E / перехват данных из работающего приложения ===
echo Приложение UI2058.exe должно быть ЗАПУЩЕНО и показывать данные.
echo Остановить: Ctrl+C.
echo.
python capture_live.py
echo.
pause