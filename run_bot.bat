@echo off
chcp 65001 >nul
title Nowshahr Port Bot - دستیار بندر نوشهر

REM ─────────────────────────────────────────────
REM  اجرای ربات بندر نوشهر
REM  پیش‌نیاز: 1) pip install -r requirements.txt
REM           2) VPN/پروکسی شما روشن باشد
REM  اگر پورت پروکسی شما فرق دارد، در خط زیر تغییرش بدهید
REM  (v2rayN معمولا: 10808 یا 10809 | کلش: 7890)
REM ─────────────────────────────────────────────

set HTTPS_PROXY=http://127.0.0.1:10808
set HTTP_PROXY=http://127.0.0.1:10808

cd /d "%~dp0"
echo 🚀 در حال اجرای ربات @NowshahrPMO_bot ...
echo (برای توقف: Ctrl+C)
echo ─────────────────────────────────────────────
python bot.py
pause
