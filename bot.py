import logging
from datetime import datetime, timedelta, timezone

# ══════════════════════════════════════════════
#  تایم‌زون تهران — UTC+3:30 (بدون نیاز به pytz)
#  اگه pytz نصب باشه از اون استفاده میکنه (DST رو هم درنظر میگیره)
#  اگه نباشه از UTC+3:30 ثابت استفاده میکنه
# ══════════════════════════════════════════════
try:
    import pytz
    TEHRAN_TZ = pytz.timezone("Asia/Tehran")
    def now_tehran():
        """زمان دقیق تهران — با احتساب ساعت تابستانی اگه pytz باشه"""
        return datetime.now(TEHRAN_TZ)
except ImportError:
    # UTC+3:30 ثابت — بدون DST
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))
    def now_tehran():
        return datetime.now(TEHRAN_TZ)

def fmt_dt(dt=None):
    """فرمت استاندارد تاریخ و ساعت تهران — مثلاً ۱۴۰۳-۰۲-۱۵ ساعت ۱۴:۳۲"""
    if dt is None:
        dt = now_tehran()
    return dt.strftime("%Y-%m-%d | %H:%M") + " (تهران)"
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, PollAnswerHandler, filters, ContextTypes
)

# ══════════════════════════════════════════════
#  تنظیمات اصلی — فقط اینجا رو عوض کن
# ══════════════════════════════════════════════
BOT_TOKEN      = "8977895133:AAHdVjMrr-9-ceXXviV5Zt5I_vP93HxQqZY"
ADMIN_CHAT_ID  = 1143598012
# شماره کارت — از پنل ادمین هم قابل تغییره
bot_config = {
    "card_number": "6037-XXXX-XXXX-XXXX",
    "card_owner":  "نام صاحب کارت",
}

# ══════════════════════════════════════════════
#  لاگ‌گیری
# ══════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)

# ══════════════════════════════════════════════
#  دیتابیس‌های حافظه‌ای
# ══════════════════════════════════════════════
users_db       = {}          # {chat_id: {name, username, chat_id}}
blocked_users  = set()       # chat_id های بلاک‌شده
reply_to       = {}          # {ADMIN_CHAT_ID: target_id / "broadcast"}
message_map    = {}          # {f"reply_{chat_id}": fwd_msg_id}
group_mode     = {}          # حالت ارسال به گروه

user_mode      = {}          # {chat_id: "anonymous" | "normal"}
user_coins     = {}          # {chat_id: int}
user_history   = {}          # {chat_id: [str, ...]}

# ── نظرسنجی ──────────────────────────────────
pending_poll   = {}          # {ADMIN_CHAT_ID: {step, question, options, target}}
poll_votes     = {}          # {poll_id: {option_id: count, "question": str, "options": [str]}}

# ── اشتراک ───────────────────────────────────
# plans: {plan_id: {name, days, price, description}}
subscription_plans = {
    "plan1": {"name": "اشتراک یک ماهه", "days": 30, "price": "۴۰,۰۰۰ تومان", "description": "دسترسی کامل ۳۰ روزه"},
}
# user_subscriptions: {chat_id: {"plan": plan_id, "expires": datetime}}
user_subscriptions = {}
# pending_receipts: {chat_id: {"plan": plan_id, "receipt_msg_id": int}}
pending_receipts   = {}
# pending_receipt_input: set — کاربرانی که منتظر ارسال رسیدند
pending_receipt_input = set()

# ── سکه ─────────────────────────────────────
pending_coin_add   = {}      # {ADMIN_CHAT_ID: target_chat_id}

# ── خاموش/روشن ربات ─────────────────────────
bot_state = {"active": True}  # ادمین می‌تونه ربات رو خاموش کنه

# ── اولویت پیام ──────────────────────────────
PRIORITY_LEVELS = {
    "normal": {"label": "🟢 عادی",  "emoji": "🟢", "cost": 0,  "title": "عادی"},
    "vip":    {"label": "🟡 ویژه",  "emoji": "🟡", "cost": 10, "title": "ویژه"},
    "urgent": {"label": "🔴 فوری",  "emoji": "🔴", "cost": 30, "title": "فوری"},
}

# ══════════════════════════════════════════════
#  🆕 دیتابیس‌های جدید
# ══════════════════════════════════════════════

# ── پروفایل کاربران ──────────────────────────
# user_profiles: {chat_id: {join_date, msg_count, admin_note, block_history: [], last_seen}}
user_profiles  = {}

# ── سیستم توکن ربات‌سازی ─────────────────────
# bot_tokens: {token_str: {chat_id, plan_id, created_at, used: bool, bot_username}}
bot_tokens     = {}
# user_bot_tokens: {chat_id: [token_str, ...]}   — توکن‌هایی که به این کاربر داده شده
user_bot_tokens = {}
# pending_token_input: {ADMIN_CHAT_ID: target_chat_id}  — ادمین داره توکن میفرسته
pending_token_input = {}
# user_submitting_token: set  — کاربرانی که دارن توکن وارد میکنن
user_submitting_token = set()

# ── یادداشت روی کاربر ────────────────────────
# pending_note_input: {ADMIN_CHAT_ID: target_chat_id}
pending_note_input = {}


# ══════════════════════════════════════════════
#  توابع کمکی
# ══════════════════════════════════════════════
def add_coins(chat_id, amount, reason=""):
    user_coins[chat_id] = user_coins.get(chat_id, 0) + amount
    sign  = "➕" if amount >= 0 else "➖"
    entry = f"{sign} {abs(amount)} سکه — {reason or 'بدون توضیح'} | {fmt_dt()}"
    user_history.setdefault(chat_id, []).append(entry)
    return user_coins[chat_id]


def get_coins(chat_id):
    return user_coins.get(chat_id, 0)


def has_active_subscription(chat_id):
    sub = user_subscriptions.get(chat_id)
    if not sub:
        return False
    return now_tehran() < sub["expires"]


def subscription_status_text(chat_id):
    sub = user_subscriptions.get(chat_id)
    if not sub:
        return "❌ ندارید"
    plan = subscription_plans.get(sub["plan"], {})
    expires = sub["expires"]
    if now_tehran() >= expires:
        return "⌛ منقضی شده"
    remaining = (expires - now_tehran()).days
    return f"✅ {plan.get('name','؟')} — {remaining} روز مانده (تا {expires.strftime('%Y-%m-%d')})"


# ══════════════════════════════════════════════
#  🆕 توابع پروفایل کاربر
# ══════════════════════════════════════════════
def ensure_profile(chat_id):
    """اگه پروفایل کاربر وجود نداشت، بساز"""
    if chat_id not in user_profiles:
        user_profiles[chat_id] = {
            "join_date":    fmt_dt(),    # تاریخ عضویت
            "msg_count":    0,           # تعداد پیام‌های ارسالی
            "admin_note":   "",          # یادداشت ادمین
            "block_history": [],         # سابقه بلاک‌ها
            "last_seen":    fmt_dt(),    # آخرین فعالیت
        }
    return user_profiles[chat_id]


def update_last_seen(chat_id):
    """آپدیت آخرین فعالیت کاربر"""
    p = ensure_profile(chat_id)
    p["last_seen"] = fmt_dt()


def increment_msg(chat_id):
    """یه پیام به شمارنده اضافه کن"""
    p = ensure_profile(chat_id)
    p["msg_count"] = p.get("msg_count", 0) + 1


