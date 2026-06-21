import logging
import time
from datetime import datetime, timedelta, timezone

try:
    import pytz
    TEHRAN_TZ = pytz.timezone("Asia/Tehran")
except ImportError:
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

def now_tehran(): return datetime.now(TEHRAN_TZ)
def fmt_dt(dt=None): return (dt or now_tehran()).strftime("%Y-%m-%d | %H:%M") + " (تهران)"

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    PollAnswerHandler,
    filters,
    ContextTypes
)

# ================= BOT CONFIG =================
BOT_TOKEN      = "YOUR_TOKEN"
OWNER_CHAT_ID  = 1143598012

# ================= COOLDOWN SYSTEM =================
COOLDOWN_SECONDS = 3600  # پیشفرض 1 ساعت
user_last_message_time = {}

def check_cooldown(uid):
    now = time.time()
    last = user_last_message_time.get(uid)

    if not last:
        return False, 0

    remaining = COOLDOWN_SECONDS - (now - last)

    if remaining > 0:
        return True, int(remaining)

    return False, 0


# ================= LOGGING =================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.WARNING
)

# ================= DATABASES =================
users_db = {}
blocked_users = set()
reply_to = {}
message_map = {}
group_mode = {}
user_mode = {}
user_coins = {}
user_history = {}
pending_poll = {}
poll_votes = {}
bot_state = {"active": True}
user_profiles = {}

pending_coin_add = {}
pending_note_input = {}
pending_admin_add = {}

unblock_requests = {}
used_unblock_ticket = set()
pending_unblock_text = {}

admins_db = {}

# ================= HELPERS =================

def is_admin(uid):
    return uid == OWNER_CHAT_ID or uid in admins_db

def ensure_profile(uid):
    if uid not in user_profiles:
        user_profiles[uid] = {"msg_count": 0, "last_seen": fmt_dt()}
    return user_profiles[uid]

def update_last_seen(uid):
    ensure_profile(uid)["last_seen"] = fmt_dt()

def increment_msg(uid):
    p = ensure_profile(uid)
    p["msg_count"] += 1


# ================= MAIN MESSAGE HANDLER =================

async def handle_admin_media_and_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id

    # ================= COOLDOWN CHECK =================
    if not is_admin(uid):
        blocked, remaining = check_cooldown(uid)

        if blocked:
            await update.message.reply_text(
                f"⏳ لطفاً صبر کن\n"
                f"⏱ باقی‌مانده: {remaining} ثانیه"
            )
            return

        user_last_message_time[uid] = time.time()

    text = update.message.text or ""

    if uid in blocked_users:
        return

    if not bot_state["active"]:
        return

    update_last_seen(uid)
    increment_msg(uid)

    # اینجا همون منطق قبلیت ادامه پیدا می‌کنه
    await forward_message(update, context)


# ================= COOLDOWN COMMAND =================

async def set_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global COOLDOWN_SECONDS

    uid = update.effective_chat.id

    if uid != OWNER_CHAT_ID:
        await update.message.reply_text("⛔ دسترسی نداری")
        return

    if not context.args:
        await update.message.reply_text("مثال: /cooldown 3600")
        return

    try:
        COOLDOWN_SECONDS = int(context.args[0])
        await update.message.reply_text(f"✔️ کول‌داون تنظیم شد: {COOLDOWN_SECONDS}")
    except:
        await update.message.reply_text("❌ عدد اشتباهه")


# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("cooldown", set_cooldown))
    app.add_handler(MessageHandler(filters.ALL, handle_admin_media_and_text))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(PollAnswerHandler(handle_poll_answer))

    print("bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
