# -*- coding: utf-8 -*-
"""
پارس جملات NMEA AIVDM/AIVDO — داده AIS از گیرنده محلی (RTL-SDR با rtl-ais)
این ماژول بدون وابستگی خارجی است و پیام‌های موقعیت (1/2/3/18) و نام کشتی (5/24) را می‌خواند.
"""
import logging

log = logging.getLogger("nmea")


def checksum_ok(body: str, given: str) -> bool:
    """بررسی چک‌سام NMEA — XOR همه کاراکترهای بین ! و *"""
    if not given:
        return True
    c = 0
    for ch in body:
        c ^= ord(ch)
    return f"{c:02X}" == given.upper()


def _decode_payload(sixbit: str, fill: int = 0):
    """رمزگشایی لایه انتقال 6-bit AIS به رشته بیت‌ها"""
    bits = []
    for ch in sixbit:
        v = ord(ch) - 48
        if v > 40:
            v -= 8
        if 0 <= v <= 63:
            bits.extend((v >> i) & 1 for i in range(5, -1, -1))
        else:
            log.debug("کاراکتر نامعتبر AIS: %r", ch)
    if fill:
        bits = bits[:len(bits) - fill]
    return bits


def _u(bits, start, end) -> int:
    v = 0
    for b in bits[start:end]:
        v = (v << 1) | b
    return v


def _s(bits, start, end) -> int:
    v = _u(bits, start, end)
    if bits[start]:
        v -= 1 << (end - start)
    return v


def _text(bits, start, end) -> str:
    """متن AIS (جدول ITU): 0='@' پدینگ، 1-26=A-Z، 32+=کاراکتر خودش"""
    out = []
    for i in range(start, min(end, len(bits) - 5), 6):
        v = _u(bits, i, i + 6)
        if v == 0:
            break
        out.append(chr(v + 64) if v < 32 else chr(v))
    return "".join(out).strip()


def parse_aivdm(sentence: str):
    """
    یک جمله NMEA را پارس می‌کند.
    خروجی: dict(type, mmsi, lat, lon, sog, cog, name) یا None
    """
    sentence = sentence.strip()
    if not sentence.startswith("!"):
        return None
    body, _, chk = sentence.rpartition("*")
    if len(body) < 10:
        return None
    if not checksum_ok(body[1:], chk):
        log.debug("چک‌سام نامعتبر: %s", sentence)
        return None

    fields = body.split(",")
    if len(fields) < 6 or not fields[0][1:].startswith("AI"):
        return None
    payload = fields[5]
    fill = int(fields[6]) if len(fields) > 6 and fields[6].isdigit() else 0
    bits = _decode_payload(payload, fill)
    if len(bits) < 38:
        return None

    mtype = _u(bits, 0, 6)
    mmsi = _u(bits, 8, 38)
    out = {"type": mtype, "mmsi": mmsi, "lat": None, "lon": None,
           "sog": None, "cog": None, "name": None}

    # پیام‌های موقعیت شناور کلاس A (1/2/3)
    if mtype in (1, 2, 3) and len(bits) >= 128:
        sog = _u(bits, 50, 60)
        lon = _s(bits, 61, 89) / 600000.0
        lat = _s(bits, 89, 116) / 600000.0
        cog = _u(bits, 116, 128)
        if lon != 181.0:
            out["lon"] = lon
        if lat != 91.0:
            out["lat"] = lat
        if sog != 1023:
            out["sog"] = sog / 10.0
        if cog != 3600:
            out["cog"] = cog / 10.0

    # پیام موقعیت کلاس B (18)
    elif mtype == 18 and len(bits) >= 124:
        sog = _u(bits, 46, 56)
        lon = _s(bits, 57, 85) / 600000.0
        lat = _s(bits, 85, 112) / 600000.0
        cog = _u(bits, 112, 124)
        if lon != 181.0:
            out["lon"] = lon
        if lat != 91.0:
            out["lat"] = lat
        if sog != 1023:
            out["sog"] = sog / 10.0
        if cog != 3600:
            out["cog"] = cog / 10.0

    # داده استاتیک کلاس A (5) — نام، نوع شناور، آبخور، مقصد
    elif mtype == 5 and len(bits) >= 240:
        out["name"] = _text(bits, 112, 232)
        out["ship_type"] = _u(bits, 232, 240)
        if len(bits) >= 425:
            d = _u(bits, 295, 305)
            out["draught"] = d / 10.0 if d else None
            out["destination"] = _text(bits, 305, 425) or None

    # کلاس B استاتیک (24) — بخش A: نام / بخش B: نوع
    elif mtype == 24 and len(bits) >= 160:
        part = _u(bits, 38, 40)
        if part == 0:
            out["name"] = _text(bits, 40, 160)
        elif part == 1 and len(bits) >= 48:
            out["ship_type"] = _u(bits, 40, 48)

    return out


