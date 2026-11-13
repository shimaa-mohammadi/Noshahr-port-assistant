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
