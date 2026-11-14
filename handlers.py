# -*- coding: utf-8 -*-
"""منطق گفتگوی ربات: /start → انتخاب نقش → منوی اختصاصی → سرویس‌ها"""
import asyncio, logging, time
from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters,
)

import ais, config, db, demo, keyboards, weather, certs

log = logging.getLogger("handlers")

WELCOME = (
    "👋 <b>خوش آمدید به دستیار دیجیتال بندر نوشهر</b> 🌊⚓\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "این ربات اطلاعات زنده دریا، هواشناسی مسیر، تردد شناورها و اطلاعیه‌های بندر را "
    "در اختیار شما می‌گذارد.\n\n"
    "<b>لطفاً نوع استفاده خود را انتخاب کنید تا منوی مناسب شما نمایش داده شود:</b>"
)


def _fmt_ais_line(v):
    flag = "⚓" if v["in_zone"] else "📍"
    name = v["name"] or "MMSI ناشناس"
    sog = f"{v['sog']:.1f}" if v["sog"] is not None else "-"
    typ = f" | {v['type']}" if v.get("type") else ""
    dest = f" | 🧭 مقصد: {v['dest']}" if v.get("dest") else ""
    return (f"{flag} <b>{name}</b> — {v['dist_km']:.1f} کیلومتر | سرعت {sog} گره{typ}{dest}")


# ─────────────────────── /start و /help ───────────────────────
async def cmd_start(update: Update, _):
    u = update.effective_user
    db.upsert_user(u.id, u.first_name or "", u.username or "")
    await update.message.reply_html(WELCOME, reply_markup=keyboards.role_kb())


async def cmd_help(update: Update, _):
    await update.message.reply_html(
        "ℹ️ <b>راهنمای ربات دستیار بندر نوشهر</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "/start — شروع و انتخاب نوع کاربر\n"
        "🌊 دریای الان — موج، دمای آب و بادِ لحظه‌ای\n"
        "🗓 پیش‌بینی ۴۸ ساعته — روند موج و باد\n"
        "🚢 شناورهای اطراف — دیده‌بان AIS (کارگزار/سازمانی)\n"
        "🔔 هشدارها — اعلان خودکار موج خطرناک یا ورود شناور\n\n"
        "⚠️ داده‌ها از Open-Meteo و جریان عمومی AIS است و جایگزین اعلان رسمی بندر نیستند."
    )


async def cmd_admin(update: Update, _):
    if update.effective_user.id != config.ADMIN_CHAT_ID:
        await update.message.reply_text("⛔ این بخش فقط برای مدیر ربات است.")
        return
    await update.message.reply_html(
        "🛠 <b>پنل مدیریت</b>", reply_markup=keyboards.admin_kb())


