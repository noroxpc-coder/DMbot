import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, filters, ContextTypes
)

BOT_TOKEN = "8977895133:AAHdVjMrr-9-ceXXviV5Zt5I_vP93HxQqZY"
ADMIN_CHAT_ID = 1143598012

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)

users_db = {}
blocked_users = set()
reply_to = {}
message_map = {}   # نگه‌داری message_id پیام اصلی برای ریپلای
group_mode = {}    # حالت ارسال به گروه

# ─────────────────────────────────────────────
# 🆕 جدید: حالت ارسال هر کاربر (anonymous / normal)
# ─────────────────────────────────────────────
user_mode = {}   # {chat_id: "anonymous" | "normal"}

# ─────────────────────────────────────────────
# 🆕 حالت مزاحم نشو (Do Not Disturb)
# ─────────────────────────────────────────────
dnd_mode = {}            # {chat_id: True/False}
dnd_until = {}           # {chat_id: datetime}  -- پایان حالت مزاحم نشو (در صورت تعیین بازه)
pending_dnd_time = set() # کاربرانی که منتظر وارد کردن مدت زمان DND هستند

# ─────────────────────────────────────────────
# 🆕 سیستم گیمیفیکیشن / سکه (Coins)
# ─────────────────────────────────────────────
user_coins = {}       # {chat_id: int}
user_history = {}     # {chat_id: [str, ...]}  -- تاریخچه تراکنش‌های سکه

PRIORITY_LEVELS = {
    "normal": {"label": "🟢 عادی",  "emoji": "🟢", "cost": 0,  "title": "عادی"},
    "vip":    {"label": "🟡 ویژه",  "emoji": "🟡", "cost": 10, "title": "ویژه"},
    "urgent": {"label": "🔴 فوری",  "emoji": "🔴", "cost": 30, "title": "فوری"},
}

# ─────────────────────────────────────────────
# 🆕 تاریخچه مکالمه (لاگ پیام‌های بین کاربر و ادمین)
# ─────────────────────────────────────────────
conversation_history = {}   # {chat_id: [str, ...]}

# ─────────────────────────────────────────────
# 🆕 منتظر دریافت مقدار سکه از ادمین برای کاربر خاص
# ─────────────────────────────────────────────
pending_coin_add = {}   # {ADMIN_CHAT_ID: target_chat_id}

# ─────────────────────────────────────────────
# 🆕 نظرسنجی - منتظر دریافت اطلاعات نظرسنجی از ادمین
# ─────────────────────────────────────────────
pending_poll = {}   # {ADMIN_CHAT_ID: {"step": "...", "question": "...", "options": [...], "target": "all"/"group"/group_id}


# ══════════════════════════════════════════════
#  توابع کمکی گیمیفیکیشن / سکه
# ══════════════════════════════════════════════
def add_coins(chat_id, amount, reason=""):
    user_coins[chat_id] = user_coins.get(chat_id, 0) + amount
    sign = "➕" if amount >= 0 else "➖"
    entry = f"{sign} {abs(amount)} سکه — {reason or 'بدون توضیح'} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    user_history.setdefault(chat_id, []).append(entry)
    return user_coins[chat_id]

def get_coins(chat_id):
    return user_coins.get(chat_id, 0)


# ══════════════════════════════════════════════
#  تابع کمکی تاریخچه مکالمه
# ══════════════════════════════════════════════
def log_history(chat_id, line):
    entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {line}"
    conversation_history.setdefault(chat_id, []).append(entry)
    if len(conversation_history[chat_id]) > 50:
        conversation_history[chat_id] = conversation_history[chat_id][-50:]


# ══════════════════════════════════════════════
# 🆕 تابع کمکی ارسال نظرسنجی به هدف مشخص
#    target: "all" برای همه کاربران، یا یک group_id عددی
# ══════════════════════════════════════════════
async def send_poll_to_target(context: ContextTypes.DEFAULT_TYPE, poll_info, target):
    question = poll_info["question"]
    options  = poll_info["options"]

    if target == "all":
        success = 0
        for uid in users_db:
            if uid not in blocked_users:
                try:
                    await context.bot.send_poll(
                        chat_id=uid,
                        question=question,
                        options=options,
                        is_anonymous=True
                    )
                    success += 1
                except Exception:
                    pass
        return success
    else:
        # target یک group_id عددی است
        try:
            await context.bot.send_poll(
                chat_id=target,
                question=question,
                options=options,
                is_anonymous=True
            )
            return 1
        except Exception:
            return 0


