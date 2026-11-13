# -*- coding: utf-8 -*-
"""موتور هشدار: موج خطرناک (دوره‌ای) + ورود شناور به محدوده بندر (رویدادی)"""
import asyncio, logging, time

import httpx

import config, db, weather

log = logging.getLogger("alerts")


# ─────────────── هشدار دوره‌ای موج ───────────────
async def weather_alert_job(context):
    """هر چند دقیقه یک‌بار اجرا می‌شود؛ به مشترکین فعال پیام می‌دهد اگر موج از آستانه گذشته باشد."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as cl:
            r = await cl.get(weather.MARINE_URL, params={
                "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
                "current": "wave_height", "timezone": "Asia/Tehran",
            })
            r.raise_for_status()
            wave = r.json().get("current", {}).get("wave_height")
    except Exception as e:
        log.warning("weather alert fetch failed: %s", e)
        return

    if wave is None:
        return
    log.info("alert check: wave=%.2fm", wave)

    now = time.time()
    cooldown = config.WAVE_ALERT_COOLDOWN_HOURS * 3600
    for row in db.wave_subscribers():
        chat_id, thr, last = row["chat_id"], row["wave_threshold"], row["last_wave_alert"]
        if wave >= (thr or 1.5) and (now - (last or 0)) > cooldown:
            try:
                await context.bot.send_message(
                    chat_id,
                    f"⚠️ <b>هشدار موج — بندر نوشهر</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"ارتفاع موج فعلی: <b>{wave:.2f} متر</b> "
                    f"(آستانه شما: {thr:.2f} متر)\n"
                    f"برای عملیات دریایی احتیاط کنید و اعلان رسمی بندر را چک کنید.",
                    parse_mode="HTML")
                db.mark_wave_alert(chat_id)
            except Exception as e:
                log.warning("wave alert to %s failed: %s", chat_id, e)


# ─────────────── هشدار رویدادی: ورود شناور به محدوده ───────────────
async def _send_zone_alerts(app, ship_name, mmsi, dist_km):
    txt = (
        f"🔔 <b>ورود شناور به محدوده بندر نوشهر</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚢 شناور: <b>{ship_name}</b>\n"
        f"📍 فاصله از اسکله: {dist_km:.1f} کیلومتر\n"
        f"🕐 {time.strftime('%H:%M', time.localtime())}\n"
        f"<i>داده از جریان عمومی AIS — برای وضعیت رسمی پهلوگیری با بندر هماهنگ کنید.</i>"
    )
    for row in db.ais_subscribers():
        try:
            await app.bot.send_message(row["chat_id"], txt, parse_mode="HTML")
        except Exception as e:
            log.warning("zone alert to %s failed: %s", row["chat_id"], e)


def _make_zone_callback(app):
    def cb(ship_name, mmsi, dist_km):
        asyncio.create_task(_send_zone_alerts(app, ship_name, mmsi, dist_km))
    return cb


# ─────────────── راه‌اندازی ───────────────
def setup(app):
    import ais
    ais.set_zone_enter_callback(_make_zone_callback(app))
    app.job_queue.run_repeating(
        weather_alert_job,
        interval=config.WEATHER_ALERT_INTERVAL_MIN * 60,
        first=120,
        name="wave_alerts",
    )
