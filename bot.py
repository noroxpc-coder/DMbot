import logging, secrets, string
from datetime import datetime, timedelta, timezone

try:
    import pytz
    TEHRAN_TZ = pytz.timezone("Asia/Tehran")
except ImportError:
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

def now_tehran(): return datetime.now(TEHRAN_TZ)
def fmt_dt(dt=None): return (dt or now_tehran()).strftime("%Y-%m-%d | %H:%M") + " (تهران)"

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, PollAnswerHandler, filters, ContextTypes

BOT_TOKEN     = "8977895133:AAHdVjMrr-9-ceXXviV5Zt5I_vP93HxQqZY"
ADMIN_CHAT_ID = 1143598012
bot_config    = {"card_number": "6037-XXXX-XXXX-XXXX", "card_owner": "نام صاحب کارت"}

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARNING)

users_db = {}; blocked_users = set(); reply_to = {}; message_map = {}
group_mode = {}; user_mode = {}; user_coins = {}; user_history = {}
pending_poll = {}; poll_votes = {}
subscription_plans = {"plan1": {"name": "اشتراک یک ماهه", "days": 30, "price": "۴۰,۰۰۰ تومان", "description": "دسترسی کامل ۳۰ روزه"}}
user_subscriptions = {}; pending_receipts = {}; pending_receipt_input = set()
pending_coin_add = {}; bot_state = {"active": True}; user_profiles = {}
bot_tokens = {}; user_bot_tokens = {}; user_submitting_token = set()
pending_note_input = {}

PRIORITY_LEVELS = {
    "normal": {"label": "🟢 عادی",  "emoji": "🟢", "cost": 0,  "title": "عادی"},
    "vip":    {"label": "🟡 ویژه",  "emoji": "🟡", "cost": 10, "title": "ویژه"},
    "urgent": {"label": "🔴 فوری",  "emoji": "🔴", "cost": 30, "title": "فوری"},
}

# ── توابع کمکی ──────────────────────────────────────────────────────────────

def add_coins(uid, amount, reason=""):
    user_coins[uid] = user_coins.get(uid, 0) + amount
    sign = "➕" if amount >= 0 else "➖"
    user_history.setdefault(uid, []).append(f"{sign} {abs(amount)} سکه — {reason or 'بدون توضیح'} | {fmt_dt()}")
    return user_coins[uid]

def get_coins(uid): return user_coins.get(uid, 0)

def has_active_subscription(uid):
    sub = user_subscriptions.get(uid)
    return bool(sub) and now_tehran() < sub["expires"]

def subscription_status_text(uid):
    sub = user_subscriptions.get(uid)
    if not sub: return "❌ ندارید"
    plan, expires = subscription_plans.get(sub["plan"], {}), sub["expires"]
    if now_tehran() >= expires: return "⌛ منقضی شده"
    return f"✅ {plan.get('name','؟')} — {(expires - now_tehran()).days} روز مانده (تا {expires.strftime('%Y-%m-%d')})"

def ensure_profile(uid):
    if uid not in user_profiles:
        user_profiles[uid] = {"join_date": fmt_dt(), "msg_count": 0, "admin_note": "", "block_history": [], "last_seen": fmt_dt()}
    return user_profiles[uid]

def update_last_seen(uid): ensure_profile(uid)["last_seen"] = fmt_dt()
def increment_msg(uid): p = ensure_profile(uid); p["msg_count"] = p.get("msg_count", 0) + 1

def get_full_profile_text(uid):
    info = users_db.get(uid, {"name": str(uid), "username": "ندارد"})
    p    = ensure_profile(uid)
    tokens = user_bot_tokens.get(uid, [])
    token_lines = "".join(
        f"  • `{t}` — {'✅ استفاده شده' if bot_tokens.get(t,{}).get('used') else '⏳ استفاده نشده'}\n"
        for t in tokens
    ) or "  — توکنی ندارد\n"
    bh_text = "\n".join(f"  • {b}" for b in p.get("block_history",[])[-3:]) or "  — سابقه‌ای ندارد"
    return (
        f"👤 *پروفایل کامل کاربر*\n━━━━━━━━━━━━━━━━━━\n"
        f"🏷 نام: *{info.get('name','؟')}*\n🆔 یوزرنیم: @{info.get('username','ندارد')}\n🔢 Chat ID: `{uid}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 تاریخ عضویت: {p.get('join_date','؟')}\n🕐 آخرین فعالیت: {p.get('last_seen','؟')}\n📨 تعداد پیام‌ها: {p.get('msg_count',0)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 موجودی سکه: {get_coins(uid)}\n📦 اشتراک: {subscription_status_text(uid)}\n"
        f"🔐 حالت ارسال: {'🕵️ ناشناس' if user_mode.get(uid)=='anonymous' else '👤 عادی'}\n"
        f"🚫 بلاک‌شده: {'🚫 بله' if uid in blocked_users else '✅ خیر'}\n"
        f"━━━━━━━━━━━━━━━━━━\n🤖 توکن‌های ربات:\n{token_lines}"
        f"━━━━━━━━━━━━━━━━━━\n📋 سابقه بلاک:\n{bh_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n📝 یادداشت ادمین: {p.get('admin_note') or '—'}"
    )

def generate_token():
    chars = string.ascii_uppercase + string.digits
    while True:
        t = "BOT-" + "".join(secrets.choice(chars) for _ in range(8))
        if t not in bot_tokens: return t

def create_bot_token(uid, plan_id="plan1"):
    token = generate_token()
    bot_tokens[token] = {"chat_id": uid, "plan_id": plan_id, "created_at": fmt_dt(), "used": False, "bot_username": None}
    user_bot_tokens.setdefault(uid, []).append(token)
    return token

def use_bot_token(token_str, bot_username):
    td = bot_tokens.get(token_str)
    if not td: return False, "توکن نامعتبر است"
    if td["used"]: return False, "این توکن قبلاً استفاده شده"
    td.update({"used": True, "bot_username": bot_username, "used_at": fmt_dt()})
    return True, "ok"

# ── کیبوردها ────────────────────────────────────────────────────────────────

def kb(*rows): return InlineKeyboardMarkup(list(rows))
def btn(label, data): return InlineKeyboardButton(label, callback_data=data)
def back_btn(cb="back"): return btn("🔙 برگشت", cb)

def main_menu_keyboard():
    return kb(
        [btn("📨 ارسال پیام به ادمین", "goto_send")],
        [btn("🛒 خرید اشتراک", "show_plans")],
        [btn("👤 حساب من", "my_account")],
        [btn("🤖 ربات من", "my_bots")],
        [btn("⚙️ تنظیمات", "open_settings")],
    )

def mode_selection_keyboard():
    return kb([btn("👤 با اسم (عادی)", "set_mode_normal")], [btn("🕵️ ناشناس", "set_mode_anonymous")])

def priority_keyboard(uid):
    return kb(
        [btn("🟢 عادی (رایگان)", "priority_normal")],
        [btn("🟡 ویژه (۱۰ سکه)", "priority_vip")],
        [btn("🔴 فوری (۳۰ سکه)", "priority_urgent")],
        [btn(f"💰 موجودی: {get_coins(uid)} سکه", "noop")],
    )