# ══════════════════════════════════════════════
#  کیبورد انتخاب اولویت پیام (زیر هر پیام کاربر)
# ══════════════════════════════════════════════
def priority_keyboard(chat_id):
    coins = get_coins(chat_id)
    keyboard = [
        [InlineKeyboardButton("🟢 عادی (رایگان)", callback_data="priority_normal")],
        [InlineKeyboardButton(f"🟡 ویژه (۱۰ سکه)", callback_data="priority_vip")],
        [InlineKeyboardButton(f"🔴 فوری (۳۰ سکه)", callback_data="priority_urgent")],
        [InlineKeyboardButton(f"💰 موجودی شما: {coins} سکه", callback_data="noop")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ══════════════════════════════════════════════
#  کیبورد انتخاب حالت ارسال (برای کاربر)
# ══════════════════════════════════════════════
def mode_selection_keyboard():
    keyboard = [
        [InlineKeyboardButton("👤 با اسم (عادی)", callback_data="set_mode_normal")],
        [InlineKeyboardButton("🕵️ ناشناس",         callback_data="set_mode_anonymous")],
    ]
    return InlineKeyboardMarkup(keyboard)

def settings_keyboard():
    keyboard = [
        [InlineKeyboardButton("👤 حالت عادی",  callback_data="set_mode_normal")],
        [InlineKeyboardButton("🕵️ حالت ناشناس", callback_data="set_mode_anonymous")],
    ]
    return InlineKeyboardMarkup(keyboard)


# ══════════════════════════════════════════════
# 🆕 کیبورد حالت مزاحم نشو
# ══════════════════════════════════════════════
def dnd_keyboard(chat_id):
    is_on = dnd_mode.get(chat_id, False)
    if is_on:
        keyboard = [
            [InlineKeyboardButton("🔔 خاموش کردن حالت مزاحم نشو", callback_data="dnd_off")],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("🔕 فعال کردن (تا اطلاع بعدی)", callback_data="dnd_on_forever")],
            [InlineKeyboardButton("⏰ فعال کردن برای مدت مشخص (دقیقه)", callback_data="dnd_on_timed")],
        ]
    return InlineKeyboardMarkup(keyboard)


def is_dnd_active(chat_id):
    """بررسی می‌کند آیا حالت مزاحم نشو برای کاربر فعال است یا نه (و در صورت تمام شدن بازه، خودش غیرفعال می‌کند)."""
    if not dnd_mode.get(chat_id, False):
        return False
    until = dnd_until.get(chat_id)
    if until is not None:
        if datetime.now() >= until:
            dnd_mode[chat_id] = False
            dnd_until.pop(chat_id, None)
            return False
    return True


# ══════════════════════════════════════════════
#  پنل ادمین (بدون تغییر)
# ══════════════════════════════════════════════
def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("👥 لیست کاربران",       callback_data="list_users")],
        [InlineKeyboardButton("🚫 لیست بلاک‌شده‌ها",  callback_data="list_blocked")],
        [InlineKeyboardButton("📊 آمار",                callback_data="stats")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی",  callback_data="broadcast")],
        [InlineKeyboardButton("👥 ارسال پیام به گروه", callback_data="send_group")],
        [InlineKeyboardButton("🗳 ساخت نظرسنجی",       callback_data="create_poll")],
        [InlineKeyboardButton("💰 مدیریت سکه کاربران", callback_data="manage_coins")],
    ]
    return InlineKeyboardMarkup(keyboard)

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID:
        return
    await update.message.reply_text(
        "🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:",
        parse_mode="Markdown",
        reply_markup=admin_panel_keyboard()
    )


