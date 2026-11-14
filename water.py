# -*- coding: utf-8 -*-
"""
🌊 پایش تراز آب بندر — دریافت داده سنسور (ESP32) روی UDP،
محاسبه تراز نسبت به مبنا، هشدار افت آبخور، و گزارش وضعیت.

پروتکل دستگاه: بسته UDP با JSON:
    {"id":"STN-NOSHR-1","dist_mm":3000.0,"temp_c":18.2,"datum_mm":5000.0}
معنا: فاصله سطح سنسور تا سطح آب = dist_mm (میلی‌متر)
مبنا: datum_mm = ارتفاع سطح سنسور بالای مبنای هیدروگرافی (دستگاه می‌فرستد؛
      اگر نفرستد از مقدار قبلی ثبت‌شده استفاده می‌شود)
تراز آب = datum_mm − dist_mm
"""
import asyncio, json, logging, time

import config, db

log = logging.getLogger("water")

ALERT_COOLDOWN_H = 12.0   # حداکثر یک هشدار افت برای هر مشترک در این بازه


# ─────────────── دریافت بسته دستگاه ───────────────
def _process_packet(data: bytes):
    try:
        msg = json.loads(data.decode("utf-8", errors="ignore"))
        device_id = str(msg.get("id", "")).strip() or "STN-UNKNOWN"
        dist_mm = float(msg["dist_mm"])
        temp_c = msg.get("temp_c")
        temp_c = float(temp_c) if temp_c is not None else None
        datum_mm = msg.get("datum_mm")
        datum_mm = float(datum_mm) if datum_mm is not None else None
    except Exception as e:
        log.warning("بسته نامعتبر سنسور آب: %s", e)
        return None

    dev = db.get_water_device(device_id)
    # مبنای بسته مقدم است (دستگاه منبع حقیقت هندسه نصب است)؛ وگرنه مقدار ثبت‌شده
    if datum_mm is None:
        datum_mm = dev["datum_mm"] if dev else 0.0
    label = dev["label"] if dev else device_id

    level_mm = datum_mm - dist_mm
    db.upsert_water_device(device_id, label, datum_mm)
    db.insert_water_reading(device_id, level_mm, dist_mm, temp_c)
    return {"device_id": device_id, "label": label, "datum_mm": datum_mm,
            "level_mm": level_mm, "dist_mm": dist_mm, "temp_c": temp_c}


# ─────────────── هشدار افت آبخور ───────────────
async def _maybe_alert(app, reading):
    if app is None:   # حالت تست مستقل از تلگرام
        return
    drop = db.water_drop_24h(reading["device_id"])
    if drop < config.WATER_ALERT_DROP_24H_MM:
        return
    now = time.time()
    cooldown = ALERT_COOLDOWN_H * 3600
    txt = (
        f"⚠️ <b>هشدار افت تراز آب — {config.PORT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"ایستگاه: <b>{reading['label']}</b>\n"
        f"افت ۲۴ ساعت اخیر: <b>{drop:.0f} میلی‌متر</b>\n"
        f"(آستانه هشدار: {config.WATER_ALERT_DROP_24H_MM:.0f} میلی‌متر)\n\n"
        f"<i>برای برنامه‌ریزی لایروبی و آبخور شناورها بررسی کنید.</i>"
    )
    for row in db.water_subs():
        if now - (row["last_alert"] or 0) < cooldown:
            continue
        try:
            await app.bot.send_message(row["chat_id"], txt, parse_mode="HTML")
            db.water_mark_alert(row["chat_id"])
        except Exception as e:
            log.warning("هشدار آب به %s ارسال نشد: %s", row["chat_id"], e)


# ─────────────── گزارش وضعیت (خالص و قابل تست) ───────────────
def build_status_report() -> str:
    devs = db._exec("SELECT * FROM water_devices ORDER BY device_id", fetch=True)
    if not devs:
        return (
            "🌊 <b>پایش تراز آب — بندر نوشهر</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "هنوز هیچ ایستگاهی ثبت نشده است.\n\n"
            "<b>راه‌اندازی:</b>\n"
            "۱) سنسور (ESP32) را روشن کنید — خودش ثبت می‌شود\n"
            "۲) یا شبیه‌ساز: <code>python water_sim.py</code>\n\n"
            "<i>جزئیات کامل در docs/water_level_project.md</i>"
        )
    lines = ["🌊 <b>پایش تراز آب — بندر نوشهر</b>", "━━━━━━━━━━━━━━━━━━"]
    for dev in devs:
        did, label = dev["device_id"], dev["label"] or dev["device_id"]
        s = db.water_stats(did)
        if not s:
            lines.append(f"📍 <b>{label}</b> — ثبت‌شده ولی داده‌ای در ۲۴ ساعت ندارد")
            continue
        age_min = (time.time() - s["last_seen"]) / 60.0
        live = "🟢 زنده" if age_min < 30 else ("🟡 کند" if age_min < 24 * 60 else "🔴 قطع")
        trend = ("📈 بالا" if s["change_24h"] > 5 else
                 "📉 افت" if s["change_24h"] < -5 else "➖ ثابت")
        temp = f"{s['temp']:.1f}°C" if s["temp"] is not None else "—"
        drop = db.water_drop_24h(did)
        warn = ("⚠️ افت بیش از آستانه!" if drop >= config.WATER_ALERT_DROP_24H_MM
                else "✅ عادی")
        lines.append(
            f"📍 <b>{label}</b> {live}\n"
            f"📏 تراز فعلی: <b>{s['current']:+.0f} mm</b> نسبت به مبنا ایستگاه\n"
            f"📊 ۲۴ ساعت: بیشینه {s['max']:+.0f} | کمینه {s['min']:+.0f} | "
            f"تغییر {s['change_24h']:+.0f} mm → {trend}\n"
            f"🌡 دما: {temp} | 📥 {s['count']} نمونه | آخرین داده {age_min:.0f} دقیقه پیش\n"
            f"وضعیت آبخور: {warn}\n"
        )
    lines.append("<i>تراز «نسبی» به مبنای هر ایستگاه است؛ اتصال به مبنای رسمی "
                 "هیدروگرافی با نقشه‌برداریbenchmark انجام می‌شود (سند پروژه).</i>")
    return "\n".join(lines)


# ─────────────── حلقه UDP ───────────────
async def _udp_loop(port: int, app):
    loop = asyncio.get_running_loop()

    class Proto(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            try:
                reading = _process_packet(data)
                if reading:
                    asyncio.create_task(_maybe_alert(app, reading))
            except Exception:
                log.exception("خطا در پردازش بسته آب")

    try:
        await loop.create_datagram_endpoint(Proto, local_addr=("0.0.0.0", port))
        log.info("پایش تراز آب روی UDP پورت %s فعال است ✔", port)
    except OSError as e:
        log.error("باز کردن UDP %s ناموفق: %s", port, e)


def start(app):
    """تسک پس‌زمینه پایش آب — همیشه فعال (حتی قبل از رسیدن سخت‌افزار)"""
    return asyncio.create_task(_udp_loop(config.WATER_UDP_PORT, app))
