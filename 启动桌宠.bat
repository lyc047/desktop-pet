@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动桌宠...
start "" python main.py