# ══════════════════════════════════════════════
#  /start  —  اگه کاربر جدیده، حالت رو بپرسه
# ══════════════════════════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    chat_id = update.effective_chat.id

    if update.effective_chat.type != "private":
        return
    if chat_id == ADMIN_CHAT_ID:
        await panel(update, context)
        return

    # ذخیره اطلاعات کاربر
    users_db[chat_id] = {
        "name":     user.full_name,
        "username": user.username or "ندارد",
        "chat_id":  chat_id
    }

    # 🆕 اگه کاربر هنوز حالت انتخاب نکرده، بپرس
    if chat_id not in user_mode:
        await update.message.reply_text(
            "👋 *سلام!*\n\n"
            "قبل از اینکه پیامت رو بفرستی، یه چیز ازت بپرسم:\n\n"
            "━━━━━━━━━━━━━━━━\n"
            "👤 *با اسم* — ادمین اسم و پروفایلت رو میبینه\n"
            "🕵️ *ناشناس* — هیچ اطلاعاتی از تو نمیفرسته\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "💡 هر وقت خواستی از /settings میتونی حالتت رو عوض کنی.",
            parse_mode="Markdown",
            reply_markup=mode_selection_keyboard()
        )
    else:
        current = "🕵️ ناشناس" if user_mode[chat_id] == "anonymous" else "👤 عادی"
        await update.message.reply_text(
            f"👋 *سلام {user.first_name}!*\n\n"
            f"حالت فعلیت: {current}\n"
            f"پیامت رو بفرست، در اولین فرصت جواب میگیری ✅\n\n"
            f"💡 برای تغییر حالت: /settings",
            parse_mode="Markdown"
        )


