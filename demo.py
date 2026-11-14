# -*- coding: utf-8 -*-
"""
🎬 دموی پنل کارکنان — شبیه‌سازی کامل تجربه «پورتال کارکنان بندر»
ورود با کد پرسنلی + رمز، فیش حقوقی چندماهه، اضافه‌کاری، مرخصی، ابلاغیه.
⚠️ همه داده‌ها «نمونه» و ساختگی‌اند — هدف نمایش محصول برای سازمان است.

کدهای نمونه: 101 / 102 / 103 — رمز نمونه: 1234
"""
import hashlib, logging, secrets, time

import db

log = logging.getLogger("demo")

SESSION_TTL_SEC = 15 * 60      # نشست ورود ۱۵ دقیقه معتبر است


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + pin).encode()).hexdigest()


# ─────────────── داده اولیه نمونه (یک‌بار) ───────────────
EMPLOYEES = [
    {"code": "101", "name": "رضا محمدی",  "unit": "عملیات اسکله", "base": 12_500_000},
    {"code": "102", "name": "علی نادری",  "unit": "تعمیرات فنی",  "base": 13_200_000},
    {"code": "103", "name": "سارا کریمی", "unit": "مرکز VTS",     "base": 14_000_000},
]
MONTHS = ["1405-06", "1405-07", "1405-08"]
MONTH_FA = {"1405-06": "شهریور ۱۴۰۵", "1405-07": "مهر ۱۴۰۵", "1405-08": "آبان ۱۴۰۵"}
OT_HOURS = {"101": [18, 26, 32], "102": [12, 20, 15], "103": [22, 30, 28]}
MEMOS = [
    ("تغییر ساعت کاری ماه آینده", "به اطلاع می‌رساند ساعات کاری واحد از ابتدای ماه آینده ۷:۳۰ تا ۱۵:۳۰ خواهد بود."),
    ("دوره الزامی گوارد", "همکاران عملیاتی می‌بایست تا پایان ماه در دوره گوارد شرکت کنند — ثبت‌نام از واحد آموزش."),
    ("جلسه ماهانه HSE", "جلسه ایمنی ماهانه روز چهارشنبه ساعت ۱۰ در سالن اجتماعات برگزار می‌شود."),
]


def seed_if_empty():
    if db.get_demo_employee("101"):
        return
    for e in EMPLOYEES:
        salt = secrets.token_hex(8)
        db._exec(
            "INSERT INTO demo_employees(code,name,unit,pin_hash,salt) VALUES(?,?,?,?,?)",
            (e["code"], e["name"], e["unit"], hash_pin("1234", salt), salt))
        for ym, ot_h in zip(MONTHS, OT_HOURS[e["code"]]):
            base = e["base"]
            ot_pay = round(ot_h * 87_500, -3)
            allowance = 1_500_000
            gross = base + ot_pay + allowance
            deduction = round(gross * 0.16, -3)
            net = gross - deduction
            db._exec(
                "INSERT INTO demo_payslips(code,ym,base,overtime_pay,allowance,"
                "deduction,net,overtime_hours) VALUES(?,?,?,?,?,?,?,?)",
                (e["code"], ym, base, ot_pay, allowance, deduction, net, ot_h))
        for lt, total, used in [("استحقاقی", 26, 11), ("استعلاجی", 10, 2)]:
            db._exec("INSERT INTO demo_leaves(code,leave_type,total,used) VALUES(?,?,?,?)",
                     (e["code"], lt, total, used))
        for title, body in MEMOS:
            db._exec("INSERT INTO demo_memos(code,title,body,ts) VALUES(?,?,?,?)",
                     (e["code"], title, body, time.time()))
    log.info("داده دموی پنل کارکنان ایجاد شد (۳ کارمند نمونه، رمز 1234)")


def verify_login(code: str, pin: str):
    e = db.get_demo_employee(code)
    if not e:
        return None
    return e if hash_pin(pin, e["salt"]) == e["pin_hash"] else None


def session_valid(context) -> bool:
    s = context.user_data.get("staff_session")
    return bool(s and s.get("exp", 0) > time.time())


# ─────────────── سازنده‌های گزارش ───────────────
def fa_money(x: float) -> str:
    return f"{x:,.0f}".replace(",", "،")


def build_home(e) -> str:
    return (f"👷 <b>{e['name']}</b> خوش آمدید\n"
            f"🏭 واحد: {e['unit']} | ش پرسنلی: {e['code']}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "از منوی زیر استفاده کنید:\n"
            "🔬 <i>حالت دمو — همه داده‌ها آزمایشی است</i>")


def build_payslip(e, ym: str) -> str:
    p = db.demo_payslip(e["code"], ym)
    if not p:
        return "فیشی برای این ماه ثبت نشده است."
    return (
        f"🧾 <b>فیش حقوقی — {MONTH_FA.get(ym, ym)}</b>\n"
        f"🔬 <i>داده آزمایشی</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 {e['name']} | واحد: {e['unit']}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 حقوق پایه: {fa_money(p['base'])}\n"
        f"⏱ اضافه‌کاری ({p['overtime_hours']:.0f} ساعت): {fa_money(p['overtime_pay'])}\n"
        f"🏠 کمک‌هزینه (مسکن/بن): {fa_money(p['allowance'])}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"➖ کسورات (بیمه/مالیات): {fa_money(p['deduction'])}\n"
        f"✅ <b>خالص پرداختی: {fa_money(p['net'])}</b>"
    )


def build_overtime(e) -> str:
    lines = [f"⏱ <b>اضافه‌کاری — {e['name']}</b>", "🔬 <i>داده آزمایشی</i>",
             "━━━━━━━━━━━━━━━━━━"]
    for ym in MONTHS:
        p = db.demo_payslip(e["code"], ym)
        if p:
            lines.append(f"• {MONTH_FA.get(ym, ym)}: <b>{p['overtime_hours']:.0f} ساعت</b> "
                         f"→ {fa_money(p['overtime_pay'])} ({'✅ تایید شده' if ym != MONTHS[-1] else '⏳ در انتظار تایید'})")
    return "\n".join(lines)


def build_leave(e) -> str:
    lines = [f"📅 <b>مانده مرخصی — {e['name']}</b>", "🔬 <i>داده آزمایشی</i>",
             "━━━━━━━━━━━━━━━━━━"]
    for r in db.demo_leaves(e["code"]):
        left = r["total"] - r["used"]
        lines.append(f"• {r['leave_type']}: مانده <b>{left:.0f}</b> از {r['total']:.0f} روز "
                     f"(استفاده‌شده {r['used']:.0f})")
    return "\n".join(lines)


def build_memos(e) -> str:
    lines = [f"📬 <b>ابلاغیه‌های داخلی — {e['name']}</b>", "🔬 <i>داده آزمایشی</i>",
             "━━━━━━━━━━━━━━━━━━"]
    for m in db.demo_memos(e["code"]):
        lines.append(f"📌 <b>{m['title']}</b>\n{m['body']}\n")
    return "\n".join(lines)
