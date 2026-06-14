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

users_db = {}
blocked_users = set()
reply_to = {}
message_map = {}   # نگه‌داری message_id پیام اصلی برای ریپلای
group_mode = {}    # حالت ارسال به گروه

# ─────────────────────────────────────────────
# 🆕 جدید: حالت ارسال هر کاربر (anonymous / normal)
# ─────────────────────────────────────────────
user_mode = {}   # {chat_id: "anonymous" | "normal"}


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
#  پنل ادمین (بدون تغییر)
# ══════════════════════════════════════════════
def admin_panel_keyboard():
    keyboard = [
        [InlineKeyboardButton("👥 لیست کاربران",       callback_data="list_users")],
        [InlineKeyboardButton("🚫 لیست بلاک‌شده‌ها",  callback_data="list_blocked")],
        [InlineKeyboardButton("📊 آمار",                callback_data="stats")],
        [InlineKeyboardButton("📢 ارسال پیام همگانی",  callback_data="broadcast")],
        [InlineKeyboardButton("👥 ارسال پیام به گروه", callback_data="send_group")],
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

    # ─── حالت ناشناس ───────────────────────────
    if user_mode[chat_id] == "anonymous":
        keyboard = [[
            InlineKeyboardButton("↩️ پاسخ",  callback_data=f"reply_{chat_id}"),
            InlineKeyboardButton("🚫 بلاک",  callback_data=f"block_{chat_id}"),
        ]]
        sender_info = (
            f"📩 *پیام جدید*\n"
            f"🕵️ *ناشناس*\n"
            f"🔢 Chat ID: `{chat_id}`\n"
            f"{'─' * 25}"
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=sender_info,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        # کپی پیام به جای فوروارد (ناشناس میمونه)
        fwd = await update.message.copy_to(chat_id=ADMIN_CHAT_ID)
        message_map[f"reply_{chat_id}"] = fwd.message_id
        await update.message.reply_text("✅ پیام ناشناس ارسال شد، به زودی جواب میگیری 🕵️")

    # ─── حالت عادی ─────────────────────────────
    else:
        keyboard = [[
            InlineKeyboardButton("↩️ پاسخ",  callback_data=f"reply_{chat_id}"),
            InlineKeyboardButton("🚫 بلاک",  callback_data=f"block_{chat_id}"),
        ]]
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
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        fwd = await update.message.forward(chat_id=ADMIN_CHAT_ID)
        message_map[f"reply_{chat_id}"] = fwd.message_id
        await update.message.reply_text("✅ پیامت دریافت شد، به زودی جواب میگیری.")


# ══════════════════════════════════════════════
#  هندلر دکمه‌ها
# ══════════════════════════════════════════════
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data
    chat_id = query.message.chat.id

    # ─── 🆕 انتخاب حالت توسط کاربر ──────────────
    if data in ("set_mode_normal", "set_mode_anonymous"):
        user_chat_id = query.from_user.id
        if user_chat_id == ADMIN_CHAT_ID:
            return

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

    # ─── بقیه دکمه‌ها فقط برای ادمین ─────────────
    if chat_id != ADMIN_CHAT_ID:
        return

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
            text    += f"{blocked}{mode_tag} {info['name']} | @{info['username']} | `{uid}`\n"
            keyboard.append([
                InlineKeyboardButton(f"↩️ پاسخ به {info['name']}", callback_data=f"reply_{uid}"),
                InlineKeyboardButton("🚫 بلاک" if uid not in blocked_users else "✅ آنبلاک",
                                     callback_data=f"{'block' if uid not in blocked_users else 'unblock'}_{uid}")
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
        try:
            reply_msg_id = message_map.get(f"reply_{target_id}")
            await context.bot.send_message(
                chat_id=target_id,
                text=f"📨 پیام از ادمین:\n{text}"
            )
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
