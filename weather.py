# -*- coding: utf-8 -*-
"""داده‌های هواشناسی و دریا از Open-Meteo (رایگان، بدون کلید API)"""
import httpx
import config

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

TIMEOUT = httpx.Timeout(15.0)


# ─────────────── کدهای وضعیت هوا → فارسی ───────────────
def weather_code_fa(code: int) -> str:
    m = {
        0: "☀️ آفتابی", 1: "🌤 غالباً آفتابی", 2: "⛅ ابری جزئی", 3: "☁️ ابری",
        45: "🌫 مه", 48: "🌫 مه یخ‌زده",
        51: "🌦 نم‌نم سبک", 53: "🌦 نم‌نم", 55: "🌦 نم‌نم شدید",
        61: "🌧 باران سبک", 63: "🌧 باران", 65: "🌧 باران شدید",
        71: "🌨 برف سبک", 73: "🌨 برف", 75: "🌨 برف سنگین",
        80: "🌧 رگبار پراکنده", 81: "🌧 رگبار", 82: "⛈ رگبار شدید",
        95: "⛈ رعدوبرق", 96: "⛈ رعدوبرق با تگرگ", 99: "⛈ رعدوبرق شدید",
    }
    return m.get(code, f"❓ کد {code}")


async def _get(url: str, params: dict):
    async with httpx.AsyncClient(timeout=TIMEOUT) as cl:
        r = await cl.get(url, params=params)
        r.raise_for_status()
        return r.json()


async def _sst() -> "float | None":
    """دمای سطح آب دریای خزر — از marine API، و اگر null بود از forecast (ساعتی)"""
    try:
        m = await _get(MARINE_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "current": "sea_surface_temperature", "timezone": "auto",
        })
        v = m.get("current", {}).get("sea_surface_temperature")
        if v is not None:
            return float(v)
    except Exception:
        pass
    try:
        f = await _get(FORECAST_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "hourly": "sea_surface_temperature", "current": "is_day",
            "timezone": "auto", "forecast_days": 2,
        })
        cur_hour = (f.get("current", {}) or {}).get("time", "")[:13]  # YYYY-MM-DDTHH
        for i, t in enumerate(f.get("hourly", {}).get("time", [])):
            if t[:13] == cur_hour:
                v = f["hourly"]["sea_surface_temperature"][i]
                return float(v) if v is not None else None
    except Exception:
        pass
    return None


# ─────────────── وضعیت دریا الان ───────────────
async def get_sea_now() -> str:
    try:
        m = await _get(MARINE_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "current": "wave_height",
            "timezone": "Asia/Tehran",
        })
        cur = m.get("current", {})
        wave = cur.get("wave_height")
    except Exception:
        wave = None
    sst = await _sst()

    try:
        w = await _get(FORECAST_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "current": "temperature_2m,wind_speed_10m,wind_direction_10m,weather_code",
            "wind_speed_unit": "kn", "timezone": "Asia/Tehran",
        })
        cw = w.get("current", {})
        temp, wind, wdir, code = (cw.get("temperature_2m"), cw.get("wind_speed_10m"),
                                  cw.get("wind_direction_10m"), cw.get("weather_code"))
    except Exception:
        temp = wind = wdir = code = None

    def f(v, unit, nd=1):
        return f"{v:.{nd}f} {unit}" if v is not None else "ناموجود"

    status = ("⚠️ شرایط دریایی نامساعد — احتیاط کنید" if (wave or 0) >= 1.3
              else "✅ شرایط عمومی قابل قبول")
    txt = (
        f"🌊 <b>وضعیت دریا و هوا — {config.PORT_NAME} (الان)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌊 ارتفاع موج: <b>{f(wave, 'm')}</b>\n"
        f"🌡 دمای آب: <b>{f(sst, '°C')}</b>\n"
        f"🌡 دمای هوا: <b>{f(temp, '°C')}</b>\n"
        f"💨 باد: <b>{f(wind, 'kn')}</b>\n"
        f"🧭 جهت باد: <b>{f(wdir, '°', 0)}</b>\n"
        f"{status}\n\n"
        f"<i>منبع: Open-Meteo — پیش‌بینی است؛ برای تصمیم نهایی به اعلان‌های رسمی بندر مراجعه کنید.</i>"
    )
    return txt