# ─────────────────────── مسیریابی دکمه‌های شیشه‌ای ───────────────────────
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data
    # اگر اتصال کند باشد و کوئری هنگام رسیدن به ربات قدیمی شده باشد،
    # نباید کل پردازش بشکند — فقط لاگ می‌کنیم و ادامه می‌دهیم.
    try:
        await q.answer()
    except Exception as e:
        log.warning("answer_callback_query failed: %s", e)
    user = db.get_user(q.from_user.id)
    if not user:
        db.upsert_user(q.from_user.id, q.from_user.first_name or "", q.from_user.username or "")
        user = db.get_user(q.from_user.id)
    role = user["role"]

    async def show(text, kb=None):
        """نمایش نتیجه با مقاومت در برابر شبکه ناپایدار:
        ابتدا ۳ بار تلاش برای ویرایش پیام؛ اگر نشد، ۳ بار تلاش برای پیام تازه."""
        markup = kb or keyboards.main_kb(role, user)
        last_err = None

        for attempt in range(3):
            try:
                await q.edit_message_text(text, parse_mode="HTML", reply_markup=markup,
                                          disable_web_page_preview=True)
                return
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return
                last_err = e
                break  # با تکرار درست نمی‌شود → مستقیم به ارسال پیام تازه
            except NetworkError as e:
                last_err = e
                log.warning("edit attempt %s/3 failed (network): %s", attempt + 1, e)
                await asyncio.sleep(1.5)
            except Forbidden:
                log.warning("user %s blocked the bot", q.from_user.id)
                return

        log.warning("edit failed (%s) — fallback to send_message", last_err)
        chat_id = q.message.chat_id if q.message else q.from_user.id
        for attempt in range(3):
            try:
                await context.bot.send_message(chat_id, text, parse_mode="HTML",
                                               reply_markup=markup,
                                               disable_web_page_preview=True)
                return
            except NetworkError as e:
                log.warning("send attempt %s/3 failed: %s", attempt + 1, e)
                await asyncio.sleep(1.5)
            except Forbidden:
                return
        log.error("هم ویرایش و هم ارسال ناموفق بود: %s", last_err)

    async def busy(text):
        """پیام «در حال دریافت...» — اگر ویرایش ممکن نبود، بی‌خیال؛ show خودش پیام می‌فرستد"""
        try:
            await q.edit_message_text(text)
        except Exception:
            pass

    # ── انتخاب نقش ──
    if data.startswith("role:"):
        new_role = data.split(":")[1]
        db.set_role(q.from_user.id, new_role)
        role_name = config.ROLES.get(new_role, new_role)
        intro = {
            "driver": "🚛 منوی راننده: هوای مسیر، راهنمای مدارک و وضعیت دریا در دسترس شماست.",
            "agent": "🚢 منوی کارگزار: دیده‌بان شناورها (AIS)، پنجره هوایی عملیات و هشدار ورود شناور آماده است.",
            "fisher": "🎣 منوی صیاد: وضعیت ایمنی قایق کوچک و هشدار موج خطرناک فعال است.",
            "tourist": "🏖 منوی گردشگر: اطلاعات ساحل، دمای آب، طلوع و غروب آماده است.",
            "org": "🏢 منوی سازمانی: دیده‌بان شناورها و آمار تردد در دسترس است.",
            "staff": "👷 منوی کارمند بندر: وضعیت دریا قبل شیفت، تراز آب، شناورها، "
                     "پنل کارکنان (نمونه) و یادآور گواهینامه‌ها آماده است.",
        }
        await show(
            f"{role_name} انتخاب شد ✅\n{intro.get(new_role, '')}\n\n👇 از منو استفاده کنید:",
            keyboards.main_kb(new_role, user))
        return

    if data == "chrole":
        await show("👤 لطفاً نوع استفاده خود را انتخاب کنید:", keyboards.role_kb())
        return

    if data == "menu":
        await show(f"🏠 <b>منوی اصلی</b> — {config.ROLES.get(role, '')}\n👇 چه کاری انجام دهم؟",
                   keyboards.main_kb(role, user))
        return

    # ── هواشناسی و دریا ──
    if data == "wx:now":
        await busy("⏳ در حال دریافت وضعیت دریا...")
        await show(await weather.get_sea_now())
        return

    if data == "wx:48":
        await busy("⏳ در حال دریافت پیش‌بینی...")
        await show(await weather.get_forecast_48())
        return

    if data == "wx:route":
        await busy("⏳ هوای مسیر را بررسی می‌کنم...")
        await show(await weather.get_route_weather())
        return

    if data == "wx:window":
        await busy("⏳ پنجره هوایی عملیات محاسبه می‌شود...")
        await show(await weather.get_operation_window())
        return

    if data == "fish:safe":
        await busy("⏳ وضعیت ایمنی دریا بررسی می‌شود...")
        await show(await weather.get_boat_safety())
        return

    if data == "tour:beach":
        await busy("⏳ اطلاعات ساحل دریافت می‌شود...")
        await show(await weather.get_beach_info())
        return

    # ── AIS: شناورها و آمار ──
    if data == "ais:list":
        vessels = ais.vessels_sorted(15)
        if not vessels:
            if ais.enabled():
                src = f"• استریم جهانی aisstream.io: وصل ✔\n• گیرنده محلی RTL-SDR: UDP پورت {config.NMEA_UDP_PORT}"
            else:
                src = (f"• استریم جهانی: غیرفعال (کلید تنظیم نشده)\n"
                       f"• گیرنده محلی RTL-SDR: UDP پورت {config.NMEA_UDP_PORT}")
            await show(
                "🚢 <b>دیده‌بان شناورها (AIS)</b>\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "فعلاً شناوری در محدوده دیده‌بانی گزارش نشده است.\n\n"
                f"<b>منابع فعال:</b>\n{src}\n\n"
                "<i>پوشش AIS شبکه‌های جهانی در دریای خزر تقریباً صفر است — "
                "با اتصال گیرنده محلی RTL-SDR، شناورهای اطراف نوشهر زنده نمایش داده می‌شوند.</i>")
            return
        lines = [
            "🚢 <b>شناورهای اطراف بندر نوشهر</b> (دیده‌بان AIS زنده)",
            "━━━━━━━━━━━━━━━━━━",
        ]
        lines += [_fmt_ais_line(v) for v in vessels]
        lines.append("\n⚓ = داخل محدوده بندر | 📍 = در حال حرکت در منطقه")
        lines.append("<i>منبع: گیرنده محلی RTL-SDR / استریم عمومی AIS</i>")
        await show("\n".join(lines))
        return

    # ── پایش تراز آب ──
    if data == "water:status":
        import water
        await show(water.build_status_report(), keyboards.water_kb(q.from_user.id))
        return

    if data == "water:alert":
        import water
        on = not db.water_is_subscribed(q.from_user.id)
        db.water_subscribe(q.from_user.id, on)
        note = ("🔔 هشدار افت آبخور <b>روشن شد</b> — اگر افت ۲۴ ساعته از آستانه بگذرد، "
                "پیام می‌گیری.\n" if on else "🔕 هشدار افت آبخور خاموش شد.\n")
        await show(note + "\n" + water.build_status_report(),
                   keyboards.water_kb(q.from_user.id))
        return

    # ── گواهینامه‌های من ──
    if data == "cert:list":
        await show(certs._fmt_list(q.from_user.id), keyboards.cert_kb(q.from_user.id))
        return

    if data == "cert:add":
        context.user_data["cert_state"] = "await_title"
        await show("➕ <b>افزودن گواهینامه</b>\n\n۱/۲ — عنوان گواهینامه را بنویسید:\n"
                   "<i>مثال: گوارد، گواهینامه رانندگی، مدارک دریانوردی</i>",
                   keyboards.back_kb("🔙 انصراف"))
        return

    if data.startswith("cert:del:"):
        try:
            cid = int(data.rsplit(":", 1)[1])
        except ValueError:
            return
        db.delete_certificate(cid, q.from_user.id)
        await show(certs._fmt_list(q.from_user.id), keyboards.cert_kb(q.from_user.id))
        return

    # ── دموی پنل کارکنان ──
    if data == "staff:login":
        context.user_data["staff_state"] = "await_code"
        await show(
            "🔐 <b>پنل کارکنان بندر نوشهر</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "۱/۲ — کد پرسنلی را ارسال کنید:\n\n"
            "🔬 <i>حالت دمو — کدهای نمونه: 101 / 102 / 103 (رمز: 1234)</i>",
            keyboards.back_kb("🔙 انصراف"))
        return

    if data == "staff:logout":
        context.user_data.pop("staff_session", None)
        await show("🚪 خارج شدید.\nبرای ورود دوباره: «🔐 پنل کارکنان (نمونه)»",
                   keyboards.back_kb())
        return

    if data == "staff:home":
        if not demo.session_valid(context):
            context.user_data["staff_state"] = "await_code"
            await show("⌛ نشست شما منقضی شد — دوباره وارد شوید:\n\n"
                       "🔬 <i>حالت دمو — کد: 101 / 102 / 103 (رمز: 1234)</i>",
                       keyboards.back_kb("🔙 انصراف"))
            return
        e = demo.EMPLOYEES[[x["code"] for x in demo.EMPLOYEES].index(
            context.user_data["staff_session"]["code"])]
        await show(demo.build_home(e), keyboards.demo_home_kb())
        return

    if data.startswith("staff:payslip"):
        if not demo.session_valid(context):
            await show("⌛ نشست منقضی — دوباره وارد شوید (🔐 پنل کارکنان).")
            return
        code = context.user_data["staff_session"]["code"]
        e = next(x for x in demo.EMPLOYEES if x["code"] == code)
        ym_list = db.demo_payslip_ym_list(code)
        ym = data.split(":", 2)[2] if data.count(":") == 2 else (ym_list[0] if ym_list else None)
        if not ym:
            await show("فیشی ثبت نشده است.")
            return
        await show(demo.build_payslip(e, ym), keyboards.demo_payslip_kb(ym_list, ym))
        return

    if data in ("staff:overtime", "staff:leave", "staff:memos"):
        if not demo.session_valid(context):
            await show("⌛ نشست منقضی — دوباره وارد شوید (🔐 پنل کارکنان).")
            return
        code = context.user_data["staff_session"]["code"]
        e = next(x for x in demo.EMPLOYEES if x["code"] == code)
        text = (demo.build_overtime(e) if data == "staff:overtime" else
                demo.build_leave(e) if data == "staff:leave" else
                demo.build_memos(e))
        await show(text, keyboards.demo_home_kb())
        return

    if data == "stats":
        n24 = db.count_vessels_last_hours(24)
        nz = db.count_vessels_in_zone()
        await show(
            "📊 <b>آمار تردد شناورها (از داده‌های دیده‌بان این ربات)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🚢 شناورهای دیده‌شده در ۲۴ ساعت اخیر: <b>{n24}</b>\n"
            f"⚓ شناورهای داخل محدوده بندر: <b>{nz}</b>\n\n"
            f"<i>هرچه ربات مدت بیشتری روشن باشد، این آمار دقیق‌تر می‌شود.</i>")
        return

    # ── اطلاعیه‌ها و تماس‌ها و راهنماها ──
    if data == "news":
        rows = db.get_announcements(5)
        if not rows:
            await show("📰 فعلاً اطلاعیه‌ای ثبت نشده است.\n"
                       "<i>اطلاعیه‌ها توسط مدیر ربات (اداره بندر) منتشر می‌شود.</i>")
            return
        lines = ["📰 <b>آخرین اطلاعیه‌های بندر</b>", "━━━━━━━━━━━━━━━━━━"]
        for i, r in enumerate(rows, 1):
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))
            lines.append(f"\n<b>{i}.</b> {r['text']}\n<i>🕐 {t}</i>")
        await show("\n".join(lines))
        return

    if data == "contacts":
        lines = ["📞 <b>شماره‌های تماس مهم</b>", "━━━━━━━━━━━━━━━━━━"]
        lines += [f"{n}: <code>{v}</code>" for n, v in config.CONTACTS]
        lines.append("\n<i>⚠️ شماره‌های نمونه — لطفاً پیش از استفاد عمومی با نسخه رسمی تکمیل شود.</i>")
        await show("\n".join(lines))
        return

    if data == "guide:driver":
        await show(config.DRIVER_GUIDE)
        return

    if data == "guide:berths":
        await show(config.AGENT_BERTH_INFO)
        return

    # ── هشدارها و تنظیمات ──
    if data == "alerts":
        await show("⚙️ <b>هشدارها و تنظیمات شما</b>\n👇 گزینه مورد نظر را انتخاب کنید:",
                   keyboards.alerts_kb(user))
        return

    if data == "alert:wave" or data == "alert:wave:toggle":
        on = not bool(user["wave_alert"])
        db.set_wave_alert(q.from_user.id, on, user["wave_threshold"] or 1.5)
        user = db.get_user(q.from_user.id)
        txt = ("🟢 هشدار موج فعال شد! اگر ارتفاع موج از آستانه شما بگذرد، پیام می‌گیرید.\n"
               if on else "🔴 هشدار موج خاموش شد.\n")
        await show(txt + "👇", keyboards.alerts_kb(user))
        return

    if data == "alert:wave:thr":
        await show("🎚 آستانه ارتفاع موج برای هشدار را انتخاب کنید:",
                   keyboards.threshold_kb())
        return

    if data.startswith("alert:wave:set:"):
        thr = float(data.rsplit(":", 1)[1])
        db.set_wave_alert(q.from_user.id, True, thr)
        user = db.get_user(q.from_user.id)
        await show(f"✅ آستانه موج روی <b>{thr:.2f} متر</b> تنظیم و هشدار فعال شد.",
                   keyboards.alerts_kb(user))
        return

    if data == "alert:ais" or data == "alert:ais:toggle":
        on = not bool(user["ais_alert"])
        db.set_ais_alert(q.from_user.id, on)
        user = db.get_user(q.from_user.id)
        if not ais.enabled() and on:
            txt = ("🟡 هشدار ورود شناور فعال شد — اما سرویس AIS هنوز پیکربندی نشده "
                   "(AIS_API_KEY). پس از فعال‌سازی کار می‌کند.\n")
        else:
            txt = ("🟢 هشدار ورود شناور فعال شد! وقتی شناوری وارد محدوده بندر شود پیام می‌گیرید.\n"
                   if on else "🔴 هشدار ورود شناور خاموش شد.\n")
        await show(txt + "👇", keyboards.alerts_kb(user))
        return

    # ── پنل مدیریت ──
    if data.startswith("admin:"):
        if q.from_user.id != config.ADMIN_CHAT_ID:
            await show("⛔ فقط مدیر می‌تواند از پنل مدیریت استفاده کند.")
            return
        action = data.split(":", 1)[1]
        if action == "new":
            context.user_data["awaiting_announcement"] = True
            await show("📢 لطفاً متن اطلاعیه را ارسال کنید (یک پیام متنی):\n"
                       "<i>برای انصراف /admin را دوباره بزنید.</i>", keyboards.admin_kb())
            return
        if action == "list":
            rows = db.get_announcements(5)
            lines = ["🗂 <b>آخرین اطلاعیه‌ها</b>", "━━━━━━━━━━━━━━━━━━"]
            lines += [f"\n{r['id']}. {r['text']}" for r in rows] or ["—"]
            await show("\n".join(lines), keyboards.admin_kb())
            return
        if action == "dellast":
            db.delete_last_announcement()
            await show("✅ آخرین اطلاعیه حذف شد.", keyboards.admin_kb())
            return
        if action == "users":
            n = len(db.all_user_ids())
            await show(f"👥 تعداد کاربران ثبت‌شده: <b>{n}</b>", keyboards.admin_kb())
            return

    await show("🤔 گزینه نامشخص — دوباره تلاش کنید.",
               keyboards.main_kb(role, user))