def get_full_profile_text(chat_id):
    """متن کامل پروفایل کاربر برای ادمین"""
    info    = users_db.get(chat_id, {"name": str(chat_id), "username": "ندارد"})
    p       = ensure_profile(chat_id)
    coins   = get_coins(chat_id)
    sub     = subscription_status_text(chat_id)
    mode    = "🕵️ ناشناس" if user_mode.get(chat_id) == "anonymous" else "👤 عادی"
    blocked = "🚫 بله" if chat_id in blocked_users else "✅ خیر"
    note    = p.get("admin_note") or "—"
    tokens  = user_bot_tokens.get(chat_id, [])
    token_lines = ""
    for t in tokens:
        td = bot_tokens.get(t, {})
        status = "✅ استفاده شده" if td.get("used") else "⏳ استفاده نشده"
        token_lines += f"  • `{t}` — {status}\n"
    if not token_lines:
        token_lines = "  — توکنی ندارد\n"

    block_hist = p.get("block_history", [])
    block_hist_text = "\n".join(f"  • {b}" for b in block_hist[-3:]) if block_hist else "  — سابقه‌ای ندارد"

    return (
        f"👤 *پروفایل کامل کاربر*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏷 نام: *{info.get('name','؟')}*\n"
        f"🆔 یوزرنیم: @{info.get('username','ندارد')}\n"
        f"🔢 Chat ID: `{chat_id}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 تاریخ عضویت: {p.get('join_date','؟')}\n"
        f"🕐 آخرین فعالیت: {p.get('last_seen','؟')}\n"
        f"📨 تعداد پیام‌ها: {p.get('msg_count', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 موجودی سکه: {coins}\n"
        f"📦 اشتراک: {sub}\n"
        f"🔐 حالت ارسال: {mode}\n"
        f"🚫 بلاک‌شده: {blocked}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🤖 توکن‌های ربات:\n{token_lines}"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 سابقه بلاک:\n{block_hist_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 یادداشت ادمین: {note}"
    )


# ══════════════════════════════════════════════
#  🆕 توابع سیستم توکن ربات‌سازی
# ══════════════════════════════════════════════
import secrets
import string

def generate_token():
    """ساخت توکن یکتا — مثلاً BOT-A3X9K2"""
    chars = string.ascii_uppercase + string.digits
    code  = "".join(secrets.choice(chars) for _ in range(8))
    return f"BOT-{code}"


def create_bot_token(chat_id, plan_id="plan1"):
    """
    یه توکن جدید بساز و به کاربر اختصاص بده.
    توکن رو ادمین بعد از تایید اشتراک بهش میده.
    """
    token = generate_token()
    # مطمئن میشیم یکتاست
    while token in bot_tokens:
        token = generate_token()

    bot_tokens[token] = {
        "chat_id":    chat_id,
        "plan_id":    plan_id,
        "created_at": fmt_dt(),
        "used":       False,
        "bot_username": None,   # بعد از استفاده پر میشه
    }
    user_bot_tokens.setdefault(chat_id, []).append(token)
    return token


def use_bot_token(token_str, bot_username):
    """
    وقتی کاربر توکن رو وارد کرد و ربات رو ساخت،
    توکن رو به عنوان استفاده‌شده علامت بزن.
    """
    td = bot_tokens.get(token_str)
    if not td:
        return False, "توکن نامعتبر است"
    if td["used"]:
        return False, "این توکن قبلاً استفاده شده"
    td["used"]         = True
    td["bot_username"] = bot_username
    td["used_at"]      = fmt_dt()
    return True, "ok"


# ══════════════════════════════════════════════
#  کیبوردها
# ══════════════════════════════════════════════
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📨 ارسال پیام به ادمین", callback_data="goto_send")],
        [InlineKeyboardButton("🛒 خرید اشتراک",         callback_data="show_plans")],
        [InlineKeyboardButton("👤 حساب من",             callback_data="my_account")],
        [InlineKeyboardButton("🤖 ربات من",             callback_data="my_bots")],   # 🆕
        [InlineKeyboardButton("⚙️ تنظیمات",             callback_data="open_settings")],
    ]
    return InlineKeyboardMarkup(keyboard)


def mode_selection_keyboard():
    keyboard = [
        [InlineKeyboardButton("👤 با اسم (عادی)",  callback_data="set_mode_normal")],
        [InlineKeyboardButton("🕵️ ناشناس",          callback_data="set_mode_anonymous")],
    ]
    return InlineKeyboardMarkup(keyboard)


def priority_keyboard(chat_id):
    coins = get_coins(chat_id)
    keyboard = [
        [InlineKeyboardButton("🟢 عادی (رایگان)",   callback_data="priority_normal")],
        [InlineKeyboardButton("🟡 ویژه (۱۰ سکه)",   callback_data="priority_vip")],
        [InlineKeyboardButton("🔴 فوری (۳۰ سکه)",   callback_data="priority_urgent")],
        [InlineKeyboardButton(f"💰 موجودی: {coins} سکه", callback_data="noop")],
    ]
    return InlineKeyboardMarkup(keyboard)