# ─────────────── پیش‌بینی ۴۸ ساعته (هر ۳ ساعت) ───────────────
async def get_forecast_48() -> str:
    try:
        m = await _get(MARINE_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "hourly": "wave_height", "timezone": "Asia/Tehran",
            "forecast_days": 2,
        })
        w = await _get(FORECAST_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "hourly": "wind_speed_10m,weather_code",
            "wind_speed_unit": "kn", "timezone": "Asia/Tehran", "forecast_days": 2,
        })
    except Exception:
        return "❌ دریافت پیش‌بینی ناموفق بود. کمی بعد دوباره تلاش کنید."

    times = w["hourly"]["time"]
    winds = w["hourly"]["wind_speed_10m"]
    codes = w["hourly"]["weather_code"]
    waves = m["hourly"]["wave_height"]

    lines = ["🗓 <b>پیش‌بینی ۴۸ ساعته دریا و هوا</b>", "━━━━━━━━━━━━━━━━━━"]
    for i in range(0, min(len(times), 48), 3):
        t = times[i][5:].replace("T", " ")
        wv = waves[i] if i < len(waves) else None
        wd = winds[i] if i < len(winds) else None
        icon = "🟢" if (wv or 0) < 0.8 and (wd or 0) < 15 else ("🟡" if (wv or 0) < 1.3 else "🔴")
        lines.append(
            f"{icon} <b>{t}</b> | موج {f'{wv:.1f}m' if wv is not None else '-'} | "
            f"باد {f'{wd:.0f}kn' if wd is not None else '-'} | {weather_code_fa(codes[i])}"
        )
    lines.append("\n🟢 مناسب عملیات | 🟡 احتیاط | 🔴 نامناسب")
    return "\n".join(lines)


# ─────────────── هوای مسیر تهران → نوشهر ───────────────
async def get_route_weather() -> str:
    lines = ["🚚 <b>هوای مسیر تهران ← نوشهر</b>", "━━━━━━━━━━━━━━━━━━"]
    async with httpx.AsyncClient(timeout=TIMEOUT) as cl:
        for name, lat, lon in config.ROUTE_POINTS:
            try:
                r = await cl.get(FORECAST_URL, params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,wind_speed_10m,weather_code",
                    "timezone": "Asia/Tehran",
                })
                c = r.json().get("current", {})
                lines.append(
                    f"📍 <b>{name}</b>\n"
                    f"   {weather_code_fa(c.get('weather_code'))} | "
                    f"{c.get('temperature_2m')}°C | باد {c.get('wind_speed_10m')} km/h\n"
                )
            except Exception:
                lines.append(f"📍 <b>{name}</b> — ناموفق\n")
    return "\n".join(lines)


# ─────────────── پنجره هوایی عملیات بندری (۱۲ ساعت) ───────────────
async def get_operation_window() -> str:
    try:
        m = await _get(MARINE_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "hourly": "wave_height", "timezone": "Asia/Tehran", "forecast_days": 1,
        })
        w = await _get(FORECAST_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "hourly": "wind_speed_10m", "wind_speed_unit": "kn",
            "timezone": "Asia/Tehran", "forecast_days": 1,
        })
    except Exception:
        return "❌ دریافت داده ناموفق بود."

    times, waves, winds = w["hourly"]["time"], m["hourly"]["wave_height"], w["hourly"]["wind_speed_10m"]
    lines = ["🛟 <b>پنجره هوایی عملیات تخلیه/بارگیری (۱۲ ساعت)</b>", "━━━━━━━━━━━━━━━━━━"]
    good = warn = bad = 0
    for i in range(0, min(12, len(times))):
        wv, wd = waves[i], winds[i]
        if wv < 0.8 and wd < 15:
            st, good = "✅ مناسب", good + 1
        elif wv < 1.3 and wd < 22:
            st, warn = "🟡 مشروط", warn + 1
        else:
            st, bad = "🔴 تعلیق پیشنهادی", bad + 1
        lines.append(f"• <b>{times[i][11:16]}</b> — موج {wv:.1f}m، باد {wd:.0f}kn → {st}")
    lines.append(
        f"\n📊 جمع‌بندی: {good} ساعت مناسب | {warn} مشروط | {bad} نامناسب\n"
        "<i>آستانه‌ها: مناسب&lt;0.8m/15kn — تعلیق&gt;1.3m/22kn (قابل تنظیم در کد)</i>"
    )
    return "\n".join(lines)


