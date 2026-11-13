# -*- coding: utf-8 -*-
"""دکمه‌های شیشه‌ای (InlineKeyboard) ربات — به تفکیک نقش کاربر"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

W = 2  # تعداد ستون پیش‌فرض


def _grid(buttons, cols=W):
    rows, row = [], []
    for b in buttons:
        row.append(b)
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def role_kb() -> InlineKeyboardMarkup:
    """انتخاب نوع کاربر در شروع"""
    btns = [
        InlineKeyboardButton("🚛 راننده و حمل‌ونقل", callback_data="role:driver"),
        InlineKeyboardButton("🚢 کارگزار کشتی / شیپینگ", callback_data="role:agent"),
        InlineKeyboardButton("🎣 ماهیگیر / صیاد", callback_data="role:fisher"),
        InlineKeyboardButton("🏖 گردشگر / عموم", callback_data="role:tourist"),
        InlineKeyboardButton("🏢 سازمانی / پژوهشگر", callback_data="role:org"),
    ]
    return InlineKeyboardMarkup([[b] for b in btns])


def common_buttons(role):
    """دکمه‌های مشترک همه نقش‌ها"""
    return [
        InlineKeyboardButton("🌊 دریای الان", callback_data="wx:now"),
        InlineKeyboardButton("🗓 پیش‌بینی ۴۸ ساعت", callback_data="wx:48"),
        InlineKeyboardButton("📰 اطلاعیه‌های بندر", callback_data="news"),
        InlineKeyboardButton("📞 شماره‌های تماس", callback_data="contacts"),
    ]


def main_kb(role: str, user=None) -> InlineKeyboardMarkup:
    """منوی اصلی بر اساس نقش"""
    btns = list(common_buttons(role))

    if role == "driver":
        btns += [
            InlineKeyboardButton("🚚 هوای مسیر تهران←نوشهر", callback_data="wx:route"),
            InlineKeyboardButton("🧾 راهنمای مدارک بار", callback_data="guide:driver"),
        ]
    elif role == "agent":
        btns += [
            InlineKeyboardButton("🚢 شناورهای اطراف بندر", callback_data="ais:list"),
            InlineKeyboardButton("🛟 پنجره هوایی عملیات", callback_data="wx:window"),
            InlineKeyboardButton("🏗 وضعیت اسکله‌ها", callback_data="guide:berths"),
            InlineKeyboardButton("🔔 هشدار ورود شناور", callback_data="alert:ais"),
        ]
    elif role == "fisher":
        btns += [
            InlineKeyboardButton("🎣 ایمنی قایق کوچک", callback_data="fish:safe"),
            InlineKeyboardButton("🔔 هشدار موج خطرناک", callback_data="alert:wave"),
        ]
    elif role == "tourist":
        btns += [
            InlineKeyboardButton("🏖 اطلاعات ساحل و شنا", callback_data="tour:beach"),
        ]
    elif role == "org":
        btns += [
            InlineKeyboardButton("🚢 شناورهای اطراف بندر", callback_data="ais:list"),
            InlineKeyboardButton("📊 آمار تردد شناورها", callback_data="stats"),
        ]

    # تنظیمات پایین منو
    settings = []
    if role in ("agent", "fisher", "driver"):
        settings.append(InlineKeyboardButton("⚙️ هشدارها و تنظیمات", callback_data="alerts"))
    settings.append(InlineKeyboardButton("🔄 تغییر نوع کاربر", callback_data="chrole"))

    rows = _grid(btns)
    if settings:
        rows.append(settings)
    return InlineKeyboardMarkup(rows)


def alerts_kb(user) -> InlineKeyboardMarkup:
    """پنل تنظیم هشدارها"""
    rows = []
    if user:
        w_on = bool(user["wave_alert"])
        rows.append([InlineKeyboardButton(
            ("🟢 هشدار موج: فعال (خاموش کن)" if w_on else "🔴 هشدار موج: خاموش (روشن کن)"),
            callback_data="alert:wave:toggle")])
        if w_on:
            rows.append([InlineKeyboardButton(
                f"🎚 آستانه موج: {user['wave_threshold']:.1f}m — تغییر",
                callback_data="alert:wave:thr")])
        a_on = bool(user["ais_alert"])
        rows.append([InlineKeyboardButton(
            ("🟢 هشدار ورود شناور: فعال (خاموش کن)" if a_on else "🔴 هشدار ورود شناور: خاموش (روشن کن)"),
            callback_data="alert:ais:toggle")])
    rows.append([InlineKeyboardButton("🔙 بازگشت به منو", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


def threshold_kb() -> InlineKeyboardMarkup:
    vals = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5]
    rows = [InlineKeyboardButton(f"{v:.2f} متر", callback_data=f"alert:wave:set:{v}")
            for v in vals]
    return InlineKeyboardMarkup(_grid(rows, 3) + [[
        InlineKeyboardButton("🔙 بازگشت", callback_data="alerts")]])


def back_kb(text="🔙 بازگشت به منو") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data="menu")]])


def admin_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 ارسال اطلاعیه جدید", callback_data="admin:new")],
        [InlineKeyboardButton("🗂 آخرین اطلاعیه‌ها", callback_data="admin:list")],
        [InlineKeyboardButton("❌ حذف آخرین اطلاعیه", callback_data="admin:dellast")],
        [InlineKeyboardButton("📊 تعداد کاربران", callback_data="admin:users")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu")],
    ])
