# -*- coding: utf-8 -*-
"""
دیده‌بان شناورها با داده AIS عمومی از aisstream.io (رایگان)
اگر AIS_API_KEY تنظیم نشده باشد، این ماژول غیرفعال می‌ماند و بقیه ربات کار می‌کند.
"""
import asyncio, json, logging, math, time
import websockets
import config
import db
import nmea

log = logging.getLogger("ais")

# کش در حافظه: mmsi -> dict(name, lat, lon, sog, cog, dist_km, in_zone, ts)
CACHE: dict = {}
# نام شناورها (از پیام‌های استاتیک 5/24 گیرنده محلی — جدا از پیام‌های موقعیت می‌آیند)
NAMES: dict = {}
# نوع شناور و مقصد (از پیام‌های استاتیک 5/24 گیرنده محلی)
SHIP_TYPES: dict = {}
DESTINATIONS: dict = {}
# callback برای رویداد ورود شناور به محدوده بندر: def on_enter(name, mmsi, dist_km)
_on_zone_enter = None


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def set_zone_enter_callback(cb):
    global _on_zone_enter
    _on_zone_enter = cb


def enabled() -> bool:
    return bool(config.AIS_API_KEY)


def cleanup():
    now = time.time()
    for mmsi in list(CACHE.keys()):
        if now - CACHE[mmsi]["ts"] > config.AIS_TTL_SEC:
            CACHE.pop(mmsi, None)


def vessels_sorted(limit=15):
    """لیست شناورهای اخیر مرتب بر اساس فاصله از بندر"""
    cleanup()
    items = sorted(CACHE.values(), key=lambda v: v["dist_km"])
    return items[:limit]


def _handle_position(mmsi, name, lat, lon, sog, cog,
                     type_label=None, destination=None):
    dist = haversine_km(lat, lon, config.PORT_LAT, config.PORT_LON)
    in_zone = dist <= config.ZONE_RADIUS_KM
    prev = CACHE.get(mmsi)
    was_in = prev["in_zone"] if prev else False

    # نوع/مقصد: مقدار جدید، یا آخرین مقدار شناخته‌شده این شناور
    vtype = type_label or SHIP_TYPES.get(mmsi) or (prev or {}).get("type")
    vdest = destination or DESTINATIONS.get(mmsi) or (prev or {}).get("dest")

    CACHE[mmsi] = {"name": name, "lat": lat, "lon": lon, "sog": sog, "cog": cog,
                   "dist_km": dist, "in_zone": in_zone, "ts": time.time(),
                   "type": vtype, "dest": vdest}
    try:
        db.upsert_vessel(mmsi, name, lat, lon, sog, cog, dist, in_zone)
    except Exception:
        pass

    # رویداد: ورود جدید به محدوده بندر → هشدار مشترکین
    if in_zone and not was_in and _on_zone_enter:
        try:
            _on_zone_enter(name or f"MMSI {mmsi}", mmsi, dist)
        except Exception:
            log.exception("zone-enter callback failed")


async def _loop():
    url = "wss://stream.aisstream.io/v0/stream"
    while True:
        try:
            # ping_timeout بلندتر برای تحمل نوسان شبکه
            async with websockets.connect(url, max_size=2**22,
                                          ping_interval=20, ping_timeout=60) as ws:
                sub = {
                    "APIKey": config.AIS_API_KEY,
                    "BoundingBoxes": config.AIS_BBOX,
                    "FilterMessageTypes": ["PositionReport", "StandardClassBPositionReport"],
                }
                await ws.send(json.dumps(sub))
                log.info("AIS stream connected ✔")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    meta = msg.get("Meta", {})
                    mmsi = meta.get("MMSI")
                    name = (meta.get("ShipName") or "").strip()
                    body = msg.get("Message", {})

                    pr = body.get("PositionReport") or body.get("StandardClassBPositionReport")
                    if pr and mmsi:
                        _handle_position(
                            int(mmsi), name,
                            float(pr.get("Latitude", 0) or 0),
                            float(pr.get("Longitude", 0) or 0),
                            float(pr.get("Sog", 0) or 0),
                            float(pr.get("Cog", 0) or 0),
                        )
        except Exception as e:
            log.warning("AIS stream error: %s — retry in 20s", e)
            await asyncio.sleep(20)


async def _udp_loop(port: int):
    """دریافت جملات NMEA از گیرنده محلی (rtl-ais روی UDP می‌فرستد)"""
    loop = asyncio.get_running_loop()

    def _process(data: bytes):
        text = data.decode("ascii", errors="ignore")
        for line in text.splitlines():
            parsed = nmea.parse_aivdm(line)
            if not parsed:
                continue
            mmsi = parsed["mmsi"]
            type_label = dest = None
            if parsed["name"]:
                NAMES[mmsi] = parsed["name"]
            if parsed.get("ship_type") is not None:
                type_label = nmea.ship_type_fa(parsed["ship_type"])
                if type_label:
                    SHIP_TYPES[mmsi] = type_label
            if parsed.get("destination"):
                DESTINATIONS[mmsi] = parsed["destination"]
                dest = parsed["destination"]
            if parsed["lat"] is not None and parsed["lon"] is not None:
                _handle_position(mmsi, parsed.get("name") or NAMES.get(mmsi, ""),
                                 parsed["lat"], parsed["lon"],
                                 parsed["sog"], parsed["cog"],
                                 type_label=type_label, destination=dest)

    class Proto(asyncio.DatagramProtocol):
        def connection_made(self, transport):
            self.transport = transport

        def datagram_received(self, data, addr):
            _process(data)

    try:
        await loop.create_datagram_endpoint(
            Proto, local_addr=("0.0.0.0", port))
        log.info("فید محلی NMEA روی UDP پورت %s فعال است ✔", port)
    except OSError as e:
        log.error("باز کردن UDP %s ناموفق بود: %s", port, e)


def start():
    """راه‌اندازی منابع AIS: فید گیرنده محلی (همیشه) + استریم جهانی (اگر کلید باشد)"""
    tasks = [asyncio.create_task(_udp_loop(config.NMEA_UDP_PORT))]
    if enabled():
        tasks.append(asyncio.create_task(_loop()))
    else:
        log.warning("AIS_API_KEY تنظیم نشده — فقط فید گیرنده محلی (UDP %s) فعال است.",
                    config.NMEA_UDP_PORT)
    return tasks