# ══════════════════════════════════════════════
#  🆕 /settings  —  تغییر حالت ارسال
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
        reply_markup=settings_keyboard()
    )

    # 🆕 نمایش وضعیت حالت مزاحم نشو
    if is_dnd_active(chat_id):
        until = dnd_until.get(chat_id)
        if until:
            dnd_status = f"🔕 فعال تا ساعت {until.strftime('%H:%M')}"
        else:
            dnd_status = "🔕 فعال (تا اطلاع بعدی)"
    else:
        dnd_status = "🔔 غیرفعال"

    await update.message.reply_text(
        "🔕 *حالت مزاحم نشو*\n\n"
        f"وضعیت فعلی: {dnd_status}\n\n"
        "وقتی این حالت فعاله، پیام‌های ادمین رو دریافت نمی‌کنی تا خودت غیرفعالش کنی یا زمانش تموم بشه.",
        parse_mode="Markdown",
        reply_markup=dnd_keyboard(chat_id)
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

    # 🆕 اگه کاربر منتظره مدت زمان DND رو وارد کنه
    if chat_id in pending_dnd_time:
        text = update.message.text
        if not text or not text.strip().isdigit():
            await update.message.reply_text("❌ لطفاً فقط عدد بفرست (مثلاً `60`).", parse_mode="Markdown")
            return
        minutes = int(text.strip())
        if minutes <= 0:
            await update.message.reply_text("❌ عدد باید بزرگتر از صفر باشه.")
            return
        pending_dnd_time.discard(chat_id)
        dnd_mode[chat_id] = True
        dnd_until[chat_id] = datetime.now() + timedelta(minutes=minutes)
        await update.message.reply_text(
            f"🔕 *حالت مزاحم نشو فعال شد* برای {minutes} دقیقه.\n\n"
            f"تا ساعت {dnd_until[chat_id].strftime('%H:%M')} پیام‌های ادمین رو دریافت نمی‌کنی.",
            parse_mode="Markdown"
        )
        return

    # 🆕 اگه هنوز حالت انتخاب نکرده، اول بپرس
    if chat_id not in user_mode:
        await update.message.reply_text(
            "⚠️ قبل از ارسال پیام، لطفاً حالت ارسالت رو انتخاب کن:\n\n"
            "👤 *با اسم* — ادمین اطلاعاتت رو میبینه\n"
            "🕵️ *ناشناس* — هیچ اطلاعاتی ارسال نمیشه\n\n"
            "💡 بعداً از /settings میتونی تغییرش بدی.",
            parse_mode="Markdown",
            reply_markup=mode_selection_keyboard()
        )
        return

    users_db[chat_id] = {
        "name":     user.full_name,
        "username": user.username or "ندارد",
        "chat_id":  chat_id
    }

    # 🆕 اگه پیام متنیه، اول ازش بپرس با چه اولویتی ارسال شه
    if update.message.text:
        context.user_data["pending_text"] = update.message.text
        await update.message.reply_text(
            "📨 پیامت آماده ارسال شد!\n\n"
            "میخوای با چه اولویتی برای ادمین ارسال شه؟\n\n"
            "🟢 *عادی* — رایگان\n"
            "🟡 *ویژه* — ۱۰ سکه (در لیست ادمین بالاتر نشون داده میشه)\n"
            "🔴 *فوری* — ۳۰ سکه (در صدر لیست + علامت قرمز)",
            parse_mode="Markdown",
            reply_markup=priority_keyboard(chat_id)
        )
        return

    # برای پیام‌های غیرمتنی (عکس، ویدیو، فایل و ...) مستقیم با اولویت عادی ارسال میشه
    await send_user_message(context, chat_id, user, priority="normal",
                             text=None, original_message=update.message,
                             confirm_target=update.message)


# ══════════════════════════════════════════════
# 🆕 ارسال نهایی پیام کاربر به ادمین (با اولویت)
#    text: متن پیام (برای پیام‌های متنی)
#    original_message: شیء پیام تلگرام (برای فوروارد/کپی فایل‌ها) - برای متن می‌تونه None باشه
#    confirm_target: شیء پیامی که باید پیام تایید روش reply بشه
# ══════════════════════════════════════════════
async def send_user_message(context: ContextTypes.DEFAULT_TYPE, chat_id, user, priority="normal",
                             text=None, original_message=None, confirm_target=None):
    level = PRIORITY_LEVELS[priority]
    priority_tag = ""
    if priority == "vip":
        priority_tag = "\n🟡 *پیام ویژه*"
    elif priority == "urgent":
        priority_tag = "\n🔴 *پیام فوری* ⚡️"

    is_anonymous = user_mode[chat_id] == "anonymous"
    keyboard = [[
        InlineKeyboardButton("↩️ پاسخ",  callback_data=f"reply_{chat_id}"),
        InlineKeyboardButton("🚫 بلاک",  callback_data=f"block_{chat_id}"),
    ]]

    # ─── حالت ناشناس ───────────────────────────
    if is_anonymous:
        sender_info = (
            f"📩 *پیام جدید*{priority_tag}\n"
            f"🕵️ *ناشناس*\n"
            f"🔢 Chat ID: `{chat_id}`\n"
            f"{'─' * 25}"
        )
    # ─── حالت عادی ─────────────────────────────
    else:
        sender_info = (
            f"📩 *پیام جدید*{priority_tag}\n"
            f"👤 نام: {user.full_name}\n"
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

    # ارسال محتوای اصلی پیام
    if text is not None:
        fwd = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    elif is_anonymous:
        fwd = await original_message.copy_to(chat_id=ADMIN_CHAT_ID)
    else:
        fwd = await original_message.forward(chat_id=ADMIN_CHAT_ID)

    message_map[f"reply_{chat_id}"] = fwd.message_id

    # 🆕 کسر سکه در صورت اولویت غیر عادی
    if level["cost"] > 0:
        add_coins(chat_id, -level["cost"], f"ارسال پیام با اولویت {level['title']}")

    # 🆕 ثبت در تاریخچه مکالمه
    log_history(chat_id, f"👤 کاربر ({level['title']}): {text or '[فایل/مدیا]'}")

    # 🆕 پیام تایید برای کاربر
    confirm_text = "✅ پیامت دریافت شد، به زودی جواب میگیری."
    if priority == "vip":
        confirm_text = "✅ پیام *ویژه*‌ت ارسال شد! 🟡 سریع‌تر بررسی میشه."
    elif priority == "urgent":
        confirm_text = "✅ پیام *فوری*‌ت ارسال شد! 🔴 در صدر لیست ادمین قرار گرفت."

    if is_anonymous:
        confirm_text += " 🕵️"

    if confirm_target is not None:
        await confirm_target.reply_text(confirm_text, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=chat_id, text=confirm_text, parse_mode="Markdown")


# ══════════════════════════════════════════════
#  هندلر دکمه‌ها
# ══════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    data    = query.data
    chat_id = query.message.chat.id

    # ─── 🆕 انتخاب حالت توسط کاربر ──────────────
    if data in ("set_mode_normal", "set_mode_anonymous"):
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            await query.answer()
            return
        await query.answer()

        if data == "set_mode_normal":
            user_mode[user_chat_id] = "normal"
            await query.edit_message_text(
                "✅ *حالت عادی فعال شد!*\n\n"
                "👤 از این به بعد اسم و پروفایلت همراه پیامت ارسال میشه.\n\n"
                "💡 برای تغییر: /settings\n\n"
                "حالا پیامت رو بفرست 👇",
                parse_mode="Markdown"
            )
        else:
            user_mode[user_chat_id] = "anonymous"
            await query.edit_message_text(
                "✅ *حالت ناشناس فعال شد!*\n\n"
                "🕵️ از این به بعد هیچ اطلاعاتی از تو ارسال نمیشه.\n\n"
                "💡 برای تغییر: /settings\n\n"
                "حالا پیامت رو بفرست 👇",
                parse_mode="Markdown"
            )
        return

    # ─── 🆕 انتخاب اولویت پیام توسط کاربر ────────
    if data in ("priority_normal", "priority_vip", "priority_urgent"):
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            await query.answer()
            return

        priority = data.split("_")[1]   # normal / vip / urgent
        level    = PRIORITY_LEVELS[priority]
        coins    = get_coins(user_chat_id)

        if level["cost"] > coins:
            await query.answer(
                f"❌ سکه کافی نداری! ({coins}/{level['cost']})",
                show_alert=True
            )
            return

        await query.answer()
        pending_text = context.user_data.get("pending_text")
        if not pending_text:
            await query.edit_message_text("⚠️ پیام منقضی شده، لطفاً دوباره ارسال کن.")
            return

        user = query.from_user
        await send_user_message(context, user_chat_id, user, priority=priority, text=pending_text)

        context.user_data.pop("pending_text", None)
        await query.edit_message_reply_markup(reply_markup=None)
        return

    # ─── 🆕 مدیریت حالت مزاحم نشو توسط کاربر ─────
    if data in ("dnd_on_forever", "dnd_on_timed", "dnd_off"):
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            await query.answer()
            return
        await query.answer()

        if data == "dnd_on_forever":
            dnd_mode[user_chat_id] = True
            dnd_until.pop(user_chat_id, None)
            await query.edit_message_text(
                "🔕 *حالت مزاحم نشو فعال شد.*\n\n"
                "پیام‌های ادمین رو دریافت نمی‌کنی تا خودت از /settings خاموشش کنی.",
                parse_mode="Markdown"
            )
        elif data == "dnd_on_timed":
            pending_dnd_time.add(user_chat_id)
            await query.edit_message_text(
                "⏰ چند دقیقه میخوای حالت مزاحم نشو فعال باشه؟\n\n"
                "یه عدد بفرست (مثلاً `60` برای ۱ ساعت).",
                parse_mode="Markdown"
            )
        else:  # dnd_off
            dnd_mode[user_chat_id] = False
            dnd_until.pop(user_chat_id, None)
            await query.edit_message_text(
                "🔔 *حالت مزاحم نشو خاموش شد.*\n\nدوباره پیام‌های ادمین رو دریافت می‌کنی.",
                parse_mode="Markdown"
            )
        return

    # ─── 🆕 دکمه بی‌اثر (نمایش موجودی سکه) ───────
    if data == "noop":
        await query.answer()
        return

    # ─── بقیه دکمه‌ها فقط برای ادمین ─────────────
    if chat_id != ADMIN_CHAT_ID:
        await query.answer()
        return

    await query.answer()

    if data.startswith("reply_"):
        target_id = int(data.split("_")[1])
        reply_to[ADMIN_CHAT_ID] = target_id
        user_info = users_db.get(target_id, {})
        name = user_info.get("name", "ناشناس") if user_mode.get(target_id) != "anonymous" else "🕵️ ناشناس"
        await query.message.reply_text(
            f"✍️ پیامت رو بنویس، برای *{name}* ارسال میشه.",
            parse_mode="Markdown"
        )

    elif data.startswith("block_"):
        target_id = int(data.split("_")[1])
        blocked_users.add(target_id)
        user_info = users_db.get(target_id, {})
        await query.message.reply_text(f"🚫 کاربر *{user_info.get('name', target_id)}* بلاک شد.", parse_mode="Markdown")

    elif data.startswith("unblock_"):
        target_id = int(data.split("_")[1])
        blocked_users.discard(target_id)
        user_info = users_db.get(target_id, {})
        await query.message.reply_text(f"✅ کاربر *{user_info.get('name', target_id)}* آنبلاک شد.", parse_mode="Markdown")

    elif data == "list_users":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری.")
            return
        text     = "👥 *لیست کاربران:*\n\n"
        keyboard = []
        for uid, info in users_db.items():
            blocked  = "🚫" if uid in blocked_users else "✅"
            mode_tag = "🕵️" if user_mode.get(uid) == "anonymous" else "👤"
            coins    = get_coins(uid)
            text    += f"{blocked}{mode_tag} {info['name']} | @{info['username']} | `{uid}` | 💰{coins}\n"
            keyboard.append([
                InlineKeyboardButton(f"↩️ {info['name']}", callback_data=f"reply_{uid}"),
                InlineKeyboardButton("🚫" if uid not in blocked_users else "✅",
                                     callback_data=f"{'block' if uid not in blocked_users else 'unblock'}_{uid}"),
                InlineKeyboardButton("💰", callback_data=f"addcoin_{uid}"),
            ])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "list_blocked":
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

    elif data == "stats":
        total   = len(users_db)
        blocked = len(blocked_users)
        active  = total - blocked
        anon    = sum(1 for uid in users_db if user_mode.get(uid) == "anonymous")
        normal  = sum(1 for uid in users_db if user_mode.get(uid) == "normal")
        text = (
            f"📊 *آمار ربات*\n\n"
            f"👥 کل کاربران: {total}\n"
            f"✅ کاربران فعال: {active}\n"
            f"🚫 بلاک‌شده‌ها: {blocked}\n"
            f"━━━━━━━━━━━━━━\n"
            f"🕵️ ناشناس: {anon}\n"
            f"👤 عادی: {normal}\n"
        )
        await query.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="back")]]))

    elif data == "broadcast":
        reply_to[ADMIN_CHAT_ID] = "broadcast"
        await query.message.reply_text("📢 پیام همگانیت رو بنویس، برای همه کاربران ارسال میشه:")

    elif data == "send_group":
        group_mode[ADMIN_CHAT_ID] = "waiting_id"
        await query.message.reply_text(
            "👥 *ارسال به گروه*\n\nاول آیدی عددی گروه رو بفرست:\n(مثلاً: `-1001234567890`)\n\nبرای پیدا کردن آیدی گروه، ربات رو به گروه اضافه کن و یه پیام بفرست.",
            parse_mode="Markdown"
        )

    elif data == "back":
        await query.message.reply_text(
            "🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard()
        )

    # ─── 🆕 ساخت نظرسنجی ──────────────────────────
    elif data == "create_poll":
        pending_poll[ADMIN_CHAT_ID] = {"step": "question"}
        await query.message.reply_text(
            "🗳 *ساخت نظرسنجی*\n\n"
            "اول سوال نظرسنجی رو بنویس:",
            parse_mode="Markdown"
        )

    elif data == "poll_target_all":
        info = pending_poll.get(ADMIN_CHAT_ID)
        if not info:
            return
        info["target"] = "all"
        await send_poll_to_target(context, info, "all")
        del pending_poll[ADMIN_CHAT_ID]
        await query.message.reply_text("✅ نظرسنجی برای همه کاربران ارسال شد.")

    elif data == "poll_target_group":
        info = pending_poll.get(ADMIN_CHAT_ID)
        if not info:
            return
        info["step"] = "waiting_group_id"
        await query.message.reply_text(
            "👥 آیدی عددی گروه رو بفرست:\n(مثلاً `-1001234567890`)",
            parse_mode="Markdown"
        )

    # ─── 🆕 مدیریت سکه کاربران ────────────────────
    elif data == "manage_coins":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری.")
            return
        text     = "💰 *مدیریت سکه کاربران*\n\nروی کاربر مورد نظر بزن تا سکه اضافه/کم کنی:\n\n"
        keyboard = []
        for uid, info in users_db.items():
            coins = get_coins(uid)
            text += f"👤 {info['name']} | `{uid}` | 💰 {coins}\n"
            keyboard.append([InlineKeyboardButton(f"💰 {info['name']} ({coins})", callback_data=f"addcoin_{uid}")])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("addcoin_"):
        target_id = int(data.split("_")[1])
        pending_coin_add[ADMIN_CHAT_ID] = target_id
        info = users_db.get(target_id, {"name": str(target_id)})
        coins = get_coins(target_id)
        await query.message.reply_text(
            f"💰 *افزودن/کاهش سکه*\n\n"
            f"کاربر: {info['name']} | `{target_id}`\n"
            f"موجودی فعلی: {coins} سکه\n\n"
            f"یه عدد بفرست (مثبت برای افزایش، منفی برای کاهش، مثلاً `20` یا `-10`):",
            parse_mode="Markdown"
        )