def plans_keyboard():
    keyboard = []
    for pid, plan in subscription_plans.items():
        keyboard.append([InlineKeyboardButton(
            f"⭐ {plan['name']} — {plan['price']} ({plan['days']} روز)",
            callback_data=f"buy_{pid}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(keyboard)


def admin_panel_keyboard():
    status = "🟢 روشن" if bot_state["active"] else "🔴 خاموش"
    keyboard = [
        [InlineKeyboardButton("👥 لیست کاربران",         callback_data="list_users")],
        [InlineKeyboardButton("🚫 لیست بلاک‌شده‌ها",    callback_data="list_blocked")],
        [InlineKeyboardButton("📊 آمار",                  callback_data="stats")],
        [InlineKeyboardButton("📢 پیام همگانی",           callback_data="broadcast")],
        [InlineKeyboardButton("👥 پیام به گروه",          callback_data="send_group")],
        [InlineKeyboardButton("🗳 ساخت نظرسنجی",          callback_data="create_poll")],
        [InlineKeyboardButton("💰 مدیریت سکه",            callback_data="manage_coins")],
        [InlineKeyboardButton("🛒 مدیریت اشتراک‌ها",     callback_data="manage_subs")],
        [InlineKeyboardButton("🧾 رسیدهای در انتظار",    callback_data="pending_receipts_admin")],
        [InlineKeyboardButton("💳 تنظیم شماره کارت",      callback_data="set_card")],
        # ── 🆕 دکمه‌های جدید ──────────────────────
        [InlineKeyboardButton("🤖 مدیریت توکن ربات‌سازی", callback_data="manage_tokens")],
        [InlineKeyboardButton(f"⚡ وضعیت ربات: {status}", callback_data="toggle_bot")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ══════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = update.effective_chat.id

    if update.effective_chat.type != "private":
        return
    if chat_id == ADMIN_CHAT_ID:
        await panel(update, context)
        return

    # ── 🆕 بررسی وضعیت ربات — اگه خاموشه هیچکاری نکن ──
    if not bot_state["active"]:
        await update.message.reply_text(
            "⛔ *ربات در حال حاضر غیرفعال است.*\n\n"
            "لطفاً بعداً مراجعه کنید.",
            parse_mode="Markdown"
        )
        return

    # ── ثبت کاربر در دیتابیس ──
    users_db[chat_id] = {
        "name":     user.full_name,
        "username": user.username or "ندارد",
        "chat_id":  chat_id
    }

    # ── 🆕 ساخت/آپدیت پروفایل ──
    ensure_profile(chat_id)
    update_last_seen(chat_id)

    if chat_id not in user_mode:
        await update.message.reply_text(
            "👋 *سلام!*\n\n"
            "قبل از شروع، نحوه نمایش هویتت رو انتخاب کن:\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "👤 *با اسم* — ادمین اسم و پروفایلت رو میبینه\n"
            "🕵️ *ناشناس* — هیچ اطلاعاتی از تو نمیفرسته\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "💡 هر وقت خواستی از /settings میتونی تغییرش بدی.",
            parse_mode="Markdown",
            reply_markup=mode_selection_keyboard()
        )
    else:
        sub_status = subscription_status_text(chat_id)
        current    = "🕵️ ناشناس" if user_mode[chat_id] == "anonymous" else "👤 عادی"
        await update.message.reply_text(
            f"👋 *سلام {user.first_name}!*\n\n"
            f"حالت ارسال: {current}\n"
            f"اشتراک: {sub_status}\n\n"
            "از منوی زیر ادامه بده 👇",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )


# ══════════════════════════════════════════════
#  /panel — پنل ادمین
# ══════════════════════════════════════════════
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=admin_panel_keyboard()
    )


# ══════════════════════════════════════════════
#  /settings
# ══════════════════════════════════════════════
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type != "private" or chat_id == ADMIN_CHAT_ID:
        return

    current = user_mode.get(chat_id)
    if current == "anonymous":
        status_text = "🕵️ *ناشناس* (فعال)"
    elif current == "normal":
        status_text = "👤 *عادی* (فعال)"
    else:
        status_text = "❓ هنوز انتخاب نشده"

    await update.message.reply_text(
        "⚙️ *تنظیمات ارسال پیام*\n\n"
        f"حالت فعلی: {status_text}\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "👤 *عادی* — اسم و پروفایلت برای ادمین نمایش داده میشه\n"
        "🕵️ *ناشناس* — هیچ اطلاعاتی از تو ارسال نمیشه\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "یه حالت انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=mode_selection_keyboard()
    )


# ══════════════════════════════════════════════
#  فوروارد پیام به ادمین
# ══════════════════════════════════════════════
async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = update.effective_chat.id

    if update.effective_chat.type != "private":
        return
    if chat_id == ADMIN_CHAT_ID:
        return
    if chat_id in blocked_users:
        await update.message.reply_text("⛔ شما مسدود شده‌اید.")
        return

    # ── 🆕 خاموشی کامل — هر نوع دسترسی قطع میشه ──
    if not bot_state["active"]:
        await update.message.reply_text(
            "⛔ *ربات در حال حاضر غیرفعال است.*\n\n"
            "لطفاً بعداً مراجعه کنید.",
            parse_mode="Markdown"
        )
        return

    # ── 🆕 آپدیت آخرین فعالیت ──
    update_last_seen(chat_id)

    # انتظار دریافت رسید
    if chat_id in pending_receipt_input:
        if not (update.message.photo or update.message.document):
            await update.message.reply_text(
                "📸 لطفاً *تصویر* رسید پرداخت رو ارسال کن.",
                parse_mode="Markdown"
            )
            return
        pending_receipt_input.discard(chat_id)
        receipt_info = pending_receipts.get(chat_id)
        if not receipt_info:
            await update.message.reply_text("❌ خطایی پیش اومد. دوباره از /start شروع کن.")
            return

        plan = subscription_plans.get(receipt_info["plan"], {})
        user_info = users_db.get(chat_id, {"name": str(chat_id), "username": "ندارد"})

        # ارسال رسید به ادمین با دکمه تایید/رد
        keyboard = [
            [
                InlineKeyboardButton("✅ تایید و فعال‌سازی", callback_data=f"approve_sub_{chat_id}::{receipt_info['plan']}"),
                InlineKeyboardButton("❌ رد کردن",           callback_data=f"reject_sub_{chat_id}"),
            ]
        ]
        caption = (
            f"🧾 *رسید پرداخت جدید*\n\n"
            f"👤 کاربر: {user_info['name']}\n"
            f"🆔 Chat ID: `{chat_id}`\n"
            f"📦 پلن: {plan.get('name','؟')} ({plan.get('price','؟')})\n"
            f"📅 مدت: {plan.get('days','؟')} روز\n"
            f"⏰ زمان: {fmt_dt()}"
        )
        try:
            if update.message.photo:
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=update.message.photo[-1].file_id,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await context.bot.send_document(
                    chat_id=ADMIN_CHAT_ID,
                    document=update.message.document.file_id,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            await update.message.reply_text(
                "✅ *رسید شما دریافت شد!*\n\n"
                "ادمین در اسرع وقت بررسی و اشتراکت رو فعال می‌کنه.\n"
                "⏳ معمولاً کمتر از چند ساعت طول می‌کشه.",
                parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ خطا در ارسال رسید. دوباره امتحان کن.")
        return

    # ── 🆕 بررسی ورود توکن ربات ──────────────────
    if chat_id in user_submitting_token:
        token_str = update.message.text.strip() if update.message.text else ""
        if not token_str:
            await update.message.reply_text("❌ توکن نامعتبر است. لطفاً توکن متنی ارسال کن.")
            return
        user_submitting_token.discard(chat_id)

        # بررسی اینکه توکن متعلق به همین کاربر باشه
        td = bot_tokens.get(token_str)
        if not td:
            await update.message.reply_text(
                "❌ *توکن نامعتبر است!*\n\nاگه مشکل داری با ادمین تماس بگیر.",
                parse_mode="Markdown"
            )
            return
        if td["chat_id"] != chat_id:
            await update.message.reply_text("❌ این توکن متعلق به شما نیست.")
            return
        if td["used"]:
            await update.message.reply_text(
                f"⚠️ این توکن قبلاً استفاده شده.\n🤖 ربات: @{td.get('bot_username','؟')}",
                parse_mode="Markdown"
            )
            return

        # درخواست یوزرنیم ربات
        context.user_data["pending_token"] = token_str
        await update.message.reply_text(
            "✅ *توکن معتبر است!*\n\n"
            "🤖 حالا یوزرنیم ربات تلگرامی که ساختی رو بفرست:\n"
            "(مثلاً: `@MyAwesomeBot`)\n\n"
            "📌 اگه هنوز ربات نساختی از @BotFather اقدام کن.",
            parse_mode="Markdown"
        )
        return

    # ── 🆕 دریافت یوزرنیم ربات بعد از توکن ──────
    if context.user_data.get("pending_token"):
        bot_username = update.message.text.strip() if update.message.text else ""
        if not bot_username:
            await update.message.reply_text("❌ یوزرنیم معتبر نیست.")
            return
        token_str = context.user_data.pop("pending_token")
        ok, msg   = use_bot_token(token_str, bot_username)
        if ok:
            await update.message.reply_text(
                f"🎉 *ربات شما ثبت شد!*\n\n"
                f"🤖 یوزرنیم: {bot_username}\n"
                f"🔑 توکن: `{token_str}`\n\n"
                f"ادمین از ثبت ربات شما باخبر شد.\n"
                f"در صورت نیاز به راه‌اندازی، با ادمین تماس بگیر. 🙏",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
            # اطلاع به ادمین
            info = users_db.get(chat_id, {"name": str(chat_id)})
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=(
                        f"🤖 *ربات جدید ثبت شد!*\n\n"
                        f"👤 کاربر: {info['name']} | `{chat_id}`\n"
                        f"🔑 توکن: `{token_str}`\n"
                        f"🤖 یوزرنیم ربات: {bot_username}\n"
                        f"⏰ زمان: {fmt_dt()}"
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        else:
            await update.message.reply_text(f"❌ خطا: {msg}")
        return

    # اگه هنوز حالت انتخاب نکرده
    if chat_id not in user_mode:
        await update.message.reply_text(
            "⚠️ قبل از ارسال پیام، لطفاً حالت ارسالت رو انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=mode_selection_keyboard()
        )
        return

    users_db[chat_id] = {
        "name":     user.full_name,
        "username": user.username or "ندارد",
        "chat_id":  chat_id
    }

    # 🆕 شمارش پیام
    increment_msg(chat_id)

    # پیام متنی → انتخاب اولویت
    if update.message.text:
        context.user_data["pending_text"] = update.message.text
        await update.message.reply_text(
            "📨 پیامت آماده ارسال شد!\n\n"
            "با چه اولویتی ارسال شه؟\n\n"
            "🟢 *عادی* — رایگان\n"
            "🟡 *ویژه* — ۱۰ سکه\n"
            "🔴 *فوری* — ۳۰ سکه",
            parse_mode="Markdown",
            reply_markup=priority_keyboard(chat_id)
        )
        return

    # پیام غیرمتنی → مستقیم ارسال با اولویت عادی
    await send_user_message(context, chat_id, user, priority="normal",
                             text=None, original_message=update.message,
                             confirm_target=update.message)


# ══════════════════════════════════════════════
#  ارسال نهایی پیام کاربر به ادمین
# ══════════════════════════════════════════════
async def send_user_message(context, chat_id, user, priority="normal",
                             text=None, original_message=None, confirm_target=None):
    level    = PRIORITY_LEVELS[priority]
    priority_tag = ""
    if priority == "vip":
        priority_tag = "\n🟡 *پیام ویژه*"
    elif priority == "urgent":
        priority_tag = "\n🔴 *پیام فوری* ⚡️"

    is_anonymous = user_mode[chat_id] == "anonymous"
    sub_tag = " | ⭐ اشتراک فعال" if has_active_subscription(chat_id) else ""
    keyboard = [[
        InlineKeyboardButton("↩️ پاسخ",  callback_data=f"reply_{chat_id}"),
        InlineKeyboardButton("🚫 بلاک",  callback_data=f"block_{chat_id}"),
    ]]

    if is_anonymous:
        sender_info = (
            f"📩 *پیام جدید*{priority_tag}\n"
            f"🕵️ *ناشناس*{sub_tag}\n"
            f"🔢 Chat ID: `{chat_id}`\n"
            f"{'─' * 25}"
        )
    else:
        sender_info = (
            f"📩 *پیام جدید*{priority_tag}\n"
            f"👤 نام: {user.full_name}{sub_tag}\n"
            f"🆔 یوزرنیم: @{user.username if user.username else 'ندارد'}\n"
            f"🔢 Chat ID: `{chat_id}`\n"
            f"{'─' * 25}"
        )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=sender_info,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    if text is not None:
        fwd = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    elif is_anonymous:
        fwd = await original_message.copy_to(chat_id=ADMIN_CHAT_ID)
    else:
        fwd = await original_message.forward(chat_id=ADMIN_CHAT_ID)

    message_map[f"reply_{chat_id}"] = fwd.message_id

    if level["cost"] > 0:
        add_coins(chat_id, -level["cost"], f"ارسال پیام با اولویت {level['title']}")

    confirm_text = "✅ پیامت دریافت شد، به زودی جواب میگیری."
    if priority == "vip":
        confirm_text = "✅ پیام *ویژه*‌ت ارسال شد! 🟡 سریع‌تر بررسی میشه."
    elif priority == "urgent":
        confirm_text = "✅ پیام *فوری*‌ت ارسال شد! 🔴 در صدر لیست قرار گرفت."
    if is_anonymous:
        confirm_text += " 🕵️"

    if confirm_target is not None:
        await confirm_target.reply_text(confirm_text, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=chat_id, text=confirm_text, parse_mode="Markdown")


# ══════════════════════════════════════════════
#  ارسال نظرسنجی
# ══════════════════════════════════════════════
async def send_poll_to_target(context, poll_info, target):
    question = poll_info["question"]
    options  = poll_info["options"]

    if target == "all":
        success = 0
        for uid in users_db:
            if uid not in blocked_users:
                try:
                    sent = await context.bot.send_poll(
                        chat_id=uid,
                        question=question,
                        options=options,
                        is_anonymous=False    # برای نمایش نتیجه باید False باشه
                    )
                    poll_votes[sent.poll.id] = {
                        "question": question,
                        "options":  {i: 0 for i in range(len(options))},
                        "opt_names": options,
                        "total": 0
                    }
                    success += 1
                except Exception:
                    pass
        return success
    else:
        try:
            sent = await context.bot.send_poll(
                chat_id=target,
                question=question,
                options=options,
                is_anonymous=False
            )
            poll_votes[sent.poll.id] = {
                "question":  question,
                "options":   {i: 0 for i in range(len(options))},
                "opt_names": options,
                "total": 0
            }
            return 1
        except Exception:
            return 0


# ══════════════════════════════════════════════
#  هندلر پاسخ نظرسنجی
# ══════════════════════════════════════════════
async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer  = update.poll_answer
    poll_id = answer.poll_id
    options = answer.option_ids

    if poll_id not in poll_votes:
        poll_votes[poll_id] = {"question": "نظرسنجی", "options": {}, "opt_names": [], "total": 0}

    info = poll_votes[poll_id]
    info["total"] = info.get("total", 0) + 1
    for opt_id in options:
        info["options"][opt_id] = info["options"].get(opt_id, 0) + 1

    # ارسال آمار لحظه‌ای به ادمین
    total = info["total"]
    lines = [f"📊 *نتایج نظرسنجی* (تا این لحظه)\n❓ {info['question']}\n"]
    for i, name in enumerate(info.get("opt_names", [])):
        count = info["options"].get(i, 0)
        pct   = round(count / total * 100) if total else 0
        bar   = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"• {name}\n  {bar} {pct}% ({count} نفر)")
    lines.append(f"\n👥 مجموع شرکت‌کنندگان: {total}")

    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text="\n".join(lines),
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ══════════════════════════════════════════════
#  هندلر دکمه‌ها
# ══════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    data    = query.data
    chat_id = query.message.chat.id

    await query.answer()

    # ── بی‌اثر ───────────────────────────────
    if data == "noop":
        return

    # ── انتخاب حالت توسط کاربر ───────────────
    if data in ("set_mode_normal", "set_mode_anonymous"):
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        if data == "set_mode_normal":
            user_mode[user_chat_id] = "normal"
            await query.edit_message_text(
                "✅ *حالت عادی فعال شد!*\n\n"
                "👤 اسم و پروفایلت همراه پیامت ارسال میشه.\n\n"
                "از منوی زیر ادامه بده 👇",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        else:
            user_mode[user_chat_id] = "anonymous"
            await query.edit_message_text(
                "✅ *حالت ناشناس فعال شد!*\n\n"
                "🕵️ هیچ اطلاعاتی از تو ارسال نمیشه.\n\n"
                "از منوی زیر ادامه بده 👇",
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        return

    # ── منوی اصلی کاربر ──────────────────────
    if data == "back_main":
        user_chat_id = query.from_user.id
        sub_status   = subscription_status_text(user_chat_id)
        current      = "🕵️ ناشناس" if user_mode.get(user_chat_id) == "anonymous" else "👤 عادی"
        await query.edit_message_text(
            f"🏠 *منوی اصلی*\n\n"
            f"حالت ارسال: {current}\n"
            f"اشتراک: {sub_status}\n\n"
            "یه گزینه انتخاب کن 👇",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
        return

    if data == "goto_send":
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        if not bot_state["active"]:
            await query.edit_message_text("⚠️ ربات در حال حاضر غیرفعال است.")
            return
        await query.edit_message_text(
            "📨 *ارسال پیام به ادمین*\n\n"
            "پیامت رو بنویس و ارسال کن 👇\n\n"
            "(متن، عکس، فایل — همه پذیرفته میشه)",
            parse_mode="Markdown"
        )
        return

    if data == "open_settings":
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        current = user_mode.get(user_chat_id)
        if current == "anonymous":
            status_text = "🕵️ *ناشناس*"
        elif current == "normal":
            status_text = "👤 *عادی*"
        else:
            status_text = "❓ هنوز انتخاب نشده"
        await query.edit_message_text(
            "⚙️ *تنظیمات*\n\n"
            f"حالت فعلی: {status_text}\n\n"
            "یه حالت انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=mode_selection_keyboard()
        )
        return

    if data == "my_account":
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        coins  = get_coins(user_chat_id)
        sub    = subscription_status_text(user_chat_id)
        mode   = "🕵️ ناشناس" if user_mode.get(user_chat_id) == "anonymous" else "👤 عادی"
        history_lines = user_history.get(user_chat_id, [])
        history_text  = "\n".join(history_lines[-5:]) if history_lines else "ندارید"
        p = ensure_profile(user_chat_id)
        await query.edit_message_text(
            f"👤 *حساب من*\n\n"
            f"💰 موجودی سکه: {coins}\n"
            f"🔐 حالت ارسال: {mode}\n"
            f"📦 اشتراک: {sub}\n"
            f"📨 تعداد پیام‌های ارسالی: {p.get('msg_count', 0)}\n"
            f"📅 عضویت: {p.get('join_date','؟')}\n\n"
            f"📋 *آخرین تراکنش‌های سکه:*\n{history_text}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="back_main")]])
        )
        return

    # ── 🆕 ربات من (سیستم توکن) ──────────────
    if data == "my_bots":
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        tokens = user_bot_tokens.get(user_chat_id, [])
        has_sub = has_active_subscription(user_chat_id)

        if not tokens:
            if has_sub:
                # اشتراک داره ولی هنوز توکن نگرفته — باید از ادمین بخواد
                msg = (
                    "🤖 *ربات من*\n\n"
                    "✅ اشتراک شما فعال است.\n\n"
                    "برای دریافت توکن ربات‌سازی، به ادمین پیام بده\n"
                    "و درخواست توکن کن."
                )
            else:
                # اشتراک نداره
                msg = (
                    "🤖 *ربات من*\n\n"
                    "شما هنوز توکنی دریافت نکرده‌اید.\n\n"
                    "برای دریافت توکن ربات‌سازی، ابتدا اشتراک خریداری کنید\n"
                    "و سپس از ادمین درخواست توکن کنید."
                )
            await query.edit_message_text(
                msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📨 پیام به ادمین", callback_data="goto_send")],
                    [InlineKeyboardButton("🛒 خرید اشتراک",  callback_data="show_plans")],
                    [InlineKeyboardButton("🔙 برگشت",         callback_data="back_main")],
                ])
            )
            return

        text = "🤖 *ربات‌های من*\n\n"
        kb   = []
        for t in tokens:
            td = bot_tokens.get(t, {})
            if td.get("used"):
                status = f"✅ فعال — @{td.get('bot_username','؟')}"
            else:
                status = "⏳ استفاده نشده"
            text += f"🔑 `{t}`\n   {status}\n\n"

        # اگه توکن استفاده‌نشده دارن، دکمه وارد کردن توکن نشون بده
        has_unused = any(not bot_tokens.get(t, {}).get("used") for t in tokens)
        if has_unused:
            kb.append([InlineKeyboardButton("🔑 وارد کردن توکن", callback_data="submit_token")])
        kb.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_main")])

        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "submit_token":
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        user_submitting_token.add(user_chat_id)
        await query.edit_message_text(
            "🔑 *وارد کردن توکن ربات‌سازی*\n\n"
            "توکنی که از ادمین دریافت کردی رو اینجا بفرست:\n"
            "(مثلاً: `BOT-A3X9K2AB`)\n\n"
            "⚠️ هر توکن فقط یک بار قابل استفاده است.",
            parse_mode="Markdown"
        )
        return

    # ── نمایش پلن‌ها ──────────────────────────
    if data == "show_plans":
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        # اگه قبلاً توی فرآیند خرید بود، پاکش کن
        pending_receipt_input.discard(user_chat_id)
        pending_receipts.pop(user_chat_id, None)

        text = (
            "🛒 *خرید اشتراک*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"

            "✨ *با خرید اشتراک به این امکانات دسترسی داری:*\n\n"

            "🤖 *ربات اختصاصی*\n"
            "   یه ربات تلگرامی کاملاً مخصوص خودت بساز\n"
            "   و زیر برند شخصی‌ات استفاده کن\n\n"

            "🔑 *توکن ربات‌سازی*\n"
            "   بعد از فعال‌سازی اشتراک، یه توکن یکتا\n"
            "   دریافت می‌کنی و ربات رو با یه کلیک ثبت می‌کنی\n\n"

            "📨 *ارسال پیام اولویت‌دار*\n"
            "   پیام‌هات با اولویت ویژه 🟡 و فوری 🔴\n"
            "   سریع‌تر بررسی و پاسخ داده میشه\n\n"

            "💰 *سکه رایگان*\n"
            "   با هر اشتراک سکه هدیه برای استفاده\n"
            "   از قابلیت‌های پریمیوم ربات دریافت می‌کنی\n\n"

            "⭐ *نشان اشتراک فعال*\n"
            "   پیام‌هات با برچسب اشتراک‌دار نمایش داده\n"
            "   میشه — اولویت بیشتر، توجه بیشتر\n\n"

            "━━━━━━━━━━━━━━━━━━\n"
            "📦 *پلن‌های موجود:*\n\n"
        )
        for pid, plan in subscription_plans.items():
            text += f"⭐ *{plan['name']}* — {plan['price']}\n📅 {plan['description']}\n\n"

        text += "👇 یه پلن انتخاب کن و شروع کن:"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=plans_keyboard())
        return

    # ── انتخاب پلن و نمایش شماره کارت ─────────
    if data.startswith("buy_"):
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        plan_id = data[4:]
        plan    = subscription_plans.get(plan_id)
        if not plan:
            return
        pending_receipts[user_chat_id] = {"plan": plan_id}
        pending_receipt_input.add(user_chat_id)
        keyboard = [
            [InlineKeyboardButton("✅ رسید پرداخت رو ارسال کردم", callback_data=f"sent_receipt_{plan_id}")],
            [InlineKeyboardButton("🔙 برگشت به پلن‌ها",           callback_data="show_plans")],
        ]
        await query.edit_message_text(
            f"💳 *اطلاعات پرداخت*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"📦 پلن انتخابی: *{plan['name']}*\n"
            f"💰 مبلغ: *{plan['price']}*\n"
            f"📅 مدت اشتراک: {plan['days']} روز\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💳 شماره کارت:\n`{bot_config['card_number']}`\n"
            f"👤 به نام: *{bot_config['card_owner']}*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"🤖 *بعد از فعال‌سازی اشتراک:*\n"
            f"یه توکن اختصاصی دریافت می‌کنی که باهاش\n"
            f"می‌تونی ربات تلگرامی شخصی خودت رو بسازی!\n\n"
            f"📸 بعد از پرداخت، *تصویر رسید* رو اینجا ارسال کن 👇\n"
            f"_(ادمین بررسی و اشتراکت رو فعال می‌کنه)_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 انصراف", callback_data="show_plans")]])
        )
        return

    if data.startswith("sent_receipt_"):
        user_chat_id = query.from_user.id
        await query.edit_message_text(
            "📸 تصویر رسید پرداختت رو ارسال کن 👇",
            parse_mode="Markdown"
        )
        return

    # ── تایید اشتراک توسط ادمین ─────────────
    if data.startswith("approve_sub_"):
        if chat_id != ADMIN_CHAT_ID:
            return
        # approve_sub_{chat_id}::{plan_id}
        payload   = data[len("approve_sub_"):]
        target_id_str, plan_id = payload.split("::", 1)
        target_id = int(target_id_str)
        plan      = subscription_plans.get(plan_id, {})
        expires   = now_tehran() + timedelta(days=plan.get("days", 30))
        user_subscriptions[target_id] = {"plan": plan_id, "expires": expires}
        pending_receipts.pop(target_id, None)
        pending_receipt_input.discard(target_id)

        # آپدیت کپشن پیام رسید (هم photo هم document پشتیبانی میشه)
        approved_suffix = f"\n\n✅ *تایید شد* توسط ادمین — {now_tehran().strftime('%H:%M')}"
        try:
            if query.message.caption is not None:
                await query.edit_message_caption(
                    caption=query.message.caption + approved_suffix,
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    text=(query.message.text or "") + approved_suffix,
                    parse_mode="Markdown"
                )
        except Exception:
            await query.answer("✅ اشتراک تایید شد.")

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🎉 *اشتراک شما فعال شد!*\n\n"
                    f"📦 پلن: *{plan.get('name','؟')}*\n"
                    f"📅 تاریخ انقضا: {expires.strftime('%Y-%m-%d')} ساعت {expires.strftime('%H:%M')} (تهران)\n\n"
                    f"ممنون که ما رو انتخاب کردید 🙏"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        except Exception:
            pass
        return

    # ── رد اشتراک توسط ادمین ────────────────
    if data.startswith("reject_sub_"):
        if chat_id != ADMIN_CHAT_ID:
            return
        target_id = int(data[len("reject_sub_"):])
        pending_receipts.pop(target_id, None)
        pending_receipt_input.discard(target_id)

        rejected_suffix = f"\n\n❌ *رد شد* توسط ادمین — {now_tehran().strftime('%H:%M')}"
        try:
            if query.message.caption is not None:
                await query.edit_message_caption(
                    caption=query.message.caption + rejected_suffix,
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text(
                    text=(query.message.text or "") + rejected_suffix,
                    parse_mode="Markdown"
                )
        except Exception:
            await query.answer("❌ رسید رد شد.")

        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    "❌ *رسید پرداخت تایید نشد.*\n\n"
                    "ممکنه مبلغ، شماره کارت یا رسید مشکل داشته باشه.\n"
                    "در صورت نیاز با ادمین تماس بگیر."
                ),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # ── انتخاب اولویت پیام ───────────────────
    if data in ("priority_normal", "priority_vip", "priority_urgent"):
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        priority = data.split("_")[1]
        level    = PRIORITY_LEVELS[priority]
        coins    = get_coins(user_chat_id)

        if level["cost"] > coins:
            await query.answer(f"❌ سکه کافی نداری! ({coins}/{level['cost']})", show_alert=True)
            return

        pending_text = context.user_data.get("pending_text")
        if not pending_text:
            await query.edit_message_text("⚠️ پیام منقضی شده، لطفاً دوباره ارسال کن.")
            return

        user = query.from_user
        await send_user_message(context, user_chat_id, user, priority=priority, text=pending_text)
        context.user_data.pop("pending_text", None)
        await query.edit_message_reply_markup(reply_markup=None)
        return

    # ── دکمه‌های ادمین ───────────────────────
    if chat_id != ADMIN_CHAT_ID:
        return

    # پاسخ به کاربر
    if data.startswith("reply_"):
        target_id = int(data.split("_")[1])
        reply_to[ADMIN_CHAT_ID] = target_id
        user_info = users_db.get(target_id, {})
        name = user_info.get("name", "ناشناس") if user_mode.get(target_id) != "anonymous" else "🕵️ ناشناس"
        await query.message.reply_text(
            f"✍️ پیامت رو بنویس، برای *{name}* ارسال میشه.",
            parse_mode="Markdown"
        )
        return

    # بلاک/آنبلاک
    if data.startswith("block_"):
        target_id = int(data.split("_")[1])
        blocked_users.add(target_id)
        user_info = users_db.get(target_id, {})
        # 🆕 ثبت در سابقه بلاک
        p = ensure_profile(target_id)
        p.setdefault("block_history", []).append(f"🚫 بلاک شد — {fmt_dt()}")
        await query.message.reply_text(f"🚫 کاربر *{user_info.get('name', target_id)}* بلاک شد.", parse_mode="Markdown")
        return

    if data.startswith("unblock_"):
        target_id = int(data.split("_")[1])
        blocked_users.discard(target_id)
        user_info = users_db.get(target_id, {})
        # 🆕 ثبت در سابقه بلاک
        p = ensure_profile(target_id)
        p.setdefault("block_history", []).append(f"✅ آنبلاک شد — {fmt_dt()}")
        await query.message.reply_text(f"✅ کاربر *{user_info.get('name', target_id)}* آنبلاک شد.", parse_mode="Markdown")
        return

    # لیست کاربران
    if data == "list_users":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری.")
            return
        text     = "👥 *لیست کاربران:*\n\n"
        keyboard = []
        for uid, info in users_db.items():
            blocked  = "🚫" if uid in blocked_users else "✅"
            mode_tag = "🕵️" if user_mode.get(uid) == "anonymous" else "👤"
            coins    = get_coins(uid)
            sub_tag  = "⭐" if has_active_subscription(uid) else ""
            p        = ensure_profile(uid)
            text    += f"{blocked}{mode_tag}{sub_tag} {info['name']} | @{info['username']} | `{uid}` | 💰{coins} | 📨{p.get('msg_count',0)}\n"
            keyboard.append([
                InlineKeyboardButton(f"👁 {info['name']}",  callback_data=f"full_profile_{uid}"),
                InlineKeyboardButton("↩️ پاسخ",             callback_data=f"reply_{uid}"),
                InlineKeyboardButton("🚫" if uid not in blocked_users else "✅ آنبلاک",
                                     callback_data=f"{'block' if uid not in blocked_users else 'unblock'}_{uid}"),
            ])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "list_blocked":
        if not blocked_users:
            await query.message.reply_text("🚫 هیچ کاربری بلاک نشده.")
            return
        text     = "🚫 *کاربران بلاک‌شده:*\n\n"
        keyboard = []
        for uid in blocked_users:
            info  = users_db.get(uid, {"name": str(uid), "username": "ندارد"})
            text += f"🚫 {info['name']} | @{info['username']} | `{uid}`\n"
            keyboard.append([InlineKeyboardButton(f"✅ آنبلاک {info['name']}", callback_data=f"unblock_{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "stats":
        total    = len(users_db)
        blocked  = len(blocked_users)
        active   = total - blocked
        anon     = sum(1 for uid in users_db if user_mode.get(uid) == "anonymous")
        normal   = sum(1 for uid in users_db if user_mode.get(uid) == "normal")
        with_sub = sum(1 for uid in users_db if has_active_subscription(uid))
        text = (
            f"📊 *آمار ربات*\n\n"
            f"👥 کل کاربران: {total}\n"
            f"✅ فعال: {active}\n"
            f"🚫 بلاک‌شده: {blocked}\n"
            f"⭐ دارای اشتراک: {with_sub}\n"
            f"━━━━━━━━━━━━\n"
            f"🕵️ ناشناس: {anon}\n"
            f"👤 عادی: {normal}\n"
            f"━━━━━━━━━━━━\n"
            f"⚡ وضعیت ربات: {'🟢 روشن' if bot_state["active"] else '🔴 خاموش'}"
        )
        await query.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="back")]]))
        return

    if data == "broadcast":
        reply_to[ADMIN_CHAT_ID] = "broadcast"
        await query.message.reply_text("📢 پیام همگانیت رو بنویس:")
        return

    if data == "send_group":
        group_mode[ADMIN_CHAT_ID] = "waiting_id"
        await query.message.reply_text(
            "👥 *ارسال به گروه*\n\nآیدی عددی گروه رو بفرست:\n(مثلاً: `-1001234567890`)",
            parse_mode="Markdown"
        )
        return

    if data == "back":
        await query.message.reply_text(
            "🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard()
        )
        return

    # ── نظرسنجی ──────────────────────────────
    if data == "create_poll":
        pending_poll[ADMIN_CHAT_ID] = {"step": "question"}
        await query.message.reply_text(
            "🗳 *ساخت نظرسنجی*\n\nسوال نظرسنجی رو بنویس:",
            parse_mode="Markdown"
        )
        return

    if data == "poll_target_all":
        info = pending_poll.get(ADMIN_CHAT_ID)
        if not info:
            return
        success = await send_poll_to_target(context, info, "all")
        del pending_poll[ADMIN_CHAT_ID]
        await query.message.reply_text(f"✅ نظرسنجی برای {success} کاربر ارسال شد.\n\n📊 نتایج به محض پاسخ کاربران برات ارسال میشه.")
        return

    if data == "poll_target_group":
        info = pending_poll.get(ADMIN_CHAT_ID)
        if not info:
            return
        info["step"] = "waiting_group_id"
        await query.message.reply_text("👥 آیدی عددی گروه رو بفرست:\n(مثلاً `-1001234567890`)", parse_mode="Markdown")
        return

    # ── مدیریت سکه ───────────────────────────
    if data == "manage_coins":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری.")
            return
        text     = "💰 *مدیریت سکه کاربران*\n\n"
        keyboard = []
        for uid, info in users_db.items():
            coins = get_coins(uid)
            text += f"👤 {info['name']} | `{uid}` | 💰 {coins}\n"
            keyboard.append([InlineKeyboardButton(f"💰 {info['name']} ({coins} سکه)", callback_data=f"addcoin_{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("addcoin_"):
        target_id = int(data.split("_")[1])
        pending_coin_add[ADMIN_CHAT_ID] = target_id
        info  = users_db.get(target_id, {"name": str(target_id)})
        coins = get_coins(target_id)
        await query.message.reply_text(
            f"💰 *افزودن/کاهش سکه*\n\n"
            f"کاربر: {info['name']} | `{target_id}`\n"
            f"موجودی فعلی: {coins} سکه\n\n"
            f"یه عدد بفرست (مثبت یا منفی، مثلاً `20` یا `-10`):",
            parse_mode="Markdown"
        )
        return

    # ── مدیریت اشتراک‌ها ─────────────────────
    if data == "manage_subs":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری.")
            return
        text     = "🛒 *مدیریت اشتراک‌ها*\n\n"
        keyboard = []
        for uid, info in users_db.items():
            sub_text = subscription_status_text(uid)
            text    += f"👤 {info['name']} | {sub_text}\n"
            keyboard.append([
                InlineKeyboardButton(f"⭐ {info['name']}", callback_data=f"sub_manage_{uid}"),
            ])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("sub_manage_"):
        target_id = int(data[len("sub_manage_"):])
        info      = users_db.get(target_id, {"name": str(target_id)})
        sub_text  = subscription_status_text(target_id)
        plan_keyboard = []
        for pid, plan in subscription_plans.items():
            plan_keyboard.append([InlineKeyboardButton(
                f"➕ اضافه کن: {plan['name']} ({plan['days']} روز)",
                callback_data=f"admin_add_sub_{target_id}__{pid}"
            )])
        plan_keyboard.append([InlineKeyboardButton("🗑 لغو اشتراک", callback_data=f"admin_del_sub_{target_id}")])
        plan_keyboard.append([InlineKeyboardButton("🔙 برگشت",      callback_data="manage_subs")])
        await query.message.reply_text(
            f"👤 *{info['name']}*\n\nاشتراک فعلی: {sub_text}\n\nیه عملیات انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(plan_keyboard)
        )
        return

    if data.startswith("admin_add_sub_"):
        # فرمت: admin_add_sub_{target_id}__{plan_id}  (دو آندرلاین بین id و plan)
        payload   = data[len("admin_add_sub_"):]
        target_id_str, plan_id = payload.split("__", 1)
        target_id = int(target_id_str)
        plan      = subscription_plans.get(plan_id, {})
        current   = user_subscriptions.get(target_id, {})
        # اگه اشتراک فعال دارن، اضافه کن؛ وگرنه از الان
        base      = current.get("expires", now_tehran())
        if base < now_tehran():
            base = now_tehran()
        expires   = base + timedelta(days=plan.get("days", 30))
        user_subscriptions[target_id] = {"plan": plan_id, "expires": expires}
        info = users_db.get(target_id, {"name": str(target_id)})
        await query.message.reply_text(
            f"✅ اشتراک *{plan.get('name','؟')}* برای *{info['name']}* فعال شد.\n"
            f"📅 انقضا: {expires.strftime('%Y-%m-%d')}",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(f"🎉 *اشتراک شما فعال شد!*\n\n"
                      f"📦 پلن: *{plan['name']}*\n"
                      f"📅 انقضا: {expires.strftime('%Y-%m-%d')} ساعت {expires.strftime('%H:%M')} (تهران)\n\n"
                      f"ممنون که ما رو انتخاب کردید 🙏"),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data.startswith("admin_del_sub_"):
        target_id = int(data[len("admin_del_sub_"):])
        user_subscriptions.pop(target_id, None)
        info = users_db.get(target_id, {"name": str(target_id)})
        await query.message.reply_text(f"🗑 اشتراک *{info['name']}* لغو شد.", parse_mode="Markdown")
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="⚠️ اشتراک شما توسط ادمین لغو شد."
            )
        except Exception:
            pass
        return

    # ── رسیدهای در انتظار ────────────────────
    if data == "pending_receipts_admin":
        if not pending_receipts:
            await query.message.reply_text("✅ رسید در انتظاری وجود نداره.")
            return
        text = "🧾 *رسیدهای در انتظار تایید:*\n\n"
        for uid, receipt in pending_receipts.items():
            info  = users_db.get(uid, {"name": str(uid)})
            plan  = subscription_plans.get(receipt["plan"], {})
            text += f"👤 {info['name']} | `{uid}` | پلن: {plan.get('name','؟')}\n"
        text += "\n⚠️ رسیدها به صورت تصویر ارسال میشن و باید از روی تصویر تایید/رد کنی."
        await query.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="back")]]))
        return

    # ── تنظیم شماره کارت ────────────────────
    if data == "set_card":
        if chat_id != ADMIN_CHAT_ID:
            return
        await query.message.reply_text(
            "💳 *تنظیم اطلاعات کارت بانکی*\n\n"
            f"شماره فعلی: `{bot_config['card_number']}`\n"
            f"نام فعلی: {bot_config['card_owner']}\n\n"
            "شماره کارت جدید رو بفرست (فقط اعداد، مثلاً `6037991312345678`):\n"
            "یا بنویس /cancel برای انصراف",
            parse_mode="Markdown"
        )
        context.bot_data["pending_card"] = "number"
        return

    # ── خاموش/روشن ربات ─────────────────────
    if data == "toggle_bot":
        bot_state["active"] = not bot_state["active"]
        status = "🟢 روشن شد" if bot_state["active"] else "🔴 خاموش شد"
        msg = "کاربران میتونن پیام بفرستن." if bot_state["active"] else "⛔ کاربران به هیچ چیزی دسترسی ندارن."
        await query.message.reply_text(
            f"⚡ *وضعیت ربات:* {status}\n\n{msg}",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard()
        )
        return

    # ══════════════════════════════════════════
    # 🆕 مدیریت توکن ربات‌سازی (ادمین)
    # ══════════════════════════════════════════
    if data == "manage_tokens":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری.")
            return
        text = (
            "🤖 *مدیریت توکن ربات‌سازی*\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "این بخش بهت اجازه میده به کاربرانی که اشتراک خریدن\n"
            "یه توکن یکتا بدی تا باهاش ربات بسازن.\n\n"
            "📌 *روند کار:*\n"
            "۱. کاربر اشتراک میخره و رسید میفرسته\n"
            "۲. تو اشتراک رو تایید میکنی\n"
            "۳. از اینجا بهش توکن میدی\n"
            "۴. کاربر توکن رو در ربات وارد میکنه\n"
            "۵. یوزرنیم ربات ثبت میشه\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "یه کاربر انتخاب کن:"
        )
        keyboard = []
        for uid, info in users_db.items():
            has_sub = "⭐" if has_active_subscription(uid) else "  "
            token_count = len(user_bot_tokens.get(uid, []))
            keyboard.append([InlineKeyboardButton(
                f"{has_sub} {info['name']} — {token_count} توکن",
                callback_data=f"token_for_{uid}"
            )])
        keyboard.append([InlineKeyboardButton("📋 همه توکن‌ها", callback_data="list_all_tokens")])
        keyboard.append([InlineKeyboardButton("🔙 برگشت",        callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("token_for_"):
        target_id = int(data[len("token_for_"):])
        info      = users_db.get(target_id, {"name": str(target_id)})
        tokens    = user_bot_tokens.get(target_id, [])
        sub_text  = subscription_status_text(target_id)

        token_lines = ""
        for t in tokens:
            td = bot_tokens.get(t, {})
            if td.get("used"):
                token_lines += f"  ✅ `{t}` — @{td.get('bot_username','؟')}\n"
            else:
                token_lines += f"  ⏳ `{t}` — استفاده نشده\n"
        if not token_lines:
            token_lines = "  — توکنی ندارد\n"

        keyboard = [
            [InlineKeyboardButton("🆕 صدور توکن جدید",     callback_data=f"issue_token_{target_id}")],
            [InlineKeyboardButton("👁 پروفایل کامل",        callback_data=f"full_profile_{target_id}")],
            [InlineKeyboardButton("🔙 برگشت",               callback_data="manage_tokens")],
        ]
        await query.message.reply_text(
            f"🤖 *توکن‌های {info['name']}*\n\n"
            f"📦 اشتراک: {sub_text}\n\n"
            f"🔑 توکن‌ها:\n{token_lines}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("issue_token_"):
        target_id = int(data[len("issue_token_"):])
        info      = users_db.get(target_id, {"name": str(target_id)})
        # بررسی اشتراک فعال
        if not has_active_subscription(target_id):
            await query.message.reply_text(
                f"⚠️ *{info['name']}* اشتراک فعال ندارد!\n\n"
                "آیا مطمئنی میخوای توکن بدی؟",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ بله، صادر کن",   callback_data=f"confirm_issue_{target_id}")],
                    [InlineKeyboardButton("❌ خیر",             callback_data=f"token_for_{target_id}")],
                ])
            )
            return
        # صدور توکن
        token = create_bot_token(target_id)
        await query.message.reply_text(
            f"✅ *توکن جدید صادر شد!*\n\n"
            f"👤 کاربر: {info['name']} | `{target_id}`\n"
            f"🔑 توکن: `{token}`\n"
            f"⏰ زمان: {fmt_dt()}\n\n"
            f"📤 ارسال توکن به کاربر...",
            parse_mode="Markdown"
        )
        # ارسال توکن به کاربر
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🎉 *توکن ربات‌سازی شما صادر شد!*\n\n"
                    f"🔑 توکن اختصاصی شما:\n`{token}`\n\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📌 *راهنمای استفاده:*\n"
                    f"۱. از @BotFather یه ربات جدید بساز\n"
                    f"۲. به منوی «🤖 ربات من» برو\n"
                    f"۳. روی «🔑 وارد کردن توکن» کلیک کن\n"
                    f"۴. توکن بالا رو کپی و ارسال کن\n"
                    f"۵. یوزرنیم ربات جدیدت رو وارد کن\n\n"
                    f"⚠️ این توکن فقط یک بار قابل استفاده است.\n"
                    f"⚠️ توکن را به کسی ندهید!"
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🤖 ربات من", callback_data="my_bots")
                ]])
            )
            await query.message.reply_text("✅ توکن با موفقیت به کاربر ارسال شد.")
        except Exception as e:
            await query.message.reply_text(f"⚠️ توکن صادر شد ولی ارسال به کاربر ناموفق بود:\n{e}")
        return

    if data.startswith("confirm_issue_"):
        target_id = int(data[len("confirm_issue_"):])
        info      = users_db.get(target_id, {"name": str(target_id)})
        token     = create_bot_token(target_id)
        await query.message.reply_text(
            f"✅ توکن `{token}` برای *{info['name']}* صادر شد (بدون اشتراک).",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🎉 *توکن ربات‌سازی شما صادر شد!*\n\n"
                    f"🔑 توکن: `{token}`\n\n"
                    f"برای استفاده به منوی «🤖 ربات من» برو."
                ),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data == "list_all_tokens":
        if not bot_tokens:
            await query.message.reply_text("🔑 هیچ توکنی صادر نشده.")
            return
        text = "📋 *همه توکن‌های صادرشده:*\n\n"
        for t, td in bot_tokens.items():
            info = users_db.get(td["chat_id"], {"name": str(td["chat_id"])})
            status = f"✅ @{td['bot_username']}" if td.get("used") else "⏳ استفاده نشده"
            text += f"🔑 `{t}`\n👤 {info['name']} | {status}\n\n"
        await query.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="manage_tokens")]])
        )
        return

    # ══════════════════════════════════════════
    # 🆕 پروفایل کامل کاربر (ادمین)
    # ══════════════════════════════════════════
    if data.startswith("full_profile_"):
        target_id = int(data[len("full_profile_"):])
        profile_text = get_full_profile_text(target_id)
        keyboard = [
            [InlineKeyboardButton("↩️ پاسخ",             callback_data=f"reply_{target_id}")],
            [InlineKeyboardButton("📝 یادداشت",           callback_data=f"set_note_{target_id}")],
            [InlineKeyboardButton("🤖 توکن جدید",         callback_data=f"issue_token_{target_id}")],
            [
                InlineKeyboardButton("🚫 بلاک" if target_id not in blocked_users else "✅ آنبلاک",
                    callback_data=f"{'block' if target_id not in blocked_users else 'unblock'}_{target_id}"),
            ],
            [InlineKeyboardButton("🔙 برگشت",             callback_data="list_users")],
        ]
        await query.message.reply_text(
            profile_text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("set_note_"):
        target_id = int(data[len("set_note_"):])
        pending_note_input[ADMIN_CHAT_ID] = target_id
        info = users_db.get(target_id, {"name": str(target_id)})
        current_note = user_profiles.get(target_id, {}).get("admin_note") or "—"
        await query.message.reply_text(
            f"📝 *یادداشت برای {info['name']}*\n\n"
            f"یادداشت فعلی: {current_note}\n\n"
            f"یادداشت جدید رو بنویس (یا بفرست 'حذف' تا پاک بشه):",
            parse_mode="Markdown"
        )
        return


# ══════════════════════════════════════════════
#  هندلر متن ادمین
# ══════════════════════════════════════════════
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type != "private":
        return
    if chat_id != ADMIN_CHAT_ID:
        await forward_message(update, context)
        return

    text = update.message.text

    # ─── یادداشت روی کاربر ───────────────────
    if ADMIN_CHAT_ID in pending_note_input:
        target_id = pending_note_input[ADMIN_CHAT_ID]
        del pending_note_input[ADMIN_CHAT_ID]
        p = ensure_profile(target_id)
        if text.strip() == "حذف":
            p["admin_note"] = ""
            await update.message.reply_text("🗑 یادداشت حذف شد.")
        else:
            p["admin_note"] = text.strip()
            await update.message.reply_text(f"📝 یادداشت ذخیره شد:\n{text.strip()}")
        return

    # ─── تنظیم شماره کارت ────────────────────
    pending_card = context.bot_data.get("pending_card")
    if pending_card == "number":
        digits = text.strip().replace("-", "").replace(" ", "")
        if not digits.isdigit() or len(digits) not in (16,):
            await update.message.reply_text("❌ شماره کارت باید ۱۶ رقم باشه. دوباره بفرست:")
            return
        formatted = "-".join([digits[i:i+4] for i in range(0, 16, 4)])
        bot_config["card_number"] = formatted
        context.bot_data["pending_card"] = "owner"
        await update.message.reply_text(
            f"✅ شماره کارت ذخیره شد: `{formatted}`\n\nحالا نام صاحب کارت رو بفرست:",
            parse_mode="Markdown"
        )
        return
    if pending_card == "owner":
        bot_config["card_owner"] = text.strip()
        context.bot_data.pop("pending_card", None)
        await update.message.reply_text(
            f"✅ اطلاعات کارت بروز شد!\n\n"
            f"💳 شماره: `{bot_config['card_number']}`\n"
            f"👤 نام: {bot_config['card_owner']}",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard()
        )
        return

    # ─── افزودن/کاهش سکه ─────────────────────
    if ADMIN_CHAT_ID in pending_coin_add:
        target_id = pending_coin_add[ADMIN_CHAT_ID]
        try:
            amount = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد بفرست (مثلاً 20 یا -10).")
            return
        del pending_coin_add[ADMIN_CHAT_ID]
        new_balance = add_coins(target_id, amount, "تغییر دستی توسط ادمین")
        info = users_db.get(target_id, {"name": str(target_id)})
        sign = "+" if amount >= 0 else ""
        await update.message.reply_text(
            f"✅ موجودی *{info['name']}* بروز شد.\n"
            f"تغییر: {sign}{amount} سکه\n"
            f"موجودی جدید: 💰 {new_balance}",
            parse_mode="Markdown"
        )
        try:
            change_sign = "➕" if amount >= 0 else "➖"
            await context.bot.send_message(
                chat_id=target_id,
                text=(f"💰 *موجودی سکه‌ات تغییر کرد!*\n\n"
                      f"{change_sign} {abs(amount)} سکه\n"
                      f"موجودی جدید: {new_balance} سکه"),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # ─── ساخت نظرسنجی ────────────────────────
    if ADMIN_CHAT_ID in pending_poll:
        info = pending_poll[ADMIN_CHAT_ID]
        step = info.get("step")

        if step == "question":
            info["question"] = text
            info["step"]     = "options"
            info["options"]  = []
            await update.message.reply_text(
                "📝 گزینه‌های نظرسنجی رو یکی‌یکی بفرست.\n\n"
                "وقتی تموم شد، بنویس: *تمام*\n(حداقل ۲ گزینه لازمه)",
                parse_mode="Markdown"
            )
            return

        if step == "options":
            if text.strip() == "تمام":
                if len(info["options"]) < 2:
                    await update.message.reply_text("❌ حداقل ۲ گزینه لازمه.")
                    return
                info["step"] = "target"
                keyboard = [
                    [InlineKeyboardButton("👥 ارسال به همه کاربران", callback_data="poll_target_all")],
                    [InlineKeyboardButton("👥 ارسال به یک گروه",     callback_data="poll_target_group")],
                ]
                preview = "\n".join(f"• {o}" for o in info["options"])
                await update.message.reply_text(
                    f"🗳 *پیش‌نمایش نظرسنجی:*\n\n❓ {info['question']}\n\n{preview}\n\nکجا ارسال شه?",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            else:
                info["options"].append(text.strip())
                await update.message.reply_text(
                    f"✅ گزینه «{text.strip()}» اضافه شد. ({len(info['options'])} گزینه)\n\nگزینه بعدی یا بنویس *تمام*",
                    parse_mode="Markdown"
                )
                return

        if step == "waiting_group_id":
            try:
                group_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("❌ آیدی باید عدد باشه مثل -1001234567890")
                return
            success = await send_poll_to_target(context, info, group_id)
            del pending_poll[ADMIN_CHAT_ID]
            if success:
                await update.message.reply_text("✅ نظرسنجی به گروه ارسال شد.\n📊 نتایج به محض پاسخ کاربران برات ارسال میشه.")
            else:
                await update.message.reply_text("❌ ارسال ناموفق. مطمئن شو ربات ادمین گروهه.")
            return

    # ─── حالت ارسال به گروه ──────────────────
    if group_mode.get(ADMIN_CHAT_ID) == "waiting_id":
        try:
            group_id = int(text.strip())
            group_mode[ADMIN_CHAT_ID] = group_id
            await update.message.reply_text(
                f"✅ آیدی گروه ذخیره شد: `{group_id}`\n\nحالا پیامی که میخوای بفرستی رو بنویس:",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ آیدی باید عدد باشه مثل `-1001234567890`")
        return

    if isinstance(group_mode.get(ADMIN_CHAT_ID), int):
        group_id = group_mode[ADMIN_CHAT_ID]
        del group_mode[ADMIN_CHAT_ID]
        try:
            await context.bot.send_message(chat_id=group_id, text=text)
            await update.message.reply_text("✅ پیام به گروه ارسال شد!")
        except Exception as e:
            await update.message.reply_text(f"❌ خطا در ارسال:\n{str(e)}")
        return

    # ─── پیام همگانی ──────────────────────────
    if reply_to.get(ADMIN_CHAT_ID) == "broadcast":
        del reply_to[ADMIN_CHAT_ID]
        success = 0
        for uid in users_db:
            if uid not in blocked_users:
                try:
                    await context.bot.send_message(chat_id=uid, text=f"📢 *پیام از ادمین:*\n\n{text}", parse_mode="Markdown")
                    success += 1
                except Exception:
                    pass
        await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد.")
        return

    # ─── پاسخ به کاربر خاص ───────────────────
    if ADMIN_CHAT_ID in reply_to:
        target_id = reply_to[ADMIN_CHAT_ID]
        del reply_to[ADMIN_CHAT_ID]
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📨 *پیام از ادمین:*\n\n{text}",
                parse_mode="Markdown"
            )
            reply_msg_id = message_map.get(f"reply_{target_id}")
            if reply_msg_id:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"✅ پیام ارسال شد.",
                    reply_to_message_id=reply_msg_id
                )
            else:
                await update.message.reply_text("✅ پیام ارسال شد.")
        except Exception:
            await update.message.reply_text("❌ ارسال پیام ناموفق بود.")
        return


# ══════════════════════════════════════════════
#  main
# ══════════════════════════════════════════════
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("panel",    panel))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, forward_message))
    print("✅ ربات روشن شد و منتظر پیامه...")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])


if __name__ == "__main__":
    main()
