import logging
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

# ذخیره اطلاعات کاربران و وضعیت بلاک
users_db = {}
blocked_users = set()
reply_to = {}  # برای پاسخ به کاربر خاص

# ==================== پنل ادمین ====================

def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("👥 لیست کاربران", callback_data="list_users")],
        [InlineKeyboardButton("🚫 لیست بلاک‌شده‌ها", callback_data="list_blocked")],
        [InlineKeyboardButton("📊 آمار", callback_data="stats")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی", callback_data="broadcast")],
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    if chat_id == ADMIN_CHAT_ID:
        await panel(update, context)
        return

    # ذخیره کاربر
    users_db[chat_id] = {
        "name": user.full_name,
        "username": user.username or "ندارد",
        "chat_id": chat_id
    }

    await update.message.reply_text(
        "👋 سلام!\nپیامت رو بفرست، در اولین فرصت جواب میگیری ✅"
    )

# ==================== دریافت پیام از کاربر ====================

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    # پیام ادمین به کاربر
    if chat_id == ADMIN_CHAT_ID:
        if chat_id in reply_to:
            target_id = reply_to[chat_id]
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"📨 پیام از ادمین:\n{update.message.text}"
                )
                await update.message.reply_text("✅ پیام ارسال شد!")
                del reply_to[chat_id]
            except Exception:
                await update.message.reply_text("❌ ارسال پیام ناموفق بود.")
        return

    # بلاک چک
    if chat_id in blocked_users:
        await update.message.reply_text("⛔ شما مسدود شده‌اید.")
        return

    # ذخیره کاربر
    users_db[chat_id] = {
        "name": user.full_name,
        "username": user.username or "ندارد",
        "chat_id": chat_id
    }

    # ارسال به ادمین
    keyboard = [
        [
            InlineKeyboardButton("↩️ پاسخ", callback_data=f"reply_{chat_id}"),
            InlineKeyboardButton("🚫 بلاک", callback_data=f"block_{chat_id}"),
        ]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    sender_info = (
        f"📩 *پیام جدید*\n"
        f"👤 نام: {user.full_name}\n"
        f"🆔 یوزرنیم: @{user.username if user.username else 'ندارد'}\n"
        f"🔢 Chat ID: `{chat_id}`\n"
        f"{'─' * 25}"
    )

    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=sender_info,
        parse_mode="Markdown",
        reply_markup=markup
    )
    await update.message.forward(chat_id=ADMIN_CHAT_ID)
    await update.message.reply_text("✅ پیامت دریافت شد، به زودی جواب میگیری.")

# ==================== دکمه‌های اینلاین ====================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if query.message.chat.id != ADMIN_CHAT_ID:
        return

    # پاسخ به کاربر
    if data.startswith("reply_"):
        target_id = int(data.split("_")[1])
        reply_to[ADMIN_CHAT_ID] = target_id
        user_info = users_db.get(target_id, {})
        await query.message.reply_text(
            f"✍️ پیامت رو بنویس، برای *{user_info.get('name', target_id)}* ارسال میشه.\n"
            f"(پیام بعدیت رو بفرست)",
            parse_mode="Markdown"
        )

    # بلاک کاربر
    elif data.startswith("block_"):
        target_id = int(data.split("_")[1])
        blocked_users.add(target_id)
        user_info = users_db.get(target_id, {})
        await query.message.reply_text(
            f"🚫 کاربر *{user_info.get('name', target_id)}* بلاک شد.",
            parse_mode="Markdown"
        )

    # آنبلاک کاربر
    elif data.startswith("unblock_"):
        target_id = int(data.split("_")[1])
        blocked_users.discard(target_id)
        user_info = users_db.get(target_id, {})
        await query.message.reply_text(
            f"✅ کاربر *{user_info.get('name', target_id)}* آنبلاک شد.",
            parse_mode="Markdown"
        )

    # لیست کاربران
    elif data == "list_users":
        if not users_db:
            await query.message.reply_text("👥 هنوز هیچ کاربری نداری.")
            return
        text = "👥 *لیست کاربران:*\n\n"
        keyboard = []
        for uid, info in users_db.items():
            blocked = "🚫" if uid in blocked_users else "✅"
            text += f"{blocked} {info['name']} | @{info['username']} | `{uid}`\n"
            keyboard.append([
                InlineKeyboardButton(f"↩️ پاسخ به {info['name']}", callback_data=f"reply_{uid}"),
                InlineKeyboardButton("🚫 بلاک" if uid not in blocked_users else "✅ آنبلاک",
                                     callback_data=f"{'block' if uid not in blocked_users else 'unblock'}_{uid}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # لیست بلاک‌شده‌ها
    elif data == "list_blocked":
        if not blocked_users:
            await query.message.reply_text("🚫 هیچ کاربری بلاک نشده.")
            return
        text = "🚫 *کاربران بلاک‌شده:*\n\n"
        keyboard = []
        for uid in blocked_users:
            info = users_db.get(uid, {"name": str(uid), "username": "ندارد"})
            text += f"🚫 {info['name']} | @{info['username']} | `{uid}`\n"
            keyboard.append([
                InlineKeyboardButton(f"✅ آنبلاک {info['name']}", callback_data=f"unblock_{uid}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 برگشت", callback_data="back")])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

    # آمار
    elif data == "stats":
        total = len(users_db)
        blocked = len(blocked_users)
        active = total - blocked
        text = (
            f"📊 *آمار ربات*\n\n"
            f"👥 کل کاربران: {total}\n"
            f"✅ کاربران فعال: {active}\n"
            f"🚫 بلاک‌شده‌ها: {blocked}\n"
        )
        await query.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 برگشت", callback_data="back")]]))

    # پیام همگانی
    elif data == "broadcast":
        reply_to[ADMIN_CHAT_ID] = "broadcast"
        await query.message.reply_text(
            "📢 پیام همگانیت رو بنویس، برای همه کاربران ارسال میشه:"
        )

    # برگشت به پنل
    elif data == "back":
        await query.message.reply_text(
            "🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:",
            parse_mode="Markdown",
            reply_markup=admin_panel_keyboard()
        )

# ==================== پیام همگانی ====================

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id != ADMIN_CHAT_ID:
        await forward_message(update, context)
        return

    if reply_to.get(ADMIN_CHAT_ID) == "broadcast":
        del reply_to[ADMIN_CHAT_ID]
        success = 0
        for uid in users_db:
            if uid not in blocked_users:
                try:
                    await context.bot.send_message(chat_id=uid, text=f"📢 پیام از ادمین:\n{update.message.text}")
                    success += 1
                except Exception:
                    pass
        await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد.")
    elif ADMIN_CHAT_ID in reply_to:
        target_id = reply_to[ADMIN_CHAT_ID]
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📨 پیام از ادمین:\n{update.message.text}"
            )
            await update.message.reply_text("✅ پیام ارسال شد!")
            del reply_to[ADMIN_CHAT_ID]
        except Exception:
            await update.message.reply_text("❌ ارسال پیام ناموفق بود.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, forward_message))
    print("✅ ربات روشن شد و منتظر پیامه...")
    app.run_polling()

if __name__ == "__main__":
    main()
