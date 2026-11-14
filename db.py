# -*- coding: utf-8 -*-
"""پایگاه داده سبک SQLite — کاربران، اطلاعیه‌ها، اشتراک هشدار، کش شناورها"""
import sqlite3, threading, time, os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "noshahr_bot.db")
_lock = threading.Lock()
_conn = None


def init_db() -> None:
    global _conn
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _cur = _conn.cursor()
    _cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            chat_id INTEGER PRIMARY KEY,
            role TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            wave_alert INTEGER DEFAULT 0,             -- 0/1 فعال بودن هشدار موج
            wave_threshold REAL DEFAULT 1.5,          -- آستانه موج (متر)
            ais_alert INTEGER DEFAULT 0,              -- هشدار ورود شناور به محدوده
            last_wave_alert REAL DEFAULT 0,           -- زمان آخرین هشدار ارسال‌شده
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS announcements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT,
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS vessels(
            mmsi INTEGER PRIMARY KEY,
            name TEXT DEFAULT '',
            lat REAL, lon REAL,
            sog REAL, cog REAL,
            dist_km REAL,
            in_zone INTEGER DEFAULT 0,
            first_seen REAL, last_seen REAL
        );
        CREATE TABLE IF NOT EXISTS water_levels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT,
            level_mm REAL,          -- تراز آب نسبت به مبنا ایستگاه (میلی‌متر)
            raw_dist_mm REAL,       -- فاصله خام سنسور تا سطح آب
            temp_c REAL,            -- دمای هوا برای تصحیح سرعت صوت
            ts REAL
        );
        CREATE INDEX IF NOT EXISTS idx_water_dev_ts ON water_levels(device_id, ts);
        CREATE TABLE IF NOT EXISTS water_devices(
            device_id TEXT PRIMARY KEY,
            label TEXT DEFAULT '',
            datum_mm REAL DEFAULT 0,   -- ارتفاع سطح سنسور بالای مبنای هیدروگرافی (mm)
            last_seen REAL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS water_alerts(
            chat_id INTEGER PRIMARY KEY,
            last_alert REAL DEFAULT 0
        );
        """
    )
    _conn.commit()


def _exec(sql, args=(), fetch=False):
    with _lock:
        cur = _conn.execute(sql, args)
        _conn.commit()
        if fetch:
            return cur.fetchall()
        return None


# ─────────────── کاربران ───────────────
def upsert_user(chat_id: int, first_name="", username=""):
    _exec(
        "INSERT INTO users(chat_id, first_name, username, created_at) VALUES(?,?,?,?) "
        "ON CONFLICT(chat_id) DO UPDATE SET first_name=?, username=?",
        (chat_id, first_name, username, time.time(), first_name, username),
    )


def get_user(chat_id: int):
    rows = _exec("SELECT * FROM users WHERE chat_id=?", (chat_id,), fetch=True)
    return rows[0] if rows else None


def set_role(chat_id: int, role: str):
    _exec("UPDATE users SET role=? WHERE chat_id=?", (role, chat_id))


def set_wave_alert(chat_id: int, on: bool, threshold: float):
    _exec("UPDATE users SET wave_alert=?, wave_threshold=? WHERE chat_id=?",
          (1 if on else 0, threshold, chat_id))


def set_ais_alert(chat_id: int, on: bool):
    _exec("UPDATE users SET ais_alert=? WHERE chat_id=?", (1 if on else 0, chat_id))


def mark_wave_alert(chat_id: int):
    _exec("UPDATE users SET last_wave_alert=? WHERE chat_id=?", (time.time(), chat_id))


def wave_subscribers():
    return _exec("SELECT chat_id, wave_threshold, last_wave_alert FROM users WHERE wave_alert=1", fetch=True)


def ais_subscribers():
    return _exec("SELECT chat_id FROM users WHERE ais_alert=1", fetch=True)


def all_user_ids():
    return [r["chat_id"] for r in _exec("SELECT chat_id FROM users", fetch=True)]


# ─────────────── اطلاعیه‌ها ───────────────
def add_announcement(text: str):
    _exec("INSERT INTO announcements(text, created_at) VALUES(?,?)", (text, time.time()))


def get_announcements(limit: int = 5):
    return _exec("SELECT * FROM announcements ORDER BY id DESC LIMIT ?", (limit,), fetch=True)


def delete_last_announcement():
    _exec("DELETE FROM announcements WHERE id=(SELECT MAX(id) FROM announcements)")


# ─────────────── شناورها (کش/آمار) ───────────────
def upsert_vessel(mmsi, name, lat, lon, sog, cog, dist_km, in_zone):
    _exec(
        """INSERT INTO vessels(mmsi,name,lat,lon,sog,cog,dist_km,in_zone,first_seen,last_seen)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(mmsi) DO UPDATE SET
             name=excluded.name, lat=excluded.lat, lon=excluded.lon,
             sog=excluded.sog, cog=excluded.cog, dist_km=excluded.dist_km,
             in_zone=excluded.in_zone,
             last_seen=excluded.last_seen""",
        (mmsi, name, lat, lon, sog, cog, dist_km, 1 if in_zone else 0, time.time(), time.time()),
    )


def get_vessel(mmsi):
    rows = _exec("SELECT * FROM vessels WHERE mmsi=?", (mmsi,), fetch=True)
    return rows[0] if rows else None


def count_vessels_last_hours(hours: int = 24):
    since = time.time() - hours * 3600
    rows = _exec("SELECT COUNT(*) c FROM vessels WHERE last_seen>=?", (since,), fetch=True)
    return rows[0]["c"] if rows else 0


def count_vessels_in_zone():
    rows = _exec("SELECT COUNT(*) c FROM vessels WHERE in_zone=1", fetch=True)
    return rows[0]["c"] if rows else 0


def top_recent_vessels(limit: int = 15):
    return _exec(
        "SELECT name,mmsi,dist_km,sog,in_zone,last_seen FROM vessels "
        "ORDER BY last_seen DESC LIMIT ?", (limit,), fetch=True)


# ─────────────── پایش تراز آب ───────────────
def upsert_water_device(device_id: str, label: str = "", datum_mm: float = 0.0):
    _exec(
        "INSERT INTO water_devices(device_id,label,datum_mm,last_seen) VALUES(?,?,?,?) "
        "ON CONFLICT(device_id) DO UPDATE SET label=?, datum_mm=?, last_seen=?",
        (device_id, label, datum_mm, time.time(), label, datum_mm, time.time()),
    )


def get_water_device(device_id: str):
    rows = _exec("SELECT * FROM water_devices WHERE device_id=?", (device_id,), fetch=True)
    return rows[0] if rows else None


def insert_water_reading(device_id: str, level_mm: float, raw_dist_mm: float, temp_c):
    _exec(
        "INSERT INTO water_levels(device_id,level_mm,raw_dist_mm,temp_c,ts) VALUES(?,?,?,?,?)",
        (device_id, level_mm, raw_dist_mm, temp_c, time.time()),
    )


def water_stats(device_id: str):
    """آمار ۲۴ ساعت اخیر یک ایستگاه: فعلی، بیشینه، کمینه، تغییر، تعداد نمونه"""
    since = time.time() - 24 * 3600
    rows = _exec(
        "SELECT level_mm, temp_c, ts FROM water_levels "
        "WHERE device_id=? AND ts>=? ORDER BY ts ASC", (device_id, since), fetch=True)
    if not rows:
        return None
    levels = [r["level_mm"] for r in rows]
    first, last = rows[0], rows[-1]
    return {
        "current": last["level_mm"],
        "temp": last["temp_c"],
        "min": min(levels),
        "max": max(levels),
        "change_24h": last["level_mm"] - first["level_mm"],
        "count": len(rows),
        "last_seen": last["ts"],
        "span_hours": (last["ts"] - first["ts"]) / 3600.0 or 0.0,
    }


def water_drop_24h(device_id: str) -> float:
    s = water_stats(device_id)
    return -s["change_24h"] if s else 0.0   # مثبت = افت


# ── مشترکین هشدار آبخور ──
def water_subscribe(chat_id: int, on: bool):
    if on:
        _exec("INSERT INTO water_alerts(chat_id,last_alert) VALUES(?,0) "
              "ON CONFLICT(chat_id) DO NOTHING", (chat_id,))
    else:
        _exec("DELETE FROM water_alerts WHERE chat_id=?", (chat_id,))


def water_is_subscribed(chat_id: int) -> bool:
    rows = _exec("SELECT chat_id FROM water_alerts WHERE chat_id=?", (chat_id,), fetch=True)
    return bool(rows)


def water_subs():
    return _exec("SELECT chat_id, last_alert FROM water_alerts", fetch=True)


def water_mark_alert(chat_id: int):
    _exec("UPDATE water_alerts SET last_alert=? WHERE chat_id=?", (time.time(), chat_id))