# ══════════════════════════════════════════════
#  هندلر متن ادمین (بدون تغییر اصلی)
# ══════════════════════════════════════════════
async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.effective_chat.type != "private":
        return
    if chat_id != ADMIN_CHAT_ID:
        await forward_message(update, context)
        return

    text = update.message.text

    # ─── 🆕 افزودن/کاهش سکه برای کاربر خاص ───────
    if ADMIN_CHAT_ID in pending_coin_add:
        target_id = pending_coin_add[ADMIN_CHAT_ID]
        try:
            amount = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ لطفاً فقط یه عدد بفرست (مثلاً 20 یا -10).")
            return
        del pending_coin_add[ADMIN_CHAT_ID]
        new_balance = add_coins(target_id, amount, "تغییر دستی توسط ادمین")
        info = users_db.get(target_id, {"name": str(target_id)})
        sign = "+" if amount >= 0 else ""
        await update.message.reply_text(
            f"✅ موجودی *{info['name']}* بروزرسانی شد.\n"
            f"تغییر: {sign}{amount} سکه\n"
            f"موجودی جدید: 💰 {new_balance}",
            parse_mode="Markdown"
        )
        try:
            change_sign = "➕" if amount >= 0 else "➖"
            await context.bot.send_message(
                chat_id=target_id,
                text=(f"💰 *موجودی سکه شما تغییر کرد!*\n\n"
                      f"{change_sign} {abs(amount)} سکه\n"
                      f"موجودی جدید: {new_balance} سکه"),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    # ─── 🆕 ساخت نظرسنجی - مراحل ─────────────────
    if ADMIN_CHAT_ID in pending_poll:
        info = pending_poll[ADMIN_CHAT_ID]
        step = info.get("step")

        if step == "question":
            info["question"] = text
            info["step"] = "options"
            info["options"] = []
            await update.message.reply_text(
                "📝 گزینه‌های نظرسنجی رو یکی‌یکی بفرست.\n\n"
                "وقتی همه گزینه‌ها رو فرستادی، بنویس: تمام\n"
                "(حداقل ۲ گزینه لازمه)"
            )
            return

        if step == "options":
            if text.strip() == "تمام":
                if len(info["options"]) < 2:
                    await update.message.reply_text("❌ حداقل ۲ گزینه لازمه. یه گزینه دیگه بفرست.")
                    return
                info["step"] = "target"
                keyboard = [
                    [InlineKeyboardButton("👥 ارسال به همه کاربران", callback_data="poll_target_all")],
                    [InlineKeyboardButton("👥 ارسال به یک گروه",     callback_data="poll_target_group")],
                ]
                preview = "\n".join(f"• {o}" for o in info["options"])
                await update.message.reply_text(
                    f"🗳 *پیش‌نمایش نظرسنجی:*\n\n"
                    f"❓ {info['question']}\n\n{preview}\n\n"
                    f"حالا مشخص کن کجا ارسال شه:",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            else:
                info["options"].append(text.strip())
                await update.message.reply_text(
                    f"✅ گزینه «{text.strip()}» اضافه شد. ({len(info['options'])} گزینه)\n\n"
                    f"گزینه بعدی رو بفرست یا بنویس تمام."
                )
                return

        if step == "waiting_group_id":
            try:
                group_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("❌ آیدی اشتباهه! باید عدد باشه مثل -1001234567890")
                return
            success = await send_poll_to_target(context, info, group_id)
            del pending_poll[ADMIN_CHAT_ID]
            if success:
                await update.message.reply_text("✅ نظرسنجی به گروه ارسال شد.")
            else:
                await update.message.reply_text("❌ ارسال نظرسنجی به گروه ناموفق بود. مطمئن شو ربات عضو/ادمین گروهه.")
            return

    # حالت ارسال به گروه - دریافت آیدی گروه
    if group_mode.get(ADMIN_CHAT_ID) == "waiting_id":
        try:
            group_id = int(text.strip())
            group_mode[ADMIN_CHAT_ID] = group_id
            await update.message.reply_text(
                f"✅ آیدی گروه ذخیره شد: `{group_id}`\n\nحالا پیامی که میخوای بفرستی رو بنویس:",
                parse_mode="Markdown"
            )
        except ValueError:
            await update.message.reply_text("❌ آیدی اشتباهه! باید عدد باشه مثل `-1001234567890`")
        return

    # حالت ارسال به گروه - دریافت متن پیام
    if isinstance(group_mode.get(ADMIN_CHAT_ID), int):
        group_id = group_mode[ADMIN_CHAT_ID]
        del group_mode[ADMIN_CHAT_ID]
        try:
            await context.bot.send_message(chat_id=group_id, text=text)
            await update.message.reply_text("✅ پیام به گروه ارسال شد!")
        except Exception as e:
            await update.message.reply_text(f"❌ خطا در ارسال:\n{str(e)}\n\nمطمئن شو ربات ادمین گروهه.")
        return

    # پیام همگانی
    if reply_to.get(ADMIN_CHAT_ID) == "broadcast":
        del reply_to[ADMIN_CHAT_ID]
        success = 0
        for uid in users_db:
            if uid not in blocked_users:
                try:
                    await context.bot.send_message(chat_id=uid, text=f"📢 پیام از ادمین:\n{text}")
                    success += 1
                except Exception:
                    pass
        await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد.")
        return

    # پاسخ به کاربر خاص با ریپلای روی پیام اصلی
    if ADMIN_CHAT_ID in reply_to:
        target_id = reply_to[ADMIN_CHAT_ID]
        del reply_to[ADMIN_CHAT_ID]

        # 🆕 بررسی حالت مزاحم نشو کاربر مقصد
        if is_dnd_active(target_id):
            until = dnd_until.get(target_id)
            until_text = f" (تا ساعت {until.strftime('%H:%M')})" if until else " (تا اطلاع بعدی)"
            await update.message.reply_text(
                f"🔕 توجه: کاربر `{target_id}` حالت *مزاحم نشو* رو فعال کرده{until_text}.\n"
                f"پیامت برای این کاربر ارسال نشد.\n\n"
                f"می‌تونی صبر کنی تا این حالت غیرفعال شه و دوباره پاسخ بدی.",
                parse_mode="Markdown"
            )
            return

        try:
            reply_msg_id = message_map.get(f"reply_{target_id}")
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📨 پیام از ادمین:\n{text}"
            )
            log_history(target_id, f"👨‍💼 ادمین: {text}")
            if reply_msg_id:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"✅ پیام ارسال شد!\n📤 پاسخ: {text}",
                    reply_to_message_id=reply_msg_id
                )
            else:
                await update.message.reply_text("✅ پیام ارسال شد!")
        except Exception:
            await update.message.reply_text("❌ ارسال پیام ناموفق بود.")


# ══════════════════════════════════════════════
#  main
# ══════════════════════════════════════════════
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("panel",    panel))
    app.add_handler(CommandHandler("settings", settings))   # 🆕
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, forward_message))
    print("✅ ربات روشن شد و منتظر پیامه...")
    app.run_polling()

if __name__ == "__main__":
    main()
