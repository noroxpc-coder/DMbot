import logging
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

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARNING)

users_db = {}; blocked_users = set(); reply_to = {}; message_map = {}
group_mode = {}; user_mode = {}; user_coins = {}; user_history = {}
pending_poll = {}; poll_votes = {}
bot_state = {"active": True}; user_profiles = {}
pending_coin_add = {}; pending_note_input = {}

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

def ensure_profile(uid):
    if uid not in user_profiles:
        user_profiles[uid] = {"join_date": fmt_dt(), "msg_count": 0, "admin_note": "", "block_history": [], "last_seen": fmt_dt()}
    return user_profiles[uid]

def update_last_seen(uid): ensure_profile(uid)["last_seen"] = fmt_dt()
def increment_msg(uid): p = ensure_profile(uid); p["msg_count"] = p.get("msg_count", 0) + 1

def get_full_profile_text(uid):
    info = users_db.get(uid, {"name": str(uid), "username": "ندارد"})
    p    = ensure_profile(uid)
    bh_text = "\n".join(f"  • {b}" for b in p.get("block_history",[])[-3:]) or "  — سابقه‌ای ندارد"
    return (
        f"👤 *پروفایل کامل کاربر*\n━━━━━━━━━━━━━━━━━━\n"
        f"🏷 نام: *{info.get('name','؟')}*\n🆔 یوزرنیم: @{info.get('username','ندارد')}\n🔢 Chat ID: `{uid}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 تاریخ عضویت: {p.get('join_date','؟')}\n🕐 آخرین فعالیت: {p.get('last_seen','؟')}\n📨 تعداد پیام‌ها: {p.get('msg_count',0)}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 موجودی سکه: {get_coins(uid)}\n"
        f"🔐 حالت ارسال: {'🕵️ ناشناس' if user_mode.get(uid)=='anonymous' else '👤 عادی'}\n"
        f"🚫 بلاک‌شده: {'🚫 بله' if uid in blocked_users else '✅ خیر'}\n"
        f"━━━━━━━━━━━━━━━━━━\n📋 سابقه بلاک:\n{bh_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n📝 یادداشت ارشیا: {p.get('admin_note') or '—'}"
    )

# ── کیبوردها ────────────────────────────────────────────────
def kb(*rows): return InlineKeyboardMarkup(list(rows))
def btn(label, data): return InlineKeyboardButton(label, callback_data=data)
def back_btn(cb="back"): return btn("🔙 برگشت", cb)