# ─────────────── برچسب فارسی نوع شناور (کدهای استاندارد AIS) ───────────────
def ship_type_fa(code):
    if code is None:
        return None
    if code == 30:
        return "🎣 صیادی"
    if code in (31, 32, 33):
        return "⚙️ یدک‌کش"
    if code == 34:
        return "🏗 لایروب"
    if code == 35:
        return "🪖 نظامی"
    if code == 36:
        return "⛵ تفریحی"
    if 40 <= code <= 49:
        return "⛴ تندرو"
    if code == 50:
        return "🧭 پایلوت"
    if code in (51, 52):
        return "🚨 امداد و نجات"
    if code in (53, 54, 56, 57):
        return "🛥 امنیتی / گارد ساحلی"
    if code in (55, 58):
        return "⚙️ خدمات ویژه"
    if 60 <= code <= 69:
        return "🛳 مسافری"
    if 70 <= code <= 79:
        return "📦 باری"
    if 80 <= code <= 89:
        return "🛢 تانکر"
    if 90 <= code <= 99:
        return "🚢 دیگر"
    return None


# ─────────────── ابزار تست: ساخت جمله AIVDM از بیت‌ها (round-trip) ───────────────
def _encode_bits(bits):
    """بیت‌ها → رشته 6-bit ASCII برای ساخت جمله تستی
    مقادیر 0-39 → کاراکترهای 48-87 ('0'-'W') و مقادیر 40-63 → 96-119 ('`'-'w')"""
    while len(bits) % 6:
        bits.append(0)
    out = []
    for i in range(0, len(bits), 6):
        v = 0
        for b in bits[i:i + 6]:
            v = (v << 1) | b
        out.append(chr(v + 48) if v < 40 else chr(v + 56))
    return "".join(out)


def build_aivdm(payload_bits, channel="A"):
    """بیت‌های پیام AIS → جمله کامل AIVDM با چک‌سام (مخصوص تست)"""
    payload = _encode_bits(list(payload_bits))
    body = f"AIVDM,1,1,,{channel},{payload},0"
    c = 0
    for ch in body:
        c ^= ord(ch)
    return f"!{body}*{c:02X}"


def _pack(vals):
    """[ (value, nbits), ... ] → لیست بیت"""
    bits = []
    for v, n in vals:
        bits.extend((v >> i) & 1 for i in range(n - 1, -1, -1))
    return bits


def build_position_message(mtype, mmsi, lat_deg, lon_deg, sog_kn, cog_deg):
    """ساخت بیت‌های پیام موقعیت 1/3 یا 18 برای تست"""
    if mtype in (1, 2, 3):
        return _pack([
            (mtype, 6), (0, 2), (mmsi, 30), (0, 4), (0, 8),
            (int(sog_kn * 10), 10), (0, 1),
            (int(lon_deg * 600000) & 0x0FFFFFFF, 28),
            (int(lat_deg * 600000) & 0x07FFFFFF, 27),
            (int(cog_deg * 10), 12),
        ])
    return _pack([
        (18, 6), (0, 2), (mmsi, 30), (0, 8),
        (int(sog_kn * 10), 10), (0, 1),
        (int(lon_deg * 600000) & 0x0FFFFFFF, 28),
        (int(lat_deg * 600000) & 0x07FFFFFF, 27),
        (int(cog_deg * 10), 12),
    ])


def _text_to_bits(text, nbits):
    """متن → بیت‌ها بر اساس جدول معکوس ITU (برای ساخت پیام تستی)"""
    bits = []
    for ch in text[:nbits // 6]:
        o = ord(ch)
        v = (o - 64) if 64 <= o <= 95 else (o if 32 <= o <= 63 else 0)
        bits.extend((v >> i) & 1 for i in range(5, -1, -1))
    while len(bits) < nbits:
        bits.append(0)  # پدینگ '@'
    return bits


def build_static_message(mmsi, name, ship_type, destination, draught_m):
    """بیت‌های پیام استاتیک نوع 5 (نام/نوع/آبخور/مقصد) — مخصوص تست"""
    return (_pack([(5, 6), (0, 2), (mmsi, 30), (1, 2), (0, 30)])
            + _text_to_bits("IRNOS1", 42)
            + _text_to_bits(name, 120)
            + _pack([(ship_type, 8), (0, 9), (0, 9), (0, 6), (0, 7),
                     (0, 4), (0, 4), (0, 5), (0, 5), (0, 6),
                     (int(draught_m * 10), 10)])
            + _text_to_bits(destination, 120))