def plans_keyboard():
    rows = [[btn(f"⭐ {p['name']} — {p['price']} ({p['days']} روز)", f"buy_{pid}")] for pid, p in subscription_plans.items()]
    rows.append([back_btn("back_main")])
    return InlineKeyboardMarkup(rows)

def admin_panel_keyboard():
    status = "🟢 روشن" if bot_state["active"] else "🔴 خاموش"
    return kb(
        [btn("👥 لیست کاربران", "list_users")],
        [btn("📊 آمار", "stats")],
        [btn("📢 پیام همگانی", "broadcast")],
        [btn("💰 مدیریت سکه", "manage_coins")],
        [btn(f"⚡ وضعیت ربات: {status}", "toggle_bot")],
    )

# ── هندلرهای اصلی ───────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, uid = update.effective_user, update.effective_chat.id
    if update.effective_chat.type != "private": return
    if uid == ADMIN_CHAT_ID:
        await panel(update, context); return
    if not bot_state["active"]:
        await update.message.reply_text("⛔ *ربات در حال حاضر غیرفعال است.*\n\nلطفاً بعداً مراجعه کنید.", parse_mode="Markdown"); return
    users_db[uid] = {"name": user.full_name, "username": user.username or "ندارد", "chat_id": uid}
    ensure_profile(uid); update_last_seen(uid)
    if uid not in user_mode:
        await update.message.reply_text(
            "👋 *سلام!*\n\nقبل از شروع، نحوه نمایش هویتت رو انتخاب کن:\n\n"
            "━━━━━━━━━━━━━━━━\n👤 *با اسم* — ادمین اسم و پروفایلت رو میبینه\n"
            "🕵️ *ناشناس* — هیچ اطلاعاتی از تو نمیفرسته\n"
            "━━━━━━━━━━━━━━━━\n\n💡 هر وقت خواستی از /settings میتونی تغییرش بدی.",
            parse_mode="Markdown", reply_markup=mode_selection_keyboard())
    else:
        current = "🕵️ ناشناس" if user_mode[uid] == "anonymous" else "👤 عادی"
        await update.message.reply_text(
            f"👋 *سلام {user.first_name}!*\n\nحالت ارسال: {current}\nاشتراک: {subscription_status_text(uid)}\n\nاز منوی زیر ادامه بده 👇",
            parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    await update.message.reply_text("🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_panel_keyboard())

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if update.effective_chat.type != "private" or uid == ADMIN_CHAT_ID: return
    current = user_mode.get(uid)
    status_text = "🕵️ *ناشناس* (فعال)" if current == "anonymous" else ("👤 *عادی* (فعال)" if current == "normal" else "❓ هنوز انتخاب نشده")
    await update.message.reply_text(
        f"⚙️ *تنظیمات ارسال پیام*\n\nحالت فعلی: {status_text}\n\n"
        "━━━━━━━━━━━━━━━━\n👤 *عادی* — اسم و پروفایلت برای ادمین نمایش داده میشه\n"
        "🕵️ *ناشناس* — هیچ اطلاعاتی از تو ارسال نمیشه\n━━━━━━━━━━━━━━━━\n\nیه حالت انتخاب کن:",
        parse_mode="Markdown", reply_markup=mode_selection_keyboard())

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if uid != ADMIN_CHAT_ID: return
    
    # ریست کردن تمام حالت‌های انتظار ادمین
    reply_to.pop(ADMIN_CHAT_ID, None)
    group_mode.pop(ADMIN_CHAT_ID, None)
    pending_poll.pop(ADMIN_CHAT_ID, None)
    pending_coin_add.pop(ADMIN_CHAT_ID, None)
    pending_note_input.pop(ADMIN_CHAT_ID, None)
    context.bot_data.pop("pending_card", None)
    
    await update.message.reply_text("🔄 *عملیات فعلی لغو شد و وضعیت ادمین به حالت عادی برگشت.*", parse_mode="Markdown")

# ── فوروارد و ارسال پیام ────────────────────────────────────────────────────

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, uid = update.effective_user, update.effective_chat.id
    if update.effective_chat.type != "private" or uid == ADMIN_CHAT_ID: return
    if uid in blocked_users:
        await update.message.reply_text("⛔ شما مسدود شده‌اید."); return
    if not bot_state["active"]:
        await update.message.reply_text("⛔ *ربات در حال حاضر غیرفعال است.*\n\nلطفاً بعداً مراجعه کنید.", parse_mode="Markdown"); return
    update_last_seen(uid)

    # دریافت رسید
    if uid in pending_receipt_input:
        if not (update.message.photo or update.message.document):
            await update.message.reply_text("📸 لطفاً *تصویر* رسید پرداخت رو ارسال کن.", parse_mode="Markdown"); return
        pending_receipt_input.discard(uid)
        receipt_info = pending_receipts.get(uid)
        if not receipt_info:
            await update.message.reply_text("❌ خطایی پیش اومد. دوباره از /start شروع کن."); return
        plan      = subscription_plans.get(receipt_info["plan"], {})
        user_info = users_db.get(uid, {"name": str(uid), "username": "ندارد"})
        keyboard  = [[btn("✅ تایید و فعال‌سازی", f"approve_sub_{uid}::{receipt_info['plan']}"), btn("❌ رد کردن", f"reject_sub_{uid}")]]
        caption   = (f"🧾 *رسید پرداخت جدید*\n\n👤 کاربر: {user_info['name']}\n🆔 Chat ID: `{uid}`\n"
                     f"📦 پلن: {plan.get('name','؟')} ({plan.get('price','؟')})\n📅 مدت: {plan.get('days','؟')} روز\n⏰ زمان: {fmt_dt()}")
        try:
            if update.message.photo:
                await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=update.message.photo[-1].file_id, caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await context.bot.send_document(chat_id=ADMIN_CHAT_ID, document=update.message.document.file_id, caption=caption, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            await update.message.reply_text("✅ *رسید شما دریافت شد!*\n\nادمین در اسرع وقت بررسی و اشتراکت رو فعال می‌کنه.\n⏳ معمولاً کمتر از چند ساعت طول می‌کشه.", parse_mode="Markdown")
        except Exception:
            await update.message.reply_text("❌ خطا در ارسال رسید. دوباره امتحان کن.")
        return

    # ورود توکن ربات
    if uid in user_submitting_token:
        token_str = update.message.text.strip() if update.message.text else ""
        if not token_str:
            await update.message.reply_text("❌ توکن نامعتبر است. لطفاً توکن متنی ارسال کن."); return
        user_submitting_token.discard(uid)
        td = bot_tokens.get(token_str)
        if not td:
            await update.message.reply_text("❌ *توکن نامعتبر است!*\n\nاگه مشکل داری با ادمین تماس بگیر.", parse_mode="Markdown"); return
        if td["chat_id"] != uid:
            await update.message.reply_text("❌ این توکن متعلق به شما نیست."); return
        if td["used"]:
            await update.message.reply_text(f"⚠️ این توکن قبلاً استفاده شده.\n🤖 ربات: @{td.get('bot_username','؟')}", parse_mode="Markdown"); return
        context.user_data["pending_token"] = token_str
        await update.message.reply_text(
            "✅ *توکن معتبر است!*\n\n🤖 حالا یوزرنیم ربات تلگرامی که ساختی رو بفرست:\n(مثلاً: `@MyAwesomeBot`)\n\n📌 اگه هنوز ربات نساختی از @BotFather اقدام کن.",
            parse_mode="Markdown"); return

    # دریافت یوزرنیم ربات بعد از توکن
    if context.user_data.get("pending_token"):
        bot_username = update.message.text.strip() if update.message.text else ""
        if not bot_username:
            await update.message.reply_text("❌ یوزرنیم معتبر نیست."); return
        token_str = context.user_data.pop("pending_token")
        ok, msg   = use_bot_token(token_str, bot_username)
        if ok:
            await update.message.reply_text(
                f"🎉 *ربات شما ثبت شد!*\n\n🤖 یوزرنیم: {bot_username}\n🔑 توکن: `{token_str}`\n\nادمین از ثبت ربات شما باخبر شد.\nدر صورت نیاز به راه‌اندازی، با ادمین تماس بگیر. 🙏",
                parse_mode="Markdown", reply_markup=main_menu_keyboard())
            info = users_db.get(uid, {"name": str(uid)})
            try:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID,
                    text=f"🤖 *ربات جدید ثبت شد!*\n\n👤 کاربر: {info['name']} | `{uid}`\n🔑 توکن: `{token_str}`\n🤖 یوزرنیم ربات: {bot_username}\n⏰ زمان: {fmt_dt()}",
                    parse_mode="Markdown")
            except Exception: pass
        else:
            await update.message.reply_text(f"❌ خطا: {msg}")
        return

    if uid not in user_mode:
        await update.message.reply_text("⚠️ قبل از ارسال پیام، لطفاً حالت ارسالت رو انتخاب کن:", parse_mode="Markdown", reply_markup=mode_selection_keyboard()); return

    users_db[uid] = {"name": user.full_name, "username": user.username or "ندارد", "chat_id": uid}
    increment_msg(uid)

    if update.message.text:
        context.user_data["pending_text"] = update.message.text
        await update.message.reply_text(
            "📨 پیامت آماده ارسال شد!\n\nبا چه اولویتی ارسال شه?\n\n🟢 *عادی* — رایگان\n🟡 *ویژه* — ۱۰ سکه\n🔴 *فوری* — ۳۰ سکه",
            parse_mode="Markdown", reply_markup=priority_keyboard(uid)); return

    await send_user_message(context, uid, user, priority="normal", text=None, original_message=update.message, confirm_target=update.message)


async def send_user_message(context, uid, user, priority="normal", text=None, original_message=None, confirm_target=None):
    level       = PRIORITY_LEVELS[priority]
    priority_tag = "\n🟡 *پیام ویژه*" if priority == "vip" else ("\n🔴 *پیام فوری* ⚡️" if priority == "urgent" else "")
    is_anonymous = user_mode[uid] == "anonymous"
    sub_tag      = " | ⭐ اشتراک فعال" if has_active_subscription(uid) else ""
    keyboard     = [[btn("↩️ پاسخ", f"reply_{uid}"), btn("🚫 بلاک", f"block_{uid}")]]
    sender_info  = (
        f"📩 *پیام جدید*{priority_tag}\n🕵️ *ناشناس*{sub_tag}\n🔢 Chat ID: `{uid}`\n{'─'*25}"
        if is_anonymous else
        f"📩 *پیام جدید*{priority_tag}\n👤 نام: {user.full_name}{sub_tag}\n🆔 یوزرنیم: @{user.username or 'ندارد'}\n🔢 Chat ID: `{uid}`\n{'─'*25}"
    )
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=sender_info, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    if text is not None:
        fwd = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    elif is_anonymous:
        fwd = await original_message.copy_to(chat_id=ADMIN_CHAT_ID)
    else:
        fwd = await original_message.forward(chat_id=ADMIN_CHAT_ID)
    message_map[f"reply_{uid}"] = fwd.message_id
    if level["cost"] > 0: add_coins(uid, -level["cost"], f"ارسال پیام با اولویت {level['title']}")
    confirm_text = "✅ پیامت دریافت شد، به زودی جواب میگیری."
    if priority == "vip":    confirm_text = "✅ پیام *ویژه*‌ت ارسال شد! 🟡 سریع‌تر بررسی میشه."
    elif priority == "urgent": confirm_text = "✅ پیام *فوری*‌ت ارسال شد! 🔴 در صدر لیست قرار گرفت."
    if is_anonymous: confirm_text += " 🕵️"
    if confirm_target:
        await confirm_target.reply_text(confirm_text, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=uid, text=confirm_text, parse_mode="Markdown")

# ── نظرسنجی ─────────────────────────────────────────────────────────────────

async def send_poll_to_target(context, poll_info, target):
    question, options = poll_info["question"], poll_info["options"]
    def _store(poll_id):
        poll_votes[poll_id] = {"question": question, "options": {i: 0 for i in range(len(options))}, "opt_names": options, "total": 0}
    if target == "all":
        success = 0
        for uid in users_db:
            if uid not in blocked_users:
                try:
                    sent = await context.bot.send_poll(chat_id=uid, question=question, options=options, is_anonymous=False)
                    _store(sent.poll.id); success += 1
                except Exception: pass
        return success
    else:
        try:
            sent = await context.bot.send_poll(chat_id=target, question=question, options=options, is_anonymous=False)
            _store(sent.poll.id); return 1
        except Exception: return 0

async def handle_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    answer, poll_id = update.poll_answer, update.poll_answer.poll_id
    if poll_id not in poll_votes:
        poll_votes[poll_id] = {"question": "نظرسنجی", "options": {}, "opt_names": [], "total": 0}
    info = poll_votes[poll_id]
    info["total"] = info.get("total", 0) + 1
    for opt_id in answer.option_ids:
        info["options"][opt_id] = info["options"].get(opt_id, 0) + 1
    total = info["total"]
    lines = [f"📊 *نتایج نظرسنجی* (تا این لحظه)\n❓ {info['question']}\n"]
    for i, name in enumerate(info.get("opt_names", [])):
        count = info["options"].get(i, 0)
        pct   = round(count / total * 100) if total else 0
        lines.append(f"• {name}\n  {'█'*(pct//10)}{'░'*(10-pct//10)} {pct}% ({count} نفر)")
    lines.append(f"\n👥 مجموع شرکت‌کنندگان: {total}")
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="\n".join(lines), parse_mode="Markdown")
    except Exception: pass

# ── هندلر دکمه‌ها ───────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, data, uid = update.callback_query, update.callback_query.data, update.callback_query.message.chat.id
    await query.answer()
    if data == "noop": return

    quid = query.from_user.id

    # انتخاب حالت کاربر
    if data in ("set_mode_normal", "set_mode_anonymous"):
        if quid == ADMIN_CHAT_ID: return
        user_mode[quid] = "normal" if data == "set_mode_normal" else "anonymous"
        label = ("✅ *حالت عادی فعال شد!*\n\n👤 اسم و پروفایلت همراه پیامت ارسال میشه.\n\nاز منوی زیر ادامه بده 👇"
                 if data == "set_mode_normal" else
                 "✅ *حالت ناشناس فعال شد!*\n\n🕵️ هیچ اطلاعاتی از تو ارسال نمیشه.\n\nاز منوی زیر ادامه بده 👇")
        await query.edit_message_text(label, parse_mode="Markdown", reply_markup=main_menu_keyboard()); return

    if data == "back_main":
        current = "🕵️ ناشناس" if user_mode.get(quid) == "anonymous" else "👤 عادی"
        await query.edit_message_text(
            f"🏠 *منوی اصلی*\n\nحالت ارسال: {current}\nاشتراک: {subscription_status_text(quid)}\n\nیه گزینه انتخاب کن 👇",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()); return

    if data == "goto_send":
        if quid == ADMIN_CHAT_ID: return
        if not bot_state["active"]:
            await query.edit_message_text("⚠️ ربات در حال حاضر غیرفعال است."); return
        await query.edit_message_text("📨 *ارسال پیام به ادمین*\n\nپیامت رو بنویس و ارسال کن 👇\n\n(متن، عکس، فایل — همه پذیرفته میشه)", parse_mode="Markdown"); return

    if data == "open_settings":
        if quid == ADMIN_CHAT_ID: return
        current = user_mode.get(quid)
        status_text = "🕵️ *ناشناس*" if current == "anonymous" else ("👤 *عادی*" if current == "normal" else "❓ هنوز انتخاب نشده")
        await query.edit_message_text(f"⚙️ *تنظیمات*\n\nحالت فعلی: {status_text}\n\nیه حالت انتخاب کن:", parse_mode="Markdown", reply_markup=mode_selection_keyboard()); return

    if data == "my_account":
        if quid == ADMIN_CHAT_ID: return
        p = ensure_profile(quid)
        history_text = "\n".join(user_history.get(quid, [])[-5:]) or "ندارید"
        await query.edit_message_text(
            f"👤 *حساب من*\n\n💰 موجودی سکه: {get_coins(quid)}\n🔐 حالت ارسال: {'🕵️ ناشناس' if user_mode.get(quid)=='anonymous' else '👤 عادی'}\n"
            f"📦 اشتراک: {subscription_status_text(quid)}\n📨 تعداد پیام‌های ارسالی: {p.get('msg_count',0)}\n📅 عضویت: {p.get('join_date','؟')}\n\n"
            f"📋 *آخرین تراکنش‌های سکه:*\n{history_text}",
            parse_mode="Markdown", reply_markup=kb([back_btn("back_main")])); return

    if data == "my_bots":
        if quid == ADMIN_CHAT_ID: return
        tokens  = user_bot_tokens.get(quid, [])
        has_sub = has_active_subscription(quid)
        if not tokens:
            msg = ("🤖 *ربات من*\n\n✅ اشتراک شما فعال است.\n\nبرای دریافت توکن ربات‌سازی، به ادمین پیام بده\nو درخواست توکن کن."
                   if has_sub else
                   "🤖 *ربات من*\n\nشما هنوز توکنی دریافت نکرده‌اید.\n\nبرای دریافت توکن ربات‌سازی، ابتدا اشتراک خریداری کنید\nو سپس از ادمین درخواست توکن کنید.")
            await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=kb(
                [btn("📨 پیام به ادمین", "goto_send")],
                [btn("🛒 خرید اشتراک", "show_plans")],
                [back_btn("back_main")])); return
        text     = "🤖 *ربات‌های من*\n\n"
        kb_rows  = []
        for t in tokens:
            td    = bot_tokens.get(t, {})
            text += f"🔑 `{t}`\n   {'✅ فعال — @' + td.get('bot_username','؟') if td.get('used') else '⏳ استفاده نشده'}\n\n"
        if any(not bot_tokens.get(t, {}).get("used") for t in tokens):
            kb_rows.append([btn("🔑 وارد کردن توکن", "submit_token")])
        kb_rows.append([back_btn("back_main")])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb_rows)); return

    if data == "submit_token":
        if quid == ADMIN_CHAT_ID: return
        user_submitting_token.add(quid)
        await query.edit_message_text("🔑 *وارد کردن توکن ربات‌سازی*\n\nتوکنی که از ادمین دریافت کردی رو اینجا بفرست:\n(مثلاً: `BOT-A3X9K2AB`)\n\n⚠️ هر توکن فقط یک بار قابل استفاده است.", parse_mode="Markdown"); return

    if data == "show_plans":
        if quid == ADMIN_CHAT_ID: return
        pending_receipt_input.discard(quid); pending_receipts.pop(quid, None)
        text = (
            "🛒 *خرید اشتراک*\n━━━━━━━━━━━━━━━━━━\n\n"
            "✨ *با خرید اشتراک به این امکانات دسترسی داری:*\n\n"
            "🤖 *ربات اختصاصی* — یه ربات تلگرامی کاملاً مخصوص خودت\n"
            "🔑 *توکن ربات‌سازی* — توکن یکتا برای ثبت ربات\n"
            "📨 *ارسال پیام اولویت‌دار* — ویژه 🟡 و فوری 🔴\n"
            "💰 *سکه رایگان* — با هر اشتراک\n⭐ *نشان اشتراک فعال* — اولویت بیشتر\n\n"
            "━━━━━━━━━━━━━━━━━━\n📦 *پلن‌های موجود:*\n\n"
        )
        for pid, plan in subscription_plans.items():
            text += f"⭐ *{plan['name']}* — {plan['price']}\n📅 {plan['description']}\n\n"
        text += "👇 یه پلن انتخاب کن و شروع کن:"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=plans_keyboard()); return

    if data.startswith("buy_"):
        if quid == ADMIN_CHAT_ID: return
        plan_id = data[4:]; plan = subscription_plans.get(plan_id)
        if not plan: return
        pending_receipts[quid] = {"plan": plan_id}; pending_receipt_input.add(quid)
        await query.edit_message_text(
            f"💳 *اطلاعات پرداخت*\n━━━━━━━━━━━━━━━━\n\n"
            f"📦 پلن انتخابی: *{plan['name']}*\n💰 مبلغ: *{plan['price']}*\n📅 مدت اشتراک: {plan['days']} روز\n\n"
            f"━━━━━━━━━━━━━━━━\n💳 شماره کارت:\n`{bot_config['card_number']}`\n👤 به نام: *{bot_config['card_owner']}*\n"
            f"━━━━━━━━━━━━━━━━\n\n🤖 *بعد از فعال‌سازی اشتراک:*\nیه توکن اختصاصی دریافت می‌کنی!\n\n📸 بعد از پرداخت، *تصویر رسید* رو اینجا ارسال کن 👇\n_(ادمین بررسی و اشتراکت رو فعال می‌کنه)_",
            parse_mode="Markdown", reply_markup=kb([btn("🔙 انصراف", "show_plans")])); return

    if data.startswith("approve_sub_"):
        if uid != ADMIN_CHAT_ID: return
        target_id_str, plan_id = data[len("approve_sub_"):].split("::", 1)
        target_id = int(target_id_str)
        plan      = subscription_plans.get(plan_id, {})
        expires   = now_tehran() + timedelta(days=plan.get("days", 30))
        user_subscriptions[target_id] = {"plan": plan_id, "expires": expires}
        pending_receipts.pop(target_id, None); pending_receipt_input.discard(target_id)
        suffix = f"\n\n✅ *تایید شد* توسط ادمین — {now_tehran().strftime('%H:%M')}"
        try:
            if query.message.caption is not None:
                await query.edit_message_caption(caption=query.message.caption + suffix, parse_mode="Markdown")
            else:
                await query.edit_message_text(text=(query.message.text or "") + suffix, parse_mode="Markdown")
        except Exception: await query.answer("✅ اشتراک تایید شد.")
        try:
            await context.bot.send_message(chat_id=target_id,
                text=f"🎉 *اشتراک شما فعال شد!*\n\n📦 پلن: *{plan.get('name','؟')}*\n📅 تاریخ انقضا: {expires.strftime('%Y-%m-%d')} ساعت {expires.strftime('%H:%M')} (تهران)\n\nممنون که ما رو انتخاب کردید 🙏",
                parse_mode="Markdown", reply_markup=main_menu_keyboard())
        except Exception: pass
        return

    if data.startswith("reject_sub_"):
        if uid != ADMIN_CHAT_ID: return
        target_id = int(data[len("reject_sub_"):])
        pending_receipts.pop(target_id, None); pending_receipt_input.discard(target_id)
        suffix = f"\n\n❌ *رد شد* توسط ادمین — {now_tehran().strftime('%H:%M')}"
        try:
            if query.message.caption is not None:
                await query.edit_message_caption(caption=query.message.caption + suffix, parse_mode="Markdown")
            else:
                await query.edit_message_text(text=(query.message.text or "") + suffix, parse_mode="Markdown")
        except Exception: await query.answer("❌ رسید رد شد.")
        try:
            await context.bot.send_message(chat_id=target_id,
                text="❌ *رسید پرداخت تایید نشد.*\n\nممکنه مبلغ، شماره کارت یا رسید مشکل داشته باشه.\nدر صورت نیاز با ادمین تماس بگیر.", parse_mode="Markdown")
        except Exception: pass
        return

    if data in ("priority_normal", "priority_vip", "priority_urgent"):
        if quid == ADMIN_CHAT_ID: return
        priority = data.split("_")[1]
        level    = PRIORITY_LEVELS[priority]
        coins    = get_coins(quid)
        if level["cost"] > coins:
            await query.answer(f"❌ سکه کافی نداری! ({coins}/{level['cost']})", show_alert=True); return
        pending_text = context.user_data.get("pending_text")
        if not pending_text:
            await query.edit_message_text("⚠️ پیام منقضی شده، لطفاً دوباره ارسال کن."); return
        await send_user_message(context, quid, query.from_user, priority=priority, text=pending_text)
        context.user_data.pop("pending_text", None)
        await query.edit_message_reply_markup(reply_markup=None); return

    # ── دکمه‌های ادمین ──────────────────────────────────────────────────────
    if uid != ADMIN_CHAT_ID: return

    if data.startswith("reply_"):
        target_id = int(data.split("_")[1])
        reply_to[ADMIN_CHAT_ID] = target_id
        name = users_db.get(target_id, {}).get("name", "ناشناس") if user_mode.get(target_id) != "anonymous" else "🕵️ ناشناس"
        await query.message.reply_text(f"✍️ *در حال پاسخ به {name}*\n\nهر پیامی بفرستی (متن، استیکر، گیف، عکس و...) براش کپی میشه.\n\n💡 برای انصراف کلمه `انصراف` یا /cancel رو بفرست.", parse_mode="Markdown"); return

    if data.startswith("block_"):
        target_id = int(data.split("_")[1])
        blocked_users.add(target_id)
        ensure_profile(target_id).setdefault("block_history", []).append(f"🚫 بلاک شد — {fmt_dt()}")
        await query.message.reply_text(f"🚫 کاربر *{users_db.get(target_id, {}).get('name', target_id)}* بلاک شد.", parse_mode="Markdown"); return

    if data.startswith("unblock_"):
        target_id = int(data.split("_")[1])
        blocked_users.discard(target_id)
        ensure_profile(target_id).setdefault("block_history", []).append(f"✅ آنبلاک شد — {fmt_dt()}")
        await query.message.reply_text(f"✅ کاربر *{users_db.get(target_id, {}).get('name', target_id)}* آنبلاک شد.", parse_mode="Markdown"); return

    if data == "list_users":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری."); return
        text, keyboard = "👥 *لیست کاربران:*\n\n", []
        for u_id, info in users_db.items():
            p     = ensure_profile(u_id)
            text += f"{'🚫' if u_id in blocked_users else '✅'}{'🕵️' if user_mode.get(u_id)=='anonymous' else '👤'}{'⭐' if has_active_subscription(u_id) else ''} {info['name']} | @{info['username']} | `{u_id}` | 💰{get_coins(u_id)} | 📨{p.get('msg_count',0)}\n"
            keyboard.append([
                btn(f"👁 {info['name']}", f"full_profile_{u_id}"),
                btn("↩️ پاسخ", f"reply_{u_id}"),
                btn("🚫" if u_id not in blocked_users else "✅ آنبلاک", f"{'block' if u_id not in blocked_users else 'unblock'}_{u_id}"),
            ])
        keyboard.append([back_btn()])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data == "list_blocked":
        if not blocked_users:
            await query.message.reply_text("🚫 هیچ کاربری بلاک نشده."); return
        text, keyboard = "🚫 *کاربران بلاک‌شده:*\n\n", []
        for b_id in blocked_users:
            info  = users_db.get(b_id, {"name": str(b_id), "username": "ندارد"})
            text += f"🚫 {info['name']} | @{info['username']} | `{b_id}`\n"
            keyboard.append([btn(f"✅ آنبلاک {info['name']}", f"unblock_{b_id}")])
        keyboard.append([back_btn()])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data == "stats":
        total    = len(users_db)
        blocked  = len(blocked_users)
        anon     = sum(1 for u_id in users_db if user_mode.get(u_id) == "anonymous")
        normal   = sum(1 for u_id in users_db if user_mode.get(u_id) == "normal")
        with_sub = sum(1 for u_id in users_db if has_active_subscription(u_id))
        await query.message.reply_text(
            f"📊 *آمار ربات*\n\n👥 کل کاربران: {total}\n✅ فعال: {total-blocked}\n🚫 بلاک‌شده: {blocked}\n⭐ دارای اشتراک: {with_sub}\n"
            f"━━━━━━━━━━━━\n🕵️ ناشناس: {anon}\n👤 عادی: {normal}\n━━━━━━━━━━━━\n"
            f"⚡ وضعیت ربات: {'🟢 روشن' if bot_state['active'] else '🔴 خاموش'}",
            parse_mode="Markdown", reply_markup=kb([back_btn()])); return

    if data == "broadcast":
        reply_to[ADMIN_CHAT_ID] = "broadcast"
        await query.message.reply_text("📢 پیام همگانیت رو بنویس (یا بفرست انصراف):"); return

    if data == "send_group":
        group_mode[ADMIN_CHAT_ID] = "waiting_id"
        await query.message.reply_text("👥 *ارسال به گروه*\n\nآیدی عددی گروه رو بفرست:\n(مثلاً: `-1001234567890`)", parse_mode="Markdown"); return

    if data == "back":
        await query.message.reply_text("🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_panel_keyboard()); return

    if data == "create_poll":
        pending_poll[ADMIN_CHAT_ID] = {"step": "question"}
        await query.message.reply_text("🗳 *ساخت نظرسنجی*\n\nسوال نظرسنجی رو بنویس:", parse_mode="Markdown"); return

    if data == "poll_target_all":
        info = pending_poll.get(ADMIN_CHAT_ID)
        if not info: return
        success = await send_poll_to_target(context, info, "all")
        del pending_poll[ADMIN_CHAT_ID]
        await query.message.reply_text(f"✅ نظرسنجی برای {success} کاربر ارسال شد.\n\n📊 نتایج به محض پاسخ کاربران برات ارسال میشه."); return

    if data == "poll_target_group":
        info = pending_poll.get(ADMIN_CHAT_ID)
        if not info: return
        info["step"] = "waiting_group_id"
        await query.message.reply_text("👥 آیدی عددی گروه رو بفرست:\n(مثلاً `-1001234567890`)", parse_mode="Markdown"); return

    if data == "manage_coins":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری."); return
        text, keyboard = "💰 *مدیریت سکه کاربران*\n\n", []
        for u_id, info in users_db.items():
            coins  = get_coins(u_id)
            text  += f"👤 {info['name']} | `{u_id}` | 💰 {coins}\n"
            keyboard.append([btn(f"💰 {info['name']} ({coins} سکه)", f"addcoin_{u_id}")])
        keyboard.append([back_btn()])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data.startswith("addcoin_"):
        target_id = int(data.split("_")[1])
        pending_coin_add[ADMIN_CHAT_ID] = target_id
        info = users_db.get(target_id, {"name": str(target_id)})
        await query.message.reply_text(
            f"💰 *افزودن/کاهش سکه*\n\nکاربر: {info['name']} | `{target_id}`\nموجودی فعلی: {get_coins(target_id)} سکه\n\nیه عدد بفرست (مثبت یا منفی، مثلاً `20` یا `-10`):",
            parse_mode="Markdown"); return

    if data == "manage_subs":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری."); return
        text, keyboard = "🛒 *مدیریت اشتراک‌ها*\n\n", []
        for u_id, info in users_db.items():
            text += f"👤 {info['name']} | {subscription_status_text(u_id)}\n"
            keyboard.append([btn(f"⭐ {info['name']}", f"sub_manage_{u_id}")])
        keyboard.append([back_btn()])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data.startswith("sub_manage_"):
        target_id    = int(data[len("sub_manage_"):])
        info         = users_db.get(target_id, {"name": str(target_id)})
        plan_keyboard = [[btn(f"➕ اضافه کن: {p['name']} ({p['days']} روز)", f"admin_add_sub_{target_id}__{pid}")] for pid, p in subscription_plans.items()]
        plan_keyboard += [[btn("🗑 لغو اشتراک", f"admin_del_sub_{target_id}")], [back_btn("manage_subs")]]
        await query.message.reply_text(f"👤 *{info['name']}*\n\nاشتراک فعلی: {subscription_status_text(target_id)}\n\nیه عملیات انتخاب کن:", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(plan_keyboard)); return

    if data.startswith("admin_add_sub_"):
        target_id_str, plan_id = data[len("admin_add_sub_"):].split("__", 1)
        target_id = int(target_id_str)
        plan      = subscription_plans.get(plan_id, {})
        current   = user_subscriptions.get(target_id, {})
        base      = current.get("expires", now_tehran())
        if base < now_tehran(): base = now_tehran()
        expires   = base + timedelta(days=plan.get("days", 30))
        user_subscriptions[target_id] = {"plan": plan_id, "expires": expires}
        info = users_db.get(target_id, {"name": str(target_id)})
        await query.message.reply_text(f"✅ اشتراک *{plan.get('name','؟')}* برای *{info['name']}* فعال شد.\n📅 انقضا: {expires.strftime('%Y-%m-%d')}", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_id,
                text=f"🎉 *اشتراک شما فعال شد!*\n\n📦 پلن: *{plan['name']}*\n📅 انقضا: {expires.strftime('%Y-%m-%d')} ساعت {expires.strftime('%H:%M')} (تهران)\n\nممنون که ما رو انتخاب کردید 🙏",
                parse_mode="Markdown")
        except Exception: pass
        return

    if data.startswith("admin_del_sub_"):
        target_id = int(data[len("admin_del_sub_"):])
        user_subscriptions.pop(target_id, None)
        info = users_db.get(target_id, {"name": str(target_id)})
        await query.message.reply_text(f"🗑 اشتراک *{info['name']}* لغو شد.", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_id, text="⚠️ اشتراک شما توسط ادمین لغو شد.")
        except Exception: pass
        return

    if data == "pending_receipts_admin":
        if not pending_receipts:
            await query.message.reply_text("✅ رسید در انتظاری وجود نداره."); return
        text = "🧾 *رسیدهای در انتظار تایید:*\n\n"
        for u_id, receipt in pending_receipts.items():
            info  = users_db.get(u_id, {"name": str(u_id)})
            text += f"👤 {info['name']} | `{u_id}` | پلن: {subscription_plans.get(receipt['plan'],{}).get('name','؟')}\n"
        text += "\n⚠️ رسیدها به صورت تصویر ارسال میشن و باید از روی تصویر تایید/رد کنی."
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb([back_btn()])); return

    if data == "set_card":
        await query.message.reply_text(
            f"💳 *تنظیم اطلاعات کارت بانکی*\n\nشماره فعلی: `{bot_config['card_number']}`\nنام فعلی: {bot_config['card_owner']}\n\nشماره کارت جدید رو بفرست (فقط اعداد، مثلاً `6037991312345678`):\nیا بنویس /cancel برای انصراف",
            parse_mode="Markdown")
        context.bot_data["pending_card"] = "number"; return

    if data == "toggle_bot":
        bot_state["active"] = not bot_state["active"]
        status = "🟢 روشن شد" if bot_state["active"] else "🔴 خاموش شد"
        msg    = "کاربران میتونن پیام بفرستن." if bot_state["active"] else "⛔ کاربران به هیچ چیزی دسترسی ندارن."
        await query.message.reply_text(f"⚡ *وضعیت ربات:* {status}\n\n{msg}", parse_mode="Markdown", reply_markup=admin_panel_keyboard()); return

    if data == "manage_tokens":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری."); return
        text = (
            "🤖 *مدیریت توکن ربات‌سازی*\n\n━━━━━━━━━━━━━━━━━━\n"
            "این بخش بهت اجازه میده به کاربرانی که اشتراک خریدن\nیه توکن یکتا بدی تا باهاش ربات بسازن.\n\n"
            "📌 *روند کار:*\n۱. کاربر اشتراک میخره و رسید میفرسته\n۲. تو اشتراک رو تایید میکنی\n"
            "۳. از اینجا بهش توکن میدی\n۴. کاربر توکن رو در ربات وارد میکنه\n۵. یوزرنیم ربات ثبت میشه\n━━━━━━━━━━━━━━━━━━\n\nیه کاربر انتخاب کن:"
        )
        keyboard = [[btn(f"{'⭐' if has_active_subscription(u_id) else '  '} {info['name']} — {len(user_bot_tokens.get(u_id,[]))} توکن", f"token_for_{u_id}")] for u_id, info in users_db.items()]
        keyboard += [[btn("📋 همه توکن‌ها", "list_all_tokens")], [back_btn()]]
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data.startswith("token_for_"):
        target_id   = int(data[len("token_for_"):])
        info        = users_db.get(target_id, {"name": str(target_id)})
        tokens      = user_bot_tokens.get(target_id, [])
        token_lines = "".join(
            f"  {'✅' if bot_tokens.get(t,{}).get('used') else '⏳'} `{t}` — {'@' + bot_tokens.get(t,{}).get('bot_username','؟') if bot_tokens.get(t,{}).get('used') else 'استفاده نشده'}\n"
            for t in tokens
        ) or "  — توکنی ندارد\n"
        await query.message.reply_text(
            f"🤖 *توکن‌های {info['name']}*\n\n📦 اشتراک: {subscription_status_text(target_id)}\n\n🔑 توکن‌ها:\n{token_lines}",
            parse_mode="Markdown", reply_markup=kb(
                [btn("🆕 صدور توکن جدید", f"issue_token_{target_id}")],
                [btn("👁 پروفایل کامل", f"full_profile_{target_id}")],
                [back_btn("manage_tokens")])); return

    if data.startswith("issue_token_"):
        target_id = int(data[len("issue_token_"):])
        info      = users_db.get(target_id, {"name": str(target_id)})
        if not has_active_subscription(target_id):
            await query.message.reply_text(
                f"⚠️ *{info['name']}* اشتراک فعال ندارد!\n\nآیا مطمئنی میخوای توکن بدی?",
                parse_mode="Markdown", reply_markup=kb(
                    [btn("✅ بله، صادر کن", f"confirm_issue_{target_id}")],
                    [btn("❌ خیر", f"token_for_{target_id}")])); return
        token = create_bot_token(target_id)
        await query.message.reply_text(
            f"✅ *توکن جدید صادر شد!*\n\n👤 کاربر: {info['name']} | `{target_id}`\n🔑 توکن: `{token}`\n⏰ زمان: {fmt_dt()}\n\n📤 ارسال توکن به کاربر...",
            parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_id,
                text=f"🎉 *توکن ربات‌سازی شما صادر شد!*\n\n🔑 توکن اختصاصی شما:\n`{token}`\n\n━━━━━━━━━━━━━━━━\n📌 *راهنمای استفاده:*\n۱. از @BotFather یه ربات جدید بساز\n۲. به منوی «🤖 ربات من» برو\n۳. روی «🔑 وارد کردن توکن» کلیک کن\n۴. توکن بالا رو کپی و ارسال کن\n۵. یوزرنیم ربات جدیدت رو وارد کن\n\n⚠️ این توکن فقط یک بار قابل استفاده است.\n⚠️ توکن را به کسی ندهید!",
                parse_mode="Markdown", reply_markup=kb([btn("🤖 ربات من", "my_bots")]))
            await query.message.reply_text("✅ توکن با موفقیت به کاربر ارسال شد.")
        except Exception as e:
            await query.message.reply_text(f"⚠️ توکن صادر شد ولی ارسال به کاربر ناموفق بود:\n{e}")
        return

    if data.startswith("confirm_issue_"):
        target_id = int(data[len("confirm_issue_"):])
        info  = users_db.get(target_id, {"name": str(target_id)})
        token = create_bot_token(target_id)
        await query.message.reply_text(f"✅ توکن `{token}` برای *{info['name']}* صادر شد (بدون اشتراک).", parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_id,
                text=f"🎉 *توکن ربات‌سازی شما صادر شد!*\n\n🔑 توکن: `{token}`\n\nبرای استفاده به منوی «🤖 ربات من» برو.",
                parse_mode="Markdown")
        except Exception: pass
        return

    if data == "list_all_tokens":
        if not bot_tokens:
            await query.message.reply_text("🔑 هیچ توکنی صادر نشده."); return
        text = "📋 *همه توکن‌های صادرشده:*\n\n"
        for t, td in bot_tokens.items():
            info   = users_db.get(td["chat_id"], {"name": str(td["chat_id"])})
            status = f"✅ @{td['bot_username']}" if td.get("used") else "⏳ استفاده نشده"
            text  += f"🔑 `{t}`\n👤 {info['name']} | {status}\n\n"
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=kb([back_btn("manage_tokens")])); return

    if data.startswith("full_profile_"):
        target_id = int(data[len("full_profile_"):])
        await query.message.reply_text(
            get_full_profile_text(target_id), parse_mode="Markdown",
            reply_markup=kb(
                [btn("↩️ پاسخ", f"reply_{target_id}")],
                [btn("📝 یادداشت", f"set_note_{target_id}")],
                [btn("🤖 توکن جدید", f"issue_token_{target_id}")],
                [btn("🚫 بلاک" if target_id not in blocked_users else "✅ آنبلاک",
                     f"{'block' if target_id not in blocked_users else 'unblock'}_{target_id}")],
                [back_btn("list_users")])); return

    if data.startswith("set_note_"):
        target_id    = int(data[len("set_note_"):])
        pending_note_input[ADMIN_CHAT_ID] = target_id
        info         = users_db.get(target_id, {"name": str(target_id)})
        current_note = user_profiles.get(target_id, {}).get("admin_note") or "—"
        await query.message.reply_text(
            f"📝 *یادداشت برای {info['name']}*\n\nیادداشت فعلی: {current_note}\n\nیادداشت جدید رو بنویس (یا بفرست 'حذف' تا پاک بشه):",
            parse_mode="Markdown"); return

