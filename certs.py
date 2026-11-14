# -*- coding: utf-8 -*-
"""
🔔 یادآور گواهینامه‌ها — کارمند خودش گواهی‌هایش را ثبت می‌کند
(گوارد، ایمنی، دریانوردی، گواهینامه رانندگی و...) و ربات قبل از انقضا هشدار می‌دهد.
تاریخ شمسی و میلادی هر دو پذیرفته می‌شود. هیچ داده سازمانی لازم ندارد.
"""
import asyncio, datetime, logging, time

import config, db

log = logging.getLogger("certs")

THRESHOLDS = (30, 15, 7, 3, 1, 0)   # روزهای مانده که هشدار می‌دهیم


# ─────────────── تبدیل تاریخ جلالی ← میلادی (الگوریتم استاندارد jdf) ───────────────
def jalali_to_gregorian(jy: int, jm: int, jd: int):
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    md = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    for i in range(1, 13):
        if gd <= md[i]:
            gm = i
            break
        gd -= md[i]
    return gy, gm, gd


def parse_date_input(text: str):
    """«1404-09-22» (جلالی) یا «2025-12-13» (میلادی) → timestamp؛ جداکننده / یا -"""
    s = text.strip().replace("/", "-").replace(".", "-")
    parts = s.split("-")
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not (1 <= m <= 12 and 1 <= d <= 31):
        return None
    if y <= 1500:                      # سال شمسی
        y, m, d = jalali_to_gregorian(y, m, d)
    try:
        dt = datetime.datetime(y, m, d)
    except ValueError:
        return None
    return dt.timestamp()


def days_left(expiry_ts: float) -> int:
    return int((expiry_ts - time.time()) // 86400)


def _fmt_list(chat_id: int) -> str:
    certs = db.get_certificates(chat_id)
    if not certs:
        return ("🔔 <b>گواهینامه‌های من</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "هنوز گواهی‌ای ثبت نکرده‌اید.\n"
                "➕ «افزودن گواهینامه» را بزنید — مثلاً:\n"
                "• گوارد/آمادگی مبارزه با آتش\n"
                "• گواهینامه رانندگی\n"
                "• مدارک دریانوردی")
    lines = ["🔔 <b>گواهینامه‌های من</b>", "━━━━━━━━━━━━━━━━━━"]
    for c in certs:
        dl = days_left(c["expiry_ts"])
        if dl < 0:
            badge = "🔴 منقضی شده"
        elif dl <= 15:
            badge = "🔴 هشدار!"
        elif dl <= 30:
            badge = "🟡 نزدیک انقضا"
        else:
            badge = "🟢 سالم"
        lines.append(f"• <b>{c['title']}</b> — {c['date_str']}\n"
                     f"  {dl} روز مانده → {badge}")
    return "\n".join(lines)


# ─────────────── کار روزانه: چک و هشدار ───────────────
async def cert_check_job(context):
    now = time.time()
    for c in db.all_certificates():
        dl = days_left(c["expiry_ts"])
        if dl not in THRESHOLDS or c["last_alert_days"] == dl:
            continue
        if dl == 0:
            body = (f"🚨 <b>امروز آخرین روز اعتبار</b> «{c['title']}» است!\n"
                    f"تاریخ انقضا: {c['date_str']}\n"
                    f"برای تمدید اقدام کنید.")
        else:
            body = (f"🔔 <b>یادآور گواهینامه</b>\n"
                    f"«{c['title']}» تا <b>{dl} روز دیگر</b> منقضی می‌شود\n"
                    f"تاریخ انقضا: {c['date_str']}")
        try:
            await context.bot.send_message(c["chat_id"], body, parse_mode="HTML")
            db.set_cert_alerted(c["id"], dl)
        except Exception as e:
            log.warning("یادآور گواهی به %s ارسال نشد: %s", c["chat_id"], e)


def setup(app):
    # هر ۶ ساعت چک می‌کنیم (ساده و مقاوم به ری‌استارت)
    app.job_queue.run_repeating(cert_check_job, interval=6 * 3600, first=90,
                                name="cert_reminders")
