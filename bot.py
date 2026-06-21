import logging
import time
from datetime import datetime, timedelta, timezone

try:
    import pytz
    TEHRAN_TZ = pytz.timezone("Asia/Tehran")
except ImportError:
    TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))

def now_tehran():
    return datetime.now(TEHRAN_TZ)

def fmt_dt(dt=None):
    return (dt or now_tehran()).strftime("%Y-%m-%d | %H:%M") + " (تهران)"


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

# ================= CONFIG =================
BOT_TOKEN = "PUT_YOUR_TOKEN"
OWNER_CHAT_ID = 1143598012

# ================= COOLDOWN =================
COOLDOWN_SECONDS = 3600
user_last_message_time = {}

def check_cooldown(uid):
    last = user_last_message_time.get(uid)
    if not last:
        return False, 0

    remaining = COOLDOWN_SECONDS - (time.time() - last)

    if remaining > 0:
        return True, int(remaining)

    return False, 0


# ================= DATABASES =================
users_db = {}
blocked_users = set()
bot_state = {"active": True}
user_mode = {}

admins_db = {}

# ================= HELPERS =================

def is_admin(uid):
    return uid == OWNER_CHAT_ID or uid in admins_db


# ================= MAIN HANDLER =================

async def handle_admin_media_and_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id

    # ❌ COOLDOWN (SAFE PATCH)
    if not is_admin(uid):
        blocked, remaining = check_cooldown(uid)

        if blocked:
            await update.message.reply_text(
                f"⏳ صبر کن\n⏱ {remaining} ثانیه دیگه"
            )
            return

        user_last_message_time[uid] = time.time()

    if update.effective_chat.type != "private":
        return

    if uid in blocked_users:
        return

    if not bot_state["active"]:
        return

    text = update.message.text or ""

    await update.message.reply_text("✅ پیام دریافت شد (نسخه تستی)")


# ================= COOLDOWN COMMAND =================

async def set_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global COOLDOWN_SECONDS

    if update.effective_chat.id != OWNER_CHAT_ID:
        return

    try:
        COOLDOWN_SECONDS = int(context.args[0])
        await update.message.reply_text(f"✔️ cooldown = {COOLDOWN_SECONDS}")
    except:
        await update.message.reply_text("مثال: /cooldown 3600")


# ================= START =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("cooldown", set_cooldown))
    app.add_handler(MessageHandler(filters.ALL, handle_admin_media_and_text))

    print("BOT RUNNING...")
    app.run_polling()


if __name__ == "__main__":
    main()
