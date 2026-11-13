# -*- coding: utf-8 -*-
"""
🚢 ربات دستیار دیجیتال بندر نوشهر — نقطه ورود اصلی

راه‌اندازی:
    1) pip install -r requirements.txt
    2) توکن ربات را در config.py یا متغیر محیطی BOT_TOKEN بگذارید
    3) python bot.py
"""
import asyncio, logging, sys, time

from telegram import Update
from telegram.ext import Application, ContextTypes

import alerts, ais, config, db, handlers

logging.basicConfig(
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")


async def on_startup(app: Application) -> None:
    """پس از اتصال به تلگرام: دیده‌بان AIS و هشدارها را روشن کن"""
    db.init_db()
    alerts.setup(app)
    tasks = ais.start()
    if tasks:
        log.info("دیده‌بان AIS روشن شد (%d منبع داده).", len(tasks))
    me = await app.bot.get_me()
    log.info("ربات @%s آماده است ✅", me.username)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """خطاهای پردازش آپدیت‌ها را ثبت کن تا ربات نبرد"""
    log.error("خطا در پردازش آپدیت: %s", context.error, exc_info=context.error)


def build_app() -> Application:
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .concurrent_updates(True)      # شبکه کند: یک درخواست بقیه را قفل نکند
        .post_init(on_startup)
        .build()
    )
    app.add_error_handler(on_error)
    handlers.register(app)
    return app


def main() -> None:
    if "PUT-YOUR" in config.BOT_TOKEN:
        print("=" * 60)
        print("❌ خطا: توکن ربات تنظیم نشده است!")
        print("   1) در تلگرام به @BotFather پیام بدهید → /newbot")
        print("   2) توکن را در config.py (BOT_TOKEN) یا متغیر محیطی BOT_TOKEN بگذارید")
        print("=" * 60)
        sys.exit(1)

    # با هر قطعی موقت VPN، خودش دوباره بالا بیاید
    while True:
        try:
            app = build_app()
            log.info("در حال اتصال به تلگرام...")
            app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
            log.info("حلقه polling پایان یافت — راه‌اندازی مجدد در ۱۰ ثانیه...")
        except KeyboardInterrupt:
            log.info("توقف دستی ربات.")
            break
        except Exception as e:
            log.error("ربات با خطا متوقف شد: %s — راه‌اندازی مجدد در ۱۰ ثانیه...", e)
        time.sleep(10)


if __name__ == "__main__":
    main()