# ─────────────────────── دریافت متن: اطلاعیه مدیر + گفتگوهای ورود/گواهی ───────────────────────
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ud = context.user_data
    text = update.message.text.strip()

    # ۱) اطلاعیه مدیر
    if uid == config.ADMIN_CHAT_ID and ud.get("awaiting_announcement"):
        ud["awaiting_announcement"] = False
        db.add_announcement(text)
        sent, failed = 0, 0
        for chat_id in db.all_user_ids():
            try:
                await context.bot.send_message(
                    chat_id,
                    f"📰 <b>اطلاعیه بندر نوشهر</b>\n━━━━━━━━━━━━━━━━━━\n{text}",
                    parse_mode="HTML")
                sent += 1
            except (Forbidden, BadRequest):
                failed += 1
        await update.message.reply_html(
            f"✅ اطلاعیه ثبت و برای <b>{sent}</b> کاربر ارسال شد."
            + (f"\n⚠️ ارسال برای {failed} کاربر ناموفق بود (ربات را بلاک کرده‌اند)." if failed else ""),
            reply_markup=keyboards.admin_kb())
        return

    # ۲) ورود دموی پنل کارکنان — مرحله کد پرسنلی
    if ud.get("staff_state") == "await_code":
        ud["staff_code"] = text
        ud["staff_state"] = "await_pin"
        await update.message.reply_html(
            f"کد پرسنلی: <code>{text}</code>\n\n"
            "۲/۲ — رمز ورود را ارسال کنید:\n"
            "🔬 <i>دمو — رمز نمونه: 1234</i>")
        return

    # ۳) ورود دموی پنل کارکنان — مرحله رمز
    if ud.get("staff_state") == "await_pin":
        ud["staff_state"] = None
        code = ud.get("staff_code", "")
        e = demo.verify_login(code, text)
        if not e:
            await update.message.reply_html(
                "❌ کد پرسنلی یا رمز اشتباه است.\n"
                "🔬 <i>دمو — کد: 101 / 102 / 103 | رمز: 1234</i>\n\n"
                "دوباره از دکمه «🔐 پنل کارکنان» شروع کنید.")
            return
        ud["staff_session"] = {"code": code, "exp": time.time() + demo.SESSION_TTL_SEC}
        ud.pop("staff_code", None)
        await update.message.reply_html(
            demo.build_home(e) + f"\n\n⏱ نشست شما {demo.SESSION_TTL_SEC//60} دقیقه معتبر است.",
            reply_markup=keyboards.demo_home_kb())
        return

    # ۴) افزودن گواهینامه — عنوان
    if ud.get("cert_state") == "await_title":
        ud["cert_title"] = text[:60]
        ud["cert_state"] = "await_date"
        await update.message.reply_html(
            f"عنوان: <b>{text[:60]}</b>\n\n۲/۲ — تاریخ انقضا را ارسال کنید:\n"
            "<code>1404-09-22</code> (شمسی) یا <code>2025-12-13</code> (میلادی)\n"
            "جداکننده: <code>-</code> یا <code>/</code>")
        return

    # ۵) افزودن گواهینامه — تاریخ
    if ud.get("cert_state") == "await_date":
        ud["cert_state"] = None
        ts = certs.parse_date_input(text)
        if ts is None:
            await update.message.reply_html(
                "❌ تاریخ نامعتبر است. نمونه درست: <code>1404-09-22</code> — دوباره بفرستید.")
            return
        db.add_certificate(uid, ud.get("cert_title", "گواهینامه"), ts, text.strip())
        ud.pop("cert_title", None)
        await update.message.reply_html(
            "✅ گواهینامه ثبت شد — از این به بعد یادآور خودکار می‌گیری "
            "(۳۰/۱۵/۷/۳/۱ روز و روز انقضا).\n\n" + certs._fmt_list(uid),
            reply_markup=keyboards.cert_kb(uid))
        return

    await update.message.reply_html("👌 برای دیدن منو /start را بزنید.")


def register(app: Application):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