def main_menu_keyboard():
    return kb(
        [btn("📨 ارسال پیام به ارشیا", "goto_send")],
        [btn("👤 حساب من", "my_account")],
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
            "━━━━━━━━━━━━━━━━\n👤 *با اسم* — ارشیا اسم و پروفایلت رو میبینه\n"
            "🕵️ *ناشناس* — هیچ اطلاعاتی از تو نمیفرسته\n"
            "━━━━━━━━━━━━━━━━\n\n💡 هر وقت خواستی از /settings میتونی تغییرش بدی.",
            parse_mode="Markdown", reply_markup=mode_selection_keyboard())
    else:
        await update.message.reply_text(
            f"👋 *سلام {user.first_name}!*\n\nاز منوی زیر ادامه بده 👇",
            parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_CHAT_ID: return
    await update.message.reply_text("🎛 *پنل مدیریت ارشیا*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_panel_keyboard())

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if update.effective_chat.type != "private" or uid == ADMIN_CHAT_ID: return
    current = user_mode.get(uid)
    status_text = "🕵️ *ناشناس* (فعال)" if current == "anonymous" else ("👤 *عادی* (فعال)" if current == "normal" else "❓ هنوز انتخاب نشده")
    await update.message.reply_text(
        f"⚙️ *تنظیمات ارسال پیام*\n\nحالت فعلی: {status_text}\n\n"
        "━━━━━━━━━━━━━━━━\n👤 *عادی* — اسم و پروفایلت برای ارشیا نمایش داده میشه\n"
        "🕵️ *ناشناس* — هیچ اطلاعاتی از تو ارسال نمیشه\n━━━━━━━━━━━━━━━━\n\nیه حالت انتخاب کن:",
        parse_mode="Markdown", reply_markup=mode_selection_keyboard())

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if uid != ADMIN_CHAT_ID: return
    
    reply_to.pop(ADMIN_CHAT_ID, None)
    group_mode.pop(ADMIN_CHAT_ID, None)
    pending_poll.pop(ADMIN_CHAT_ID, None)
    pending_coin_add.pop(ADMIN_CHAT_ID, None)
    pending_note_input.pop(ADMIN_CHAT_ID, None)
    
    await update.message.reply_text("🔄 *عملیات فعلی لغو شد و وضعیت به حالت عادی برگشت.*", parse_mode="Markdown")

# ── فوروارد و ارسال پیام ────────────────────────────────────────────────────

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, uid = update.effective_user, update.effective_chat.id
    if update.effective_chat.type != "private" or uid == ADMIN_CHAT_ID: return
    if uid in blocked_users:
        await update.message.reply_text("⛔ شما مسدود شده‌اید."); return
    if not bot_state["active"]:
        await update.message.reply_text("⛔ *ربات در حال حاضر غیرفعال است.*\n\nلطفاً بعداً مراجعه کنید.", parse_mode="Markdown"); return
    update_last_seen(uid)

    if uid not in user_mode:
        await update.message.reply_text("⚠️ قبل از ارسال پیام، لطفاً حالت ارسالت رو انتخاب کن:", parse_mode="Markdown", reply_markup=mode_selection_keyboard()); return

    users_db[uid] = {"name": user.full_name, "username": user.username or "ندارد", "chat_id": uid}
    increment_msg(uid)

    if update.message.text:
        context.user_data["pending_text"] = update.message.text
        context.user_data["pending_msg_id"] = update.message.message_id
        await update.message.reply_text(
            "📨 پیامت آماده ارسال شد!\n\nبا چه اولویتی ارسال شه?\n\n🟢 *عادی* — رایگان\n🟡 *ویژه* — ۱۰ سکه\n🔴 *فوری* — ۳۰ سکه",
            parse_mode="Markdown", reply_markup=priority_keyboard(uid)); return

    # ارسال مستقیم فایل/مالتی مدیا بدون اولویت متنی
    await send_user_message(context, uid, user, priority="normal", text=None, original_message=update.message, confirm_target=update.message)


async def send_user_message(context, uid, user, priority="normal", text=None, original_message=None, confirm_target=None):
    level       = PRIORITY_LEVELS[priority]
    priority_tag = "\n🟡 *پیام ویژه*" if priority == "vip" else ("\n🔴 *پیام فوری* ⚡️" if priority == "urgent" else "")
    is_anonymous = user_mode[uid] == "anonymous"
    
    keyboard     = [[btn("↩️ پاسخ", f"reply_{uid}"), btn("🚫 بلاک", f"block_{uid}")]]
    sender_info  = (
        f"📩 *پیام جدید*{priority_tag}\n🕵️ *ناشناس*\n🔢 Chat ID: `{uid}`\n{'─'*25}"
        if is_anonymous else
        f"📩 *پیام جدید*{priority_tag}\n👤 نام: {user.full_name}\n🆔 یوزرنیم: @{user.username or 'ندارد'}\n🔢 Chat ID: `{uid}`\n{'─'*25}"
    )
    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=sender_info, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    
    user_orig_msg_id = context.user_data.get("pending_msg_id") if original_message is None else original_message.message_id

    if text is not None:
        fwd = await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=text)
    elif is_anonymous:
        fwd = await context.bot.copy_message(chat_id=ADMIN_CHAT_ID, from_chat_id=uid, message_id=original_message.message_id)
    else:
        fwd = await original_message.forward(chat_id=ADMIN_CHAT_ID)
    
    # ساخت ساختار تاپل برای ذخیره شناسه پیام ادمین و شناسه واقعی پیام کاربر
    message_map[f"reply_{uid}"] = (fwd.message_id, user_orig_msg_id)
    
    if level["cost"] > 0: 
        new_coins = add_coins(uid, -level["cost"], f"ارسال پیام با اولویت {level['title']}")
    else:
        new_coins = add_coins(uid, 1, "پاداش ارسال پیام به ارشیا")
        
    confirm_text = f"✅ پیامت دریافت شد، به زودی از ارشیا جواب میگیری.\n🎁 *۱ سکه پاداش گرفتی!*\n💰 موجودی فعلی: {new_coins} سکه"
    if priority == "vip":    confirm_text = f"✅ پیام *ویژه*‌ت ارسال شد! 🟡 سریع‌تر بررسی میشه.\n💰 موجودی فعلی: {new_coins} سکه"
    elif priority == "urgent": confirm_text = f"✅ پیام *فوری*‌ت ارسال شد! 🔴 در صدر لیست قرار گرفت.\n💰 موجودی فعلی: {new_coins} سکه"
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

    if data in ("set_mode_normal", "set_mode_anonymous"):
        if quid == ADMIN_CHAT_ID: return
        user_mode[quid] = "normal" if data == "set_mode_normal" else "anonymous"
        label = ("✅ *حالت عادی فعال شد!*\n\n👤 اسم و پروفایلت همراه پیامت ارسال میشه.\n\nاز منوی زیر ادامه بده 👇"
                 if data == "set_mode_normal" else
                 "✅ *حالت ناشناس فعال شد!*\n\n🕵️ هیچ اطلاعاتی از تو ارسال نمیشه.\n\nاز منوی زیر ادامه بده 👇")
        await query.edit_message_text(label, parse_mode="Markdown", reply_markup=main_menu_keyboard()); return

    if data == "back_main":
        await query.edit_message_text(
            f"🏠 *منوی اصلی*\n\nیه گزینه انتخاب کن 👇",
            parse_mode="Markdown", reply_markup=main_menu_keyboard()); return

    if data == "goto_send":
        if quid == ADMIN_CHAT_ID: return
        if not bot_state["active"]:
            await query.edit_message_text("⚠️ ربات در حال حاضر غیرفعال است."); return
        await query.edit_message_text("📨 *ارسال پیام به ارشیا*\n\nپیامت رو بنویس و ارسال کن 👇\n\n(متن، عکس، فایل — همه پذیرفته میشه و با هر پیام ۱ سکه جایزه می‌گیری!)", parse_mode="Markdown"); return

    if data == "open_settings":
        if quid == ADMIN_CHAT_ID: return
        current = user_mode.get(quid)
        status_text = "🕵️ *ناشناس*" if current == "anonymous" else ("👤 *عادی*" if current == "normal" else "❓ هنوز انتخاب نشده")
        await query.edit_message_text(f"⚙️ *تنظیمات*\n\nحالت فعلی: {status_text}\n\nیه حالت انتخاب کن:", parse_mode="Markdown", reply_markup=mode_selection_keyboard()); return

    if data == "my_account":
        if quid == ADMIN_CHAT_ID: return
        p = ensure_profile(quid)
        history_text = "\n".join(user_history.get(quid, [])[-5:]) or "تاریخچه‌ای وجود ندارد"
        await query.edit_message_text(
            f"👤 *حساب من*\n\n💰 موجودی سکه: {get_coins(quid)}\n🔐 حالت ارسال: {'🕵️ ناشناس' if user_mode.get(quid)=='anonymous' else '👤 عادی'}\n"
            f"📨 تعداد پیام‌های ارسالی: {p.get('msg_count',0)}\n📅 عضویت: {p.get('join_date','؟')}\n\n"
            f"📋 *آخرین تراکنش‌های سکه:*\n{history_text}",
            parse_mode="Markdown", reply_markup=kb([back_btn("back_main")])); return

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

    # ── دکمه‌های ارشیا (ادمین) ──────────────────────────────────────────────────────
    if uid != ADMIN_CHAT_ID: return

    if data.startswith("reply_"):
        target_id = int(data.split("_")[1])
        reply_to[ADMIN_CHAT_ID] = target_id
        name = users_db.get(target_id, {}).get("name", "ناشناس") if user_mode.get(target_id) != "anonymous" else "🕵️ ناشناس"
        await query.message.reply_text(f"✍️ *در حال پاسخ به {name}*\n\nهر پیامی بفرستی براش کپی میشه.\n\n💡 برای انصراف کلمه `انصراف` یا /cancel رو بفرست.", parse_mode="Markdown"); return

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
            text += f"{'🚫' if u_id in blocked_users else '✅'}{'🕵️' if user_mode.get(u_id)=='anonymous' else '👤'} {info['name']} | @{info['username']} | `{u_id}` | 💰{get_coins(u_id)} | 📨{p.get('msg_count',0)}\n"
            keyboard.append([
                btn(f"👁 {info['name']}", f"full_profile_{u_id}"),
                btn("↩️ پاسخ", f"reply_{u_id}"),
                btn("🚫" if u_id not in blocked_users else "✅ آنبلاک", f"{'block' if u_id not in blocked_users else 'unblock'}_{u_id}"),
            ])
        keyboard.append([back_btn()])
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data == "stats":
        total    = len(users_db)
        blocked  = len(blocked_users)
        anon     = sum(1 for u_id in users_db if user_mode.get(u_id) == "anonymous")
        normal   = sum(1 for u_id in users_db if user_mode.get(u_id) == "normal")
        await query.message.reply_text(
            f"📊 *آمار ربات*\n\n👥 کل کاربران: {total}\n✅ فعال: {total-blocked}\n🚫 بلاک‌شده: {blocked}\n"
            f"━━━━━━━━━━━━\n🕵️ ناشناس: {anon}\n👤 عادی: {normal}\n━━━━━━━━━━━━\n"
            f"⚡ وضعیت ربات: {'🟢 روشن' if bot_state['active'] else '🔴 خاموش'}",
            parse_mode="Markdown", reply_markup=kb([back_btn()])); return

    if data == "broadcast":
        reply_to[ADMIN_CHAT_ID] = "broadcast"
        await query.message.reply_text("📢 پیام همگانیت رو بنویس (یا بفرست انصراف):"); return

    if data == "back":
        await query.message.reply_text("🎛 *پنل مدیریت ارشیا*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_panel_keyboard()); return

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

    if data.startswith("full_profile_"):
        target_id = int(data[len("full_profile_"):])
        await query.message.reply_text(
            get_full_profile_text(target_id), parse_mode="Markdown",
            reply_markup=kb(
                [btn("↩️ پاسخ", f"reply_{target_id}")],
                [btn("📝 یادداشت", f"set_note_{target_id}")],
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

    if data == "toggle_bot":
        bot_state["active"] = not bot_state["active"]
        status = "🟢 روشن شد" if bot_state["active"] else "🔴 خاموش شد"
        msg    = "کاربران میتونن پیام بفرستن." if bot_state["active"] else "⛔ کاربران به هیچ چیزی دسترسی ندارن."
        await query.message.reply_text(f"⚡ *وضعیت ربات:* {status}\n\n{msg}", parse_mode="Markdown", reply_markup=admin_panel_keyboard()); return

# ── هندلر جامع پیام‌های ارشیا (پشتیبانی از مولتی‌مدیا) ──────────────────────────

async def handle_admin_media_and_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if update.effective_chat.type != "private": return
    
    if uid != ADMIN_CHAT_ID:
        await forward_message(update, context); return

    text = update.message.text or ""
    
    if text.strip() in ("انصراف", "/cancel"):
        await cancel_command(update, context)
        return

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

    if ADMIN_CHAT_ID in pending_coin_add:
        target_id = pending_coin_add.pop(ADMIN_CHAT_ID)
        try:
            amount = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد بفرست (مثلاً 20 یا -10)."); return
        new_balance = add_coins(target_id, amount, "تغییر دستی توسط ارشیا")
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

    if reply_to.get(ADMIN_CHAT_ID) == "broadcast":
        del reply_to[ADMIN_CHAT_ID]
        success = 0
        for u_id in users_db:
            if u_id not in blocked_users:
                try:
                    if update.message.text:
                        await context.bot.send_message(chat_id=u_id, text=f"📢 *پیام همگانی از طرف ارشیا:*\n\n{text}", parse_mode="Markdown")
                    else:
                        await context.bot.send_message(chat_id=u_id, text=f"📢 *پیام رسانه‌ای همگانی از طرف ارشیا:*", parse_mode="Markdown")
                        await context.bot.copy_message(chat_id=u_id, from_chat_id=ADMIN_CHAT_ID, message_id=update.message.message_id)
                    success += 1
                except Exception: pass
        await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد."); return

    if ADMIN_CHAT_ID in reply_to:
        target_id = reply_to.pop(ADMIN_CHAT_ID)
        try:
            mapped_data = message_map.get(f"reply_{target_id}")
            reply_to_user_msg_id = None
            admin_msg_id_in_panel = None
            
            if isinstance(mapped_data, tuple):
                admin_msg_id_in_panel, reply_to_user_msg_id = mapped_data
            elif isinstance(mapped_data, int):
                admin_msg_id_in_panel = mapped_data

            # کپی تمیز پیام ارشیا به چت کاربر به همراه قابلیت ریپلای روی آیدی پیام ثبت شده کاربر
            await context.bot.copy_message(
                chat_id=target_id, 
                from_chat_id=ADMIN_CHAT_ID, 
                message_id=update.message.message_id,
                reply_to_message_id=reply_to_user_msg_id
            )
            
            # ارسال تاییدیه روی چت خودتان (ریپلای روی پیامی که توی پنل اومده بود)
            if admin_msg_id_in_panel:
                await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text="✅ پاسخ شما ارسال شد.", reply_to_message_id=admin_msg_id_in_panel)
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
    
    app.add_handler(MessageHandler(filters.ALL, handle_admin_media_and_text))
    
    print("✅ ربات ارشیا روشن شد...")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])

if __name__ == "__main__":
    main()
