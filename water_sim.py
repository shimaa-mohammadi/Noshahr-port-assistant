# -*- coding: utf-8 -*-
"""
🌊 شبیه‌ساز ایستگاه تراز آب — برای تست کامل سیستم بدون سخت‌افزار
داده واقعی‌نما می‌فرستد: موج کشندی ملایم + نویز + افت بسیار کند بلندمدت

اجرا:  python water_sim.py            (ارسال هر ۱۰ ثانیه)
       python water_sim.py --fast     (هر ۱ ثانیه — برای تست سریع)
قطع:   Ctrl+C
"""
import asyncio, json, math, random, socket, time, sys

SERVER_IP = "127.0.0.1"
SERVER_PORT = 10111
DEVICE_ID = "STN-NOSHR-1"
DATUM_MM = 5000.0          # باید با DATUM_MM فریم‌ور یکی باشد
BASE_DIST_MM = 3000.0      # فاصله پایه سنسور تا آب (≈ تراز +2000mm)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def make_reading(t):
    """مدل واقعی‌نما: کشند خزری ملایم (تلاطم) + نویز + افت کند"""
    tide = 40.0 * math.sin(2 * math.pi * t / (6 * 3600))      # چرخه ~۶ ساعته
    seiche = 12.0 * math.sin(2 * math.pi * t / (900))         # لرزش سطح (سایش)
    noise = random.gauss(0, 2.5)                              # نویز سنسور
    drift = -0.0007 * t                                       # افت بسیار کند
    dist = BASE_DIST_MM - tide - seiche - noise - drift
    temp = 15 + 4 * math.sin(2 * math.pi * t / 86400) + random.gauss(0, 0.3)
    return dist, temp


async def main():
    fast = "--fast" in sys.argv
    interval = 1 if fast else 10
    t0 = time.time()
    n = 0
    print(f"🌊 شبیه‌ساز ایستگاه {DEVICE_ID} → {SERVER_IP}:{SERVER_PORT} "
          f"(هر {interval} ثانیه — قطع: Ctrl+C)")
    while True:
        t = time.time() - t0
        dist, temp = make_reading(t)
        pkt = json.dumps({"id": DEVICE_ID, "dist_mm": round(dist, 1),
                          "temp_c": round(temp, 1), "datum_mm": DATUM_MM})
        sock.sendto(pkt.encode(), (SERVER_IP, SERVER_PORT))
        n += 1
        level = DATUM_MM - dist
        print(f"[{n:4d}] dist={dist:7.1f}mm  level={level:+7.1f}mm  temp={temp:5.1f}°C")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nخداحافظ! 🌊")