# ─────────────── ایمنی قایق کوچک (صیادان) ───────────────
async def get_boat_safety() -> str:
    try:
        m = await _get(MARINE_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "current": "wave_height", "timezone": "Asia/Tehran",
        })
        w = await _get(FORECAST_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "current": "wind_speed_10m", "wind_speed_unit": "kn", "timezone": "Asia/Tehran",
        })
        cur, cw = m.get("current", {}), w.get("current", {})
        wave, wind = cur.get("wave_height"), cw.get("wind_speed_10m")
        sst = await _sst()
    except Exception:
        return "❌ دریافت داده ناموفق بود."

    if wave < 0.5 and wind < 12:
        status, advice = "🟢 ایمن", "خروج قایق کوچک: بدون محدودیت خاص (احتیابات معمول)"
    elif wave < 0.8 and wind < 18:
        status, advice = "🟡 احتیاط", "فقط با تجربه کافی و جلیق نجات؛ از فاصله ایمن از موج‌شکن"
    else:
        status, advice = "🔴 خطرناک", "خروج از قایق کوچک توصیه نمی‌شود"

    sst_txt = f"{sst:.1f}°C" if sst is not None else "ناموجود"
    return (
        f"🎣 <b>وضعیت ایمنی قایق‌های کوچک — {config.PORT_NAME}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"وضعیت کلی: <b>{status}</b>\n"
        f"🌊 موج: {wave:.1f}m | 💨 باد: {wind:.0f}kn | 🌡 دمای آب: {sst_txt}\n"
        f"━━━━━━━━━━━━━━━━━━\n{advice}\n\n"
        f"<i>توصیه: همیشه پیش از خروج، اعلان‌های رسمی و دید افقی را هم چک کنید.</i>"
    )


# ─────────────── اطلاعات ساحل (گردشگر) ───────────────
async def get_beach_info() -> str:
    try:
        w = await _get(FORECAST_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "daily": "sunrise,sunset,temperature_2m_max,temperature_2m_min",
            "timezone": "Asia/Tehran", "forecast_days": 1,
        })
        m = await _get(MARINE_URL, {
            "latitude": config.PORT_LAT, "longitude": config.PORT_LON,
            "current": "wave_height", "timezone": "Asia/Tehran",
        })
    except Exception:
        return "❌ دریافت داده ناموفق بود."

    cur, d, mc = w.get("current", {}), w.get("daily", {}), m.get("current", {})
    sst = await _sst()
    wave = mc.get("wave_height")
    swim = ("🟢 مناسب شنا (با احتیاط معمول)" if (wave or 0) < 0.6
            else "🟡 با احتیاط — موج دارد" if (wave or 0) < 1.0
            else "🔴 شنا توصیه نمی‌شود")
    return (
        f"🏖 <b>اطلاعات ساحل نوشهر</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{weather_code_fa(cur.get('weather_code'))} | 🌡 هوا {cur.get('temperature_2m')}°C\n"
        f"🌡 دمای آب: {f'{sst:.1f}°C' if sst is not None else 'ناموجود'}\n"
        f"🌊 موج: {f'{wave:.1f}m' if wave is not None else 'ناموجود'}\n"
        f"💨 باد: {cur.get('wind_speed_10m')} km/h\n"
        f"🌅 طلوع: {d.get('sunrise', ['—'])[0][11:16]}\n"
        f"🌇 غروب: {d.get('sunset', ['—'])[0][11:16]}\n"
        f"🌡 امروز: {d.get('temperature_2m_min', ['—'])[0]} تا {d.get('temperature_2m_max', ['—'])[0]}°C\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"حالت شنا: <b>{swim}</b>\n\n"
        f"<i>ساحل نوشهر خزر است؛ جزر و مد معنادار ندارد اما جریان ساحلی و باد را جدی بگیرید.</i>"
    )
