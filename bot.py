import logging
from datetime import datetime, timedelta
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
CARD_NUMBER    = "6037-XXXX-XXXX-XXXX"   # شماره کارت خودت رو اینجا بذار
CARD_OWNER     = "نام صاحب کارت"          # اسم صاحب کارت

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
    "plan_1": {"name": "برنزی",  "days": 30,  "price": "۲۹,۰۰۰ تومان",  "description": "دسترسی ۳۰ روزه"},
    "plan_2": {"name": "نقره‌ای", "days": 90,  "price": "۷۹,۰۰۰ تومان",  "description": "دسترسی ۳ ماهه"},
    "plan_3": {"name": "طلایی",  "days": 365, "price": "۲۴۹,۰۰۰ تومان", "description": "دسترسی ۱ ساله"},
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
bot_active = True            # ادمین می‌تونه ربات رو خاموش کنه

# ── اولویت پیام ──────────────────────────────
PRIORITY_LEVELS = {
    "normal": {"label": "🟢 عادی",  "emoji": "🟢", "cost": 0,  "title": "عادی"},
    "vip":    {"label": "🟡 ویژه",  "emoji": "🟡", "cost": 10, "title": "ویژه"},
    "urgent": {"label": "🔴 فوری",  "emoji": "🔴", "cost": 30, "title": "فوری"},
}


# ══════════════════════════════════════════════
#  توابع کمکی
# ══════════════════════════════════════════════
def add_coins(chat_id, amount, reason=""):
    user_coins[chat_id] = user_coins.get(chat_id, 0) + amount
    sign  = "➕" if amount >= 0 else "➖"
    entry = f"{sign} {abs(amount)} سکه — {reason or 'بدون توضیح'} | {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    user_history.setdefault(chat_id, []).append(entry)
    return user_coins[chat_id]


def get_coins(chat_id):
    return user_coins.get(chat_id, 0)


def has_active_subscription(chat_id):
    sub = user_subscriptions.get(chat_id)
    if not sub:
        return False
    return datetime.now() < sub["expires"]


def subscription_status_text(chat_id):
    sub = user_subscriptions.get(chat_id)
    if not sub:
        return "❌ ندارید"
    plan = subscription_plans.get(sub["plan"], {})
    expires = sub["expires"]
    if datetime.now() >= expires:
        return "⌛ منقضی شده"
    remaining = (expires - datetime.now()).days
    return f"✅ {plan.get('name','؟')} — {remaining} روز مانده (تا {expires.strftime('%Y-%m-%d')})"