# ── هندلر جامع پیام‌های ادمین (پشتیبانی از مولتی‌مدیا) ──────────────────────────

async def handle_admin_media_and_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if update.effective_chat.type != "private": return
    
    # اگر کاربر عادی بود، به عنوان پیام جدید فورواردش کن
    if uid != ADMIN_CHAT_ID:
        await forward_message(update, context); return

    text = update.message.text or ""
    
    # بررسی دستور انصراف متنی یا دستوری
    if text.strip() in ("انصراف", "/cancel"):
        await cancel_command(update, context)
        return

    # یادداشت ادمین برای کاربر
    if ADMIN_CHAT_ID in pending_note_input:
        if not update.message.text:
            await update.message.reply_text("❌ یادداشت فقط باید متنی باشد."); return
        target_id = pending_note_input.pop(ADMIN_CHAT_ID)
        p = ensure_profile(target_id)
        if text.strip() == "حذف":
            p["admin_note"] = ""
            await update.message.reply_text("🗑 یادداشت حذف شد.")
        else:
            p["admin_note"] = text.strip()
            await update.message.reply_text(f"📝 یادداشت ذخیره شد:\n{text.strip()}")
        return

    # تنظیم شماره کارت
    pending_card = context.bot_data.get("pending_card")
    if pending_card == "number":
        digits = text.strip().replace("-", "").replace(" ", "")
        if not digits.isdigit() or len(digits) != 16:
            await update.message.reply_text("❌ شماره کارت باید ۱۶ رقم باشه. دوباره بفرست:"); return
        bot_config["card_number"] = "-".join([digits[i:i+4] for i in range(0, 16, 4)])
        context.bot_data["pending_card"] = "owner"
        await update.message.reply_text(f"✅ شماره کارت ذخیره شد: `{bot_config['card_number']}`\n\nحالا نام صاحب کارت رو بفرست:", parse_mode="Markdown"); return
    if pending_card == "owner":
        bot_config["card_owner"] = text.strip()
        context.bot_data.pop("pending_card", None)
        await update.message.reply_text(
            f"✅ اطلاعات کارت بروز شد!\n\n💳 شماره: `{bot_config['card_number']}`\n👤 نام: {bot_config['card_owner']}",
            parse_mode="Markdown", reply_markup=admin_panel_keyboard()); return

    # مدیریت سکه
    if ADMIN_CHAT_ID in pending_coin_add:
        target_id = pending_coin_add.pop(ADMIN_CHAT_ID)
        try:
            amount = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد بفرست (مثلاً 20 یا -10)."); return
        new_balance = add_coins(target_id, amount, "تغییر دستی توسط ادمین")
        info  = users_db.get(target_id, {"name": str(target_id)})
        sign  = "+" if amount >= 0 else ""
        await update.message.reply_text(
            f"✅ موجودی *{info['name']}* بروز شد.\nتغییر: {sign}{amount} سکه\nموجودی جدید: 💰 {new_balance}",
            parse_mode="Markdown")
        try:
            await context.bot.send_message(chat_id=target_id,
                text=f"💰 *موجودی سکه‌ات تغییر کرد!*\n\n{'➕' if amount>=0 else '➖'} {abs(amount)} سکه\nموجودی جدید: {new_balance} سکه",
                parse_mode="Markdown")
        except Exception: pass
        return

    # نظرسنجی
    if ADMIN_CHAT_ID in pending_poll:
        info = pending_poll[ADMIN_CHAT_ID]
        step = info.get("step")
        if step == "question":
            info["question"] = text; info["step"] = "options"; info["options"] = []
            await update.message.reply_text("📝 گزینه‌های نظرسنجی رو یکی‌یکی بفرست.\n\nوقتی تموم شد، بنویس: *تمام*\n(حداقل ۲ گزینه لازمه)", parse_mode="Markdown"); return
        if step == "options":
            if text.strip() == "تمام":
                if len(info["options"]) < 2:
                    await update.message.reply_text("❌ حداقل ۲ گزینه لازمه."); return
                info["step"] = "target"
                preview = "\n".join(f"• {o}" for o in info["options"])
                await update.message.reply_text(
                    f"🗳 *پیش‌نمایش نظرسنجی:*\n\n❓ {info['question']}\n\n{preview}\n\nکجا ارسال شه?",
                    parse_mode="Markdown", reply_markup=kb(
                        [btn("👥 ارسال به همه کاربران", "poll_target_all")],
                        [btn("👥 ارسال به یک گروه", "poll_target_group")]))
            else:
                info["options"].append(text.strip())
                await update.message.reply_text(f"✅ گزینه «{text.strip()}» اضافه شد. ({len(info['options'])} گزینه)\n\nگزینه بعدی یا بنویس *تمام*", parse_mode="Markdown")
            return
        if step == "waiting_group_id":
            try:
                group_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("❌ آیدی باید عدد باشه مثل -1001234567890"); return
            success = await send_poll_to_target(context, info, group_id)
            del pending_poll[ADMIN_CHAT_ID]
            await update.message.reply_text("✅ نظرسنجی به گروه ارسال شد.\n📊 نتایج به محض پاسخ کاربران برات ارسال میشه." if success else "❌ ارسال ناموفق. مطمئن شو ربات ادمین گروهه.")
            return

    # ارسال به گروه
    if group_mode.get(ADMIN_CHAT_ID) == "waiting_id":
        try:
            group_mode[ADMIN_CHAT_ID] = int(text.strip())
            await update.message.reply_text(f"✅ آیدی گروه ذخیره شد: `{group_mode[ADMIN_CHAT_ID]}`\n\nحالا پیامی که میخوای بفرستی رو بنویس:", parse_mode="Markdown")
        except ValueError:
            await update.message.reply_text("❌ آیدی باید عدد باشه مثل `-1001234567890`")
        return

    if isinstance(group_mode.get(ADMIN_CHAT_ID), int):
        group_id = group_mode.pop(ADMIN_CHAT_ID)
        try:
            await update.message.copy_to(chat_id=group_id)
            await update.message.reply_text("✅ پیام به گروه ارسال شد!")
        except Exception as e:
            await update.message.reply_text(f"❌ خطا در ارسال:\n{str(e)}")
        return

    # پیام همگانی (برودکست)
    if reply_to.get(ADMIN_CHAT_ID) == "broadcast":
        del reply_to[ADMIN_CHAT_ID]
        success = 0
        for u_id in users_db:
            if u_id not in blocked_users:
                try:
                    # استفاده از send_message برای پیام همگانی چون هدر دارد
                    if update.message.text:
                        await context.bot.send_message(chat_id=u_id, text=f"📢 *پیام از ادمین:*\n\n{text}", parse_mode="Markdown")
                    else:
                        # اگر رسانه بود ابتدا یک متن می‌فرستد سپس خود رسانه را کپی می‌کند
                        await context.bot.send_message(chat_id=u_id, text=f"📢 *پیام رسانه‌ای از طرف ادمین:*", parse_mode="Markdown")
                        await update.message.copy_to(chat_id=u_id)
                    success += 1
                except Exception: pass
        await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد."); return

    # 💎 بخش اصلی: پاسخ به کاربر خاص (پشتیبانی از استیکر، گیف، عکس، متن و...)
    if ADMIN_CHAT_ID in reply_to:
        target_id = reply_to.pop(ADMIN_CHAT_ID)
        try:
            # ارسال پیام هدر برای اطلاع کاربر
            name = "ادمین"
            await context.bot.send_message(chat_id=target_id, text=f"📨 *پاسخ {name}:*", parse_mode="Markdown")
            
            # کپی دقیق هر نوع پیامی که ادمین فرستاده (استیکر، گیف، وویس، متن و...) برای کاربر
            await update.message.copy_to(chat_id=target_id)
            
            # ارسال تاییدیه برای ادمین روی پیام اصلی (در صورت وجود در مپ)
            reply_msg_id = message_map.get(f"reply_{target_id}")
            if reply_msg_id:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="✅ پاسخ شما با موفقیت ارسال شد.", reply_to_message_id=reply_msg_id)
            else:
                await update.message.reply_text("✅ پاسخ شما با موفقیت ارسال شد.")
        except Exception as e:
            await update.message.reply_text(f"❌ ارسال پاسخ ناموفق بود.\nخطا: {e}")

# ── main ─────────────────────────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("panel",    panel))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("cancel",   cancel_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    
    # هندلر جدید: فیلتر ALL به ما اجازه می‌دهد هر فرمتی (متن یا رسانه) از سمت ادمین یا کاربر را بگیریم
    app.add_handler(MessageHandler(filters.ALL, handle_admin_media_and_text))
    
    print("✅ ربات روشن شد و منتظر پیامه...")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])

if __name__ == "__main__":
    main()