# ══════════════════════════════════════════════
#  کیبوردها
# ══════════════════════════════════════════════
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📨 ارسال پیام به ادمین", callback_data="goto_send")],
        [InlineKeyboardButton("🛒 خرید اشتراک",         callback_data="show_plans")],
        [InlineKeyboardButton("👤 حساب من",             callback_data="my_account")],
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
    status = "🔴 خاموش" if not bot_active else "🟢 روشن"
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

    users_db[chat_id] = {
        "name":     user.full_name,
        "username": user.username or "ندارد",
        "chat_id":  chat_id
    }

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

    if not bot_active:
        await update.message.reply_text("⚠️ ربات در حال حاضر غیرفعال است. لطفاً بعداً تلاش کنید.")
        return

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
                InlineKeyboardButton("✅ تایید و فعال‌سازی", callback_data=f"approve_sub_{chat_id}_{receipt_info['plan']}"),
                InlineKeyboardButton("❌ رد کردن",           callback_data=f"reject_sub_{chat_id}"),
            ]
        ]
        caption = (
            f"🧾 *رسید پرداخت جدید*\n\n"
            f"👤 کاربر: {user_info['name']}\n"
            f"🆔 Chat ID: `{chat_id}`\n"
            f"📦 پلن: {plan.get('name','؟')} ({plan.get('price','؟')})\n"
            f"📅 مدت: {plan.get('days','؟')} روز\n"
            f"⏰ زمان: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
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
        if not bot_active:
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
        await query.edit_message_text(
            f"👤 *حساب من*\n\n"
            f"💰 موجودی سکه: {coins}\n"
            f"🔐 حالت ارسال: {mode}\n"
            f"📦 اشتراک: {sub}\n\n"
            f"📋 *آخرین تراکنش‌های سکه:*\n{history_text}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="back_main")]])
        )
        return

    # ── نمایش پلن‌ها ──────────────────────────
    if data == "show_plans":
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return
        text = "🛒 *خرید اشتراک*\n\n"
        for pid, plan in subscription_plans.items():
            text += f"⭐ *{plan['name']}* — {plan['price']}\n📅 {plan['description']}\n\n"
        text += "یه پلن انتخاب کن:"
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
            f"💳 *اطلاعات پرداخت*\n\n"
            f"📦 پلن انتخابی: *{plan['name']}*\n"
            f"💰 مبلغ: *{plan['price']}*\n"
            f"📅 مدت: {plan['days']} روز\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💳 شماره کارت:\n`{CARD_NUMBER}`\n"
            f"👤 به نام: *{CARD_OWNER}*\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"بعد از پرداخت، *تصویر رسید* رو اینجا ارسال کن 👇\n"
            f"(ادمین بررسی و اشتراکت رو فعال می‌کنه)",
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
        parts    = data.split("_")
        # approve_sub_{chat_id}_{plan_id}
        target_id = int(parts[2])
        plan_id   = parts[3]
        plan      = subscription_plans.get(plan_id, {})
        expires   = datetime.now() + timedelta(days=plan.get("days", 30))
        user_subscriptions[target_id] = {"plan": plan_id, "expires": expires}
        pending_receipts.pop(target_id, None)
        pending_receipt_input.discard(target_id)

        await query.edit_message_caption(
            caption=query.message.caption + f"\n\n✅ *تایید شد* توسط ادمین — {datetime.now().strftime('%H:%M')}",
            parse_mode="Markdown"
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🎉 *اشتراک شما فعال شد!*\n\n"
                    f"📦 پلن: *{plan.get('name','؟')}*\n"
                    f"📅 تاریخ انقضا: {expires.strftime('%Y-%m-%d')}\n\n"
                    f"از ربات لذت ببر ✨"
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
        target_id = int(data.split("_")[2])
        pending_receipts.pop(target_id, None)
        pending_receipt_input.discard(target_id)

        await query.edit_message_caption(
            caption=query.message.caption + f"\n\n❌ *رد شد* توسط ادمین — {datetime.now().strftime('%H:%M')}",
            parse_mode="Markdown"
        )
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
        await query.message.reply_text(f"🚫 کاربر *{user_info.get('name', target_id)}* بلاک شد.", parse_mode="Markdown")
        return

    if data.startswith("unblock_"):
        target_id = int(data.split("_")[1])
        blocked_users.discard(target_id)
        user_info = users_db.get(target_id, {})
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
            text    += f"{blocked}{mode_tag}{sub_tag} {info['name']} | @{info['username']} | `{uid}` | 💰{coins}\n"
            keyboard.append([
                InlineKeyboardButton(f"↩️ {info['name']}",  callback_data=f"reply_{uid}"),
                InlineKeyboardButton("🚫" if uid not in blocked_users else "✅ آنبلاک",
                                     callback_data=f"{'block' if uid not in blocked_users else 'unblock'}_{uid}"),
                InlineKeyboardButton("💰 سکه", callback_data=f"addcoin_{uid}"),
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
            f"⚡ وضعیت ربات: {'🟢 روشن' if bot_active else '🔴 خاموش'}"
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
        target_id = int(data.split("_")[2])
        info      = users_db.get(target_id, {"name": str(target_id)})
        sub_text  = subscription_status_text(target_id)
        plan_keyboard = []
        for pid, plan in subscription_plans.items():
            plan_keyboard.append([InlineKeyboardButton(
                f"➕ اضافه کن: {plan['name']} ({plan['days']} روز)",
                callback_data=f"admin_add_sub_{target_id}_{pid}"
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
        parts     = data.split("_")
        target_id = int(parts[3])
        plan_id   = parts[4]
        plan      = subscription_plans.get(plan_id, {})
        current   = user_subscriptions.get(target_id, {})
        # اگه اشتراک فعال دارن، اضافه کن؛ وگرنه از الان
        base      = current.get("expires", datetime.now())
        if base < datetime.now():
            base = datetime.now()
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
                      f"📦 پلن: *{plan.get('name','؟')}*\n"
                      f"📅 انقضا: {expires.strftime('%Y-%m-%d')}"),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    if data.startswith("admin_del_sub_"):
        target_id = int(data.split("_")[3])
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

    # ── خاموش/روشن ربات ─────────────────────
    if data == "toggle_bot":
        global bot_active
        bot_active = not bot_active
        status = "🟢 روشن شد" if bot_active else "🔴 خاموش شد"
        await query.message.reply_text(
            f"⚡ *وضعیت ربات:* {status}\n\n"
            f"{'کاربران میتونن پیام بفرستن.' if bot_active else 'کاربران نمیتونن پیام بفرستن.'}",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard()
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
