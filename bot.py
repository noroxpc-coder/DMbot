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

BOT_TOKEN      = "8977895133:AAHdVjMrr-9-ceXXviV5Zt5I_vP93HxQqZY"
OWNER_CHAT_ID  = 1143598012  # ارشیا (مالک اصلی و ادمین ارشد)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.WARNING)

users_db = {}; blocked_users = set(); reply_to = {}; message_map = {}
group_mode = {}; user_mode = {}; user_coins = {}; user_history = {}
pending_poll = {}; poll_votes = {}
bot_state = {"active": True}; user_profiles = {}
pending_coin_add = {}; pending_note_input = {}; pending_admin_add = {}

# بخش‌های جدید برای مدیریت درخواست‌های آنبلاک
unblock_requests = {}      # ساختار: { user_id: "متن درخواست" }
used_unblock_ticket = set() # کاربرانی که قبلاً یک‌بار درخواست داده‌اند
pending_unblock_text = {}   # وضعیت انتظار برای تایپ متن درخواست

admins_db = {}
ALL_PERMISSIONS = {
    "can_reply": "✉️ پاسخ به پیام‌ها",
    "can_manage_coins": "💰 مدیریت سکه",
    "can_broadcast": "📢 پیام همگانی",
    "can_manage_users": "👥 مدیریت کاربران"
}

PRIORITY_LEVELS = {
    "normal": {"label": "🟢 عادی",  "emoji": "🟢", "cost": 0,   "title": "عادی"},
    "urgent": {"label": "🔴 فوری",  "emoji": "🔴", "cost": 100, "title": "فوری"},
}

# ── توابع کمکی دسترسی ────────────────────────────────────────────────────────

def is_admin(uid):
    return uid == OWNER_CHAT_ID or uid in admins_db

def has_perm(uid, permission):
    if uid == OWNER_CHAT_ID: return True
    if uid in admins_db:
        return permission in admins_db[uid]["permissions"]
    return False

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
        f"━━━━━━━━━━━━━━━━━━\n📝 یادداشت ادمین: {p.get('admin_note') or '—'}"
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
        [btn("🔴 فوری (۱۰۰ سکه)", "priority_urgent")],
        [btn(f"💰 موجودی شما: {get_coins(uid)} سکه", "noop")],
    )

def admin_panel_keyboard(uid):
    buttons = []
    if has_perm(uid, "can_manage_users"):
        # اضافه شدن دکمه مدیریت درخواست‌های آنبلاک با نمایش تعداد کل درخواست‌ها
        req_count = len(unblock_requests)
        req_label = f"📩 درخواست‌های رفع بلاک ({req_count})" if req_count > 0 else "📩 درخواست‌های رفع بلاک"
        buttons.append([btn("👥 لیست کاربران", "list_users"), btn(req_label, "manage_unblock_reqs")])
    
    mid_row = []
    if has_perm(uid, "can_manage_users"): mid_row.append(btn("📊 آمار", "stats"))
    if has_perm(uid, "can_broadcast"): mid_row.append(btn("📢 پیام همگانی", "broadcast"))
    if mid_row: buttons.append(mid_row)
    
    if has_perm(uid, "can_manage_coins"):
        buttons.append([btn("💰 مدیریت سکه", "manage_coins")])
        
    if uid == OWNER_CHAT_ID:
        status = "🟢 روشن" if bot_state["active"] else "🔴 خاموش"
        buttons.append([btn("👑 مدیریت ادمین‌ها و دسترسی‌ها", "manage_admins")])
        buttons.append([btn(f"⚡ وضعیت ربات: {status}", "toggle_bot")])
        
    return InlineKeyboardMarkup(buttons)

def admin_permissions_keyboard(admin_id):
    admin_info = admins_db.get(admin_id, {"permissions": set()})
    current_perms = admin_info["permissions"]
    rows = []
    for perm_key, perm_label in ALL_PERMISSIONS.items():
        status_emoji = "✅" if perm_key in current_perms else "❌"
        rows.append([btn(f"{status_emoji} {perm_label}", f"toggleperm_{admin_id}_{perm_key}")])
    rows.append([btn("🗑 حذف کامل این ادمین", f"removeadmin_{admin_id}")])
    rows.append([back_btn("manage_admins")])
    return InlineKeyboardMarkup(rows)

# ── هندلرها ───────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, uid = update.effective_user, update.effective_chat.id
    if update.effective_chat.type != "private": return
    if is_admin(uid):
        await panel(update, context); return
        
    # هوش برخورد با کاربر بلاک شده
    if uid in blocked_users:
        if uid in used_unblock_ticket:
            await update.message.reply_text("⛔ *شما مسدود شده‌اید.*\n\n⚠️ شما قبلاً یک‌بار درخواست رفع بلاک ارسال کرده‌اید و دیگر امکان ارسال درخواست مجدد را ندارید.", parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "⛔ *شما از دسترسی به ربات مسدود شده‌اید.*\n\n"
                "💡 اما سیستم به شما اجازه می‌دهد **فقط یک‌بار** درخواست توجیهی یا عذرخواهی خود را برای ارشیا بفرستید تا بررسی شود.",
                parse_mode="Markdown",
                reply_markup=kb([btn("✍️ ثبت درخواست رفع بلاک", "write_unblock_request")])
            )
        return

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
        await update.message.reply_text(
            f"👋 *سلام {user.first_name}!*\n\nاز منوی زیر ادامه بده 👇",
            parse_mode="Markdown", reply_markup=main_menu_keyboard())

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if not is_admin(uid): return
    await update.message.reply_text("🎛 *پنل مدیریت ربات*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_panel_keyboard(uid))

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if update.effective_chat.type != "private" or is_admin(uid): return
    current = user_mode.get(uid)
    status_text = "🕵️ *ناشناس* (فعال)" if current == "anonymous" else ("👤 *عادی* (فعال)" if current == "normal" else "❓ هنوز انتخاب نشده")
    await update.message.reply_text(
        f"⚙️ *تنظیمات ارسال پیام*\n\nحالت فعلی: {status_text}\n\n"
        "━━━━━━━━━━━━━━━━\n👤 *عادی* — اسم و پروفایلت برای ادمین نمایش داده میشه\n"
        "🕵️ *ناشناس* — هیچ اطلاعاتی از تو ارسال نمیشه\n━━━━━━━━━━━━━━━━\n\nیه حالت انتخاب کن:",
        parse_mode="Markdown", reply_markup=mode_selection_keyboard())

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if not is_admin(uid): return
    
    reply_to.pop(uid, None)
    group_mode.pop(uid, None)
    pending_poll.pop(uid, None)
    pending_coin_add.pop(uid, None)
    pending_note_input.pop(uid, None)
    pending_admin_add.pop(uid, None)
    
    await update.message.reply_text("🔄 *عملیات فعلی لغو شد و وضعیت به حالت عادی برگشت.*", parse_mode="Markdown")

# ── فوروارد و ارسال پیام ────────────────────────────────────────────────────

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, uid = update.effective_user, update.effective_chat.id
    if update.effective_chat.type != "private" or is_admin(uid): return
    if uid in blocked_users:
        return # هندل کامل در استارت انجام می‌شود و پیام معمولی رد نمی‌شود.

    if not bot_state["active"]:
        await update.message.reply_text("⛔ *ربات در حال حاضر غیرفعال است.*", parse_mode="Markdown"); return
    update_last_seen(uid)

    if uid not in user_mode:
        await update.message.reply_text("⚠️ قبل از ارسال پیام، لطفاً حالت ارسالت رو انتخاب کن:", parse_mode="Markdown", reply_markup=mode_selection_keyboard()); return

    users_db[uid] = {"name": user.full_name, "username": user.username or "ندارد", "chat_id": uid}
    increment_msg(uid)

    if update.message.text:
        context.user_data["pending_text"] = update.message.text
        context.user_data["pending_msg_id"] = update.message.message_id
        await update.message.reply_text(
            "📨 *اولویت ارسال پیام خود را انتخاب کنید:*\n\n"
            "🟢 *عادی (رایگان):* پیام شما در صف معمولی قرار می‌گیرد و به مرور زمان بررسی می‌شود.\n\n"
            "🔴 *فوری (۱۰۰ سکه):* پیام شما با وضعیت ویژه و صدای زنگ متمایز 🔔 به دست ادمین می‌رسد و مستقیماً بالای چتِ ادمین 📌 *سنجاق (Pin)* می‌شود تا در سریع‌ترین زمان ممکن پاسخ داده شود!",
            parse_mode="Markdown", reply_markup=priority_keyboard(uid)); return

    await send_user_message(context, uid, user, priority="normal", text=None, original_message=update.message, confirm_target=update.message)


async def send_user_message(context, uid, user, priority="normal", text=None, original_message=None, confirm_target=None):
    level       = PRIORITY_LEVELS[priority]
    
    if priority == "urgent":
        priority_tag = "\n🚨🚨 *[پیام بسیار فوری — ۱۰۰ سکه]* 🚨🚨\n📌 این پیام در بالای چت ادمین سنجاق شده است!"
    else:
        priority_tag = "\n🟢 *پیام عادی*"

    is_anonymous = user_mode[uid] == "anonymous"
    keyboard     = [[btn("↩️ پاسخ", f"reply_{uid}"), btn("🚫 بلاک", f"block_{uid}")]]
    
    sender_info  = (
        f"📩 *پیام جدید*{priority_tag}\n🕵️ *ناشناس*\n🔢 Chat ID: `{uid}`\n{'─'*25}"
        if is_anonymous else
        f"📩 *پیام جدید*{priority_tag}\n👤 نام: {user.full_name}\n🆔 یوزرنیم: @{user.username or 'ندارد'}\n🔢 Chat ID: `{uid}`\n{'─'*25}"
    )
    
    targets = [OWNER_CHAT_ID] + [adm_id for adm_id, adm_info in admins_db.items() if "can_reply" in adm_info["permissions"]]

    for target_admin in targets:
        try:
            if priority == "urgent":
                await context.bot.send_message(
                    chat_id=target_admin, 
                    text="🔔🔴 *🚨 توجه! پیام بسیار فوری با کسر ۱۰۰ سکه دریافت شد! 🚨* 🔴🔔", 
                    parse_mode="Markdown", 
                    disable_notification=False
                )

            fwd_info = await context.bot.send_message(chat_id=target_admin, text=sender_info, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            user_orig_msg_id = context.user_data.get("pending_msg_id") if original_message is None else original_message.message_id

            if text is not None:
                fwd = await context.bot.send_message(chat_id=target_admin, text=text, disable_notification=(priority=="normal"))
            elif is_anonymous:
                fwd = await context.bot.copy_message(chat_id=target_admin, from_chat_id=uid, message_id=original_message.message_id, disable_notification=(priority=="normal"))
            else:
                fwd = await original_message.forward(chat_id=target_admin, disable_notification=(priority=="normal"))
            
            if priority == "urgent":
                try:
                    await context.bot.pin_chat_message(chat_id=target_admin, message_id=fwd.message_id, disable_notification=False)
                except Exception: pass

            message_map[f"reply_{uid}_{target_admin}"] = (fwd.message_id, user_orig_msg_id)
        except Exception: pass
    
    if level["cost"] > 0: 
        new_coins = add_coins(uid, -level["cost"], f"ارسال پیام با اولویت {level['title']}")
    else:
        new_coins = add_coins(uid, 1, "پاداش ارسال پیام")
        
    confirm_text = f"✅ پیامت دریافت شد، به زودی بررسی میشه.\n🎁 *۱ سکه پاداش گرفتی!*\n💰 موجودی فعلی: {new_coins} سکه"
    if priority == "urgent": 
        confirm_text = f"🔴 *پیام فوری شما با موفقیت ارسال شد!*\n📌 پیام شما با کسر ۱۰۰ سکه، در بالای چت ادمین سنجاق شد تا سریعاً بررسی شود.\n💰 موجودی فعلی: {new_coins} سکه"
    if is_anonymous: confirm_text += " 🕵️"
    
    if confirm_target:
        await confirm_target.reply_text(confirm_text, parse_mode="Markdown")
    else:
        await context.bot.send_message(chat_id=uid, text=confirm_text, parse_mode="Markdown")

# ── هندلر دکمه‌ها ───────────────────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query, data, uid = update.callback_query, update.callback_query.data, update.callback_query.message.chat.id
    await query.answer()
    if data == "noop": return

    quid = query.from_user.id

    # دکمه ورود کاربر بلاک شده به فاز تایپ درخواست رفع بلاک
    if data == "write_unblock_request":
        if quid in used_unblock_ticket:
            await query.edit_message_text("❌ خطا! شما قبلاً شانس خود را امتحان کرده‌اید."); return
        pending_unblock_text[quid] = True
        await query.edit_message_text("✍️ لطفاً دلیل خود را برای رفع مسدودی در قالب **یک پیام متنی** بنویسید و ارسال کنید:\n\n⚠️ توجه: به محض ارسال، پیام شما نهایی شده و فرصت دیگری ندارید.", parse_mode="Markdown"); return

    if data in ("set_mode_normal", "set_mode_anonymous"):
        if is_admin(quid): return
        user_mode[quid] = "normal" if data == "set_mode_normal" else "anonymous"
        label = ("✅ *حالت عادی فعال شد!*\n\n👤 اسم و پروفایلت همراه پیامت ارسال میشه.\n\nاز منوی زیر ادامه بده 👇"
                 if data == "set_mode_normal" else
                 "✅ *حالت ناشناس فعال شد!*\n\n🕵️ هیچ اطلاعاتی از تو ارسال نمیشه.\n\nاز منوی زیر ادامه بده 👇")
        await query.edit_message_text(label, parse_mode="Markdown", reply_markup=main_menu_keyboard()); return

    if data == "back_main":
        if is_admin(quid): return
        await query.edit_message_text(f"🏠 *منوی اصلی*\n\nیه گزینه انتخاب کن 👇", parse_mode="Markdown", reply_markup=main_menu_keyboard()); return

    if data == "goto_send":
        if is_admin(quid): return
        if not bot_state["active"]:
            await query.edit_message_text("⚠️ ربات در حال حاضر غیرفعال است."); return
        await query.edit_message_text("📨 *ارسال پیام*\n\nپیامت رو بنویس و ارسال کن 👇\n\n(با هر پیام عادی ۱ سکه جایزه می‌گیری!)", parse_mode="Markdown"); return

    if data == "open_settings":
        if is_admin(quid): return
        current = user_mode.get(quid)
        status_text = "🕵️ *ناشناس*" if current == "anonymous" else ("👤 *عادی*" if current == "normal" else "❓ هنوز انتخاب نشده")
        await query.edit_message_text(f"⚙️ *تنظیمات*\n\nحالت فعلی: {status_text}\n\nیه حالت انتخاب کن:", parse_mode="Markdown", reply_markup=mode_selection_keyboard()); return

    if data == "my_account":
        if is_admin(quid): return
        p = ensure_profile(quid)
        history_text = "\n".join(user_history.get(quid, [])[-5:]) or "تاریخچه‌ای وجود ندارد"
        await query.edit_message_text(
            f"👤 *حساب من*\n\n💰 موجودی سکه: {get_coins(quid)}\n🔐 حالت ارسال: {'🕵️ ناشناس' if user_mode.get(quid)=='anonymous' else '👤 عادی'}\n"
            f"📨 تعداد پیام‌های ارسالی: {p.get('msg_count',0)}\n📅 عضویت: {p.get('join_date','؟')}\n\n"
            f"📋 *آخرین تراکنش‌های سکه:*\n{history_text}",
            parse_mode="Markdown", reply_markup=kb([back_btn("back_main")])); return

    if data in ("priority_normal", "priority_urgent"):
        if is_admin(quid): return
        priority = data.split("_")[1]
        level    = PRIORITY_LEVELS[priority]
        coins    = get_coins(quid)
        if level["cost"] > coins:
            await query.answer(f"❌ سکه کافی نداری! برای ارسال فوری به ۱۰۰ سکه نیاز داری. ({coins}/{level['cost']})", show_alert=True); return
        pending_text = context.user_data.get("pending_text")
        if not pending_text:
            await query.edit_message_text("⚠️ پیام منقضی شده، لطفاً دوباره ارسال کن."); return
        await send_user_message(context, quid, query.from_user, priority=priority, text=pending_text)
        context.user_data.pop("pending_text", None)
        await query.edit_message_reply_markup(reply_markup=None); return

    # ── بخش ادمین‌ها و سطوح دسترسی ──────────────────────────────────────────────────
    if not is_admin(uid): return

    if data.startswith("reply_"):
        if not has_perm(uid, "can_reply"):
            await query.answer("❌ شما دسترسی پاسخگویی ندارید.", show_alert=True); return
        target_id = int(data.split("_")[1])
        reply_to[uid] = target_id
        name = users_db.get(target_id, {}).get("name", "ناشناس") if user_mode.get(target_id) != "anonymous" else "🕵️ ناشناس"
        await query.message.reply_text(f"✍️ *در حال پاسخ به {name}*\n\nهر پیامی بفرستی براش کپی میشه.\n\n💡 برای انصراف کلمه `انصراف` یا /cancel رو بفرست.", parse_mode="Markdown"); return

    if data.startswith("block_"):
        if not has_perm(uid, "can_manage_users"):
            await query.answer("❌ شما دسترسی مدیریت کاربران را ندارید.", show_alert=True); return
        target_id = int(data.split("_")[1])
        blocked_users.add(target_id)
        ensure_profile(target_id).setdefault("block_history", []).append(f"🚫 بلاک شد — {fmt_dt()}")
        await query.message.reply_text(f"🚫 کاربر *{users_db.get(target_id, {}).get('name', target_id)}* بلاک شد.", parse_mode="Markdown"); return

    if data.startswith("unblock_"):
        if not has_perm(uid, "can_manage_users"):
            await query.answer("❌ شما دسترسی مدیریت کاربران را ندارید.", show_alert=True); return
        target_id = int(data.split("_")[1])
        blocked_users.discard(target_id)
        ensure_profile(target_id).setdefault("block_history", []).append(f"✅ آنبلاک شد — {fmt_dt()}")
        await query.message.reply_text(f"✅ کاربر *{users_db.get(target_id, {}).get('name', target_id)}* آنبلاک شد.", parse_mode="Markdown"); return

    if data == "list_users":
        if not has_perm(uid, "can_manage_users"):
            await query.answer("❌ عدم دسترسی", show_alert=True); return
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

    # 📥 مدیریت هوشمند درخواست‌های آنبلاک در پنل ادمین
    if data == "manage_unblock_reqs":
        if not has_perm(uid, "can_manage_users"):
            await query.answer("❌ عدم دسترسی", show_alert=True); return
        if not unblock_requests:
            await query.edit_message_text("📥 *هیچ درخواست جدیدی برای رفع بلاک ثبت نشده است.*", parse_mode="Markdown", reply_markup=kb([back_btn()])); return
        
        text = "📥 *لیست درخواست‌های رفع مسدودی کاربران:*\n━━━━━━━━━━━━━━━━━━\n"
        keyboard = []
        for target_id, req_msg in list(unblock_requests.items()):
            info = users_db.get(target_id, {"name": "ناشناس", "username": "ندارد"})
            text += f"👤 کاربر: *{info['name']}* (`{target_id}`)\n📝 متن درخواست: _{req_msg}_\n━━━━━━━━━━━━━━━━━━\n"
            keyboard.append([
                btn(f"✅ آنبلاک {info['name']}", f"adm_accept_unblock_{target_id}"),
                btn(f"❌ رد درخواست", f"adm_reject_unblock_{target_id}")
            ])
        keyboard.append([back_btn()])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data.startswith("adm_accept_unblock_"):
        target_id = int(data.split("_")[3])
        blocked_users.discard(target_id)
        unblock_requests.pop(target_id, None)
        ensure_profile(target_id).setdefault("block_history", []).append(f"✅ آنبلاک شد (تایید درخواست) — {fmt_dt()}")
        await query.message.reply_text(f"✅ کاربر مسدود شده با موفقیت آنبلاک شد."); 
        try:
            await context.bot.send_message(chat_id=target_id, text="🎉 *درخواست رفع مسدودی شما توسط مدیریت تایید شد!*\n\nاکنون می‌توانید با ارسال دستور /start مجدداً از ربات استفاده کنید.", parse_mode="Markdown")
        except Exception: pass
        return

    if data.startswith("adm_reject_unblock_"):
        target_id = int(data.split("_")[3])
        unblock_requests.pop(target_id, None)
        await query.message.reply_text(f"❌ درخواست کاربر رد شد. (کاربر کماکان مسدود می‌ماند)"); 
        try:
            await context.bot.send_message(chat_id=target_id, text="❌ *درخواست رفع مسدودی شما پس از بررسی توسط مدیریت رد شد.*", parse_mode="Markdown")
        except Exception: pass
        return

    if data == "stats":
        if not has_perm(uid, "can_manage_users"):
            await query.answer("❌ عدم دسترسی", show_alert=True); return
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
        if not has_perm(uid, "can_broadcast"):
            await query.answer("❌ شما دسترسی ارسال پیام همگانی ندارید.", show_alert=True); return
        reply_to[uid] = "broadcast"
        await query.message.reply_text("📢 پیام همگانیت رو بنویس (یا بفرست انصراف):"); return

    if data == "back":
        await query.message.reply_text("🎛 *پنل مدیریت*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_panel_keyboard(uid)); return

    if data == "manage_coins":
        if not has_perm(uid, "can_manage_coins"):
            await query.answer("❌ عدم دسترسی", show_alert=True); return
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
        if not has_perm(uid, "can_manage_coins"):
            await query.answer("❌ عدم دسترسی", show_alert=True); return
        target_id = int(data.split("_")[1])
        pending_coin_add[uid] = target_id
        info = users_db.get(target_id, {"name": str(target_id)})
        await query.message.reply_text(
            f"💰 *افزودن/کاهش سکه*\n\nکاربر: {info['name']} | `{target_id}`\nموجودی فعلی: {get_coins(target_id)} سکه\n\nیه عدد بفرست (مثبت یا منفی، مثلاً `20` یا `-10`):",
            parse_mode="Markdown"); return

    if data.startswith("full_profile_"):
        if not has_perm(uid, "can_manage_users"):
            await query.answer("❌ عدم دسترسی", show_alert=True); return
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
        if not has_perm(uid, "can_manage_users"):
            await query.answer("❌ عدم دسترسی", show_alert=True); return
        target_id    = int(data[len("set_note_"):])
        pending_note_input[uid] = target_id
        info         = users_db.get(target_id, {"name": str(target_id)})
        current_note = user_profiles.get(target_id, {}).get("admin_note") or "—"
        await query.message.reply_text(
            f"📝 *یادداشت برای {info['name']}*\n\nیادداشت فعلی: {current_note}\n\nیادداشت جدید رو بنویس (یا بفرست 'حذف' تا پاک بشه):",
            parse_mode="Markdown"); return

    if uid != OWNER_CHAT_ID: return

    if data == "toggle_bot":
        bot_state["active"] = not bot_state["active"]
        status = "🟢 روشن شد" if bot_state["active"] else "🔴 خاموش شد"
        msg    = "کاربران میتونن پیام بفرستن." if bot_state["active"] else "⛔ کاربران به هیچ چیزی دسترسی ندارن."
        await query.message.reply_text(f"⚡ *وضعیت ربات:* {status}\n\n{msg}", parse_mode="Markdown", reply_markup=admin_panel_keyboard(uid)); return

    if data == "manage_admins":
        text = "👑 *بخش هوشمند مدیریت ادمین‌ها و دسترسی‌ها*\n\n"
        keyboard = [[btn("➕ افزودن ادمین جدید", "add_new_admin")]]
        if not admins_db:
            text += "⚠️ در حال حاضر هیچ ادمین فرعی تعریف نشده است."
        else:
            text += "👥 *لیست ادمین‌های فرعی فعلی:*\n"
            for adm_id, adm_info in admins_db.items():
                text += f"• 👤 {adm_info['name']} (`{adm_id}`) — دارای {len(adm_info['permissions'])} دسترسی\n"
                keyboard.append([btn(f"⚙️ تنظیم دسترسی {adm_info['name']}", f"editadmin_{adm_id}")])
        keyboard.append([back_btn()])
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)); return

    if data == "add_new_admin":
        pending_admin_add[OWNER_CHAT_ID] = True
        await query.message.reply_text("👑 *افزودن ادمین فرعی*\n\nلطفاً **Chat ID** عددی کاربر مورد نظر را ارسال کنید:", parse_mode="Markdown"); return

    if data.startswith("editadmin_"):
        admin_id = int(data.split("_")[1])
        info = admins_db.get(admin_id, {"name": "ادمین"})
        await query.edit_message_text(
            f"⚙️ *تنظیم و ویرایش دسترسی‌های ادمین: {info['name']}*\n\nروی هر گزینه کلیک کنید تا فعال یا غیرفعال شود:",
            parse_mode="Markdown", reply_markup=admin_permissions_keyboard(admin_id)); return

    if data.startswith("toggleperm_"):
        _, admin_id_str, perm_key = data.split("_", 2)
        admin_id = int(admin_id_str)
        if admin_id in admins_db:
            perms = admins_db[admin_id]["permissions"]
            if perm_key in perms: perms.remove(perm_key)
            else: perms.add(perm_key)
        await query.edit_message_reply_markup(reply_markup=admin_permissions_keyboard(admin_id)); return

    if data.startswith("removeadmin_"):
        admin_id = int(data.split("_")[1])
        name = admins_db.pop(admin_id, {}).get("name", "ادمین")
        await query.message.reply_text(f"🗑 ادمین فرعی *{name}* حذف شد.")
        return


# ── هندلر جامع پیام‌ها ──────────────────────────────────────────────────────

async def handle_admin_media_and_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_chat.id
    if update.effective_chat.type != "private": return
    
    text = update.message.text or ""

    # منطق دریافت درخواست رفع بلاک کاربر مسدود شده
    if uid in blocked_users:
        if pending_unblock_text.get(uid):
            if not update.message.text:
                await update.message.reply_text("❌ درخواست رفع بلاک حتماً باید به صورت پیام متنی ارسال شود."); return
            
            pending_unblock_text.pop(uid, None)
            used_unblock_ticket.add(uid)  # سوزاندن بلیت شانس کاربر
            unblock_requests[uid] = text.strip() # ثبت درخواست
            
            await update.message.reply_text("✅ *درخواست شما با موفقیت ثبت شد و در صف بررسی قرار گرفت.*\n\nنتیجه آن به محض بررسی توسط ارشیا از همین طریق به شما اعلام خواهد شد.", parse_mode="Markdown")
            
            # اطلاع‌رسانی سریع به ادمین‌های مربوطه
            targets = [OWNER_CHAT_ID] + [adm_id for adm_id, adm_info in admins_db.items() if "can_manage_users" in adm_info["permissions"]]
            for admin_id in targets:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=f"📥 *یک درخواست رفع مسدودی جدید ثبت شد!*\nبرای بررسی به پنل مدیریت بخش درخواست‌های رفع بلاک مراجعه کنید.")
                except Exception: pass
        return

    if not is_admin(uid):
        await forward_message(update, context); return

    if text.strip() in ("انصراف", "/cancel"):
        await cancel_command(update, context); return

    if uid == OWNER_CHAT_ID and pending_admin_add.get(OWNER_CHAT_ID):
        pending_admin_add.pop(OWNER_CHAT_ID)
        try: target_admin_id = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ خطا! شناسه ادمین باید عدد باشد."); return
        user_info = users_db.get(target_admin_id, {"name": f"کاربر {target_admin_id}"})
        admins_db[target_admin_id] = {"name": user_info["name"], "permissions": set(["can_reply"])}
        await update.message.reply_text(f"✅ ادمین اضافه شد.", reply_markup=admin_permissions_keyboard(target_admin_id)); return

    if pending_note_input.get(uid):
        if not has_perm(uid, "can_manage_users"): return
        target_id = pending_note_input.pop(uid)
        p = ensure_profile(target_id)
        if text.strip() == "حذف":
            p["admin_note"] = ""
            await update.message.reply_text("🗑 یادداشت حذف شد.")
        else:
            p["admin_note"] = text.strip()
            await update.message.reply_text(f"📝 یادداشت ذخیره شد.")
        return

    if pending_coin_add.get(uid):
        if not has_perm(uid, "can_manage_coins"): return
        target_id = pending_coin_add.pop(uid)
        try: amount = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ فقط عدد بفرستید."); return
        new_balance = add_coins(target_id, amount, f"تغییر توسط ادمین")
        await update.message.reply_text(f"✅ موجودی بروز شد. موجودی جدید: {new_balance}")
        try:
            await context.bot.send_message(chat_id=target_id, text=f"💰 موجودی جدید سکه‌های شما: {new_balance}")
        except Exception: pass
        return

    if reply_to.get(uid) == "broadcast":
        if not has_perm(uid, "can_broadcast"): return
        del reply_to[uid]
        success = 0
        for u_id in users_db:
            if u_id not in blocked_users and not is_admin(u_id):
                try:
                    if update.message.text:
                        await context.bot.send_message(chat_id=u_id, text=f"📢 *پیام همگانی از طرف مدیریت:*\n\n{text}", parse_mode="Markdown")
                    else:
                        await context.bot.send_message(chat_id=u_id, text=f"📢 *پیام رسانه‌ای همگانی از طرف مدیریت:*", parse_mode="Markdown")
                        await context.bot.copy_message(chat_id=u_id, from_chat_id=uid, message_id=update.message.message_id)
                    success += 1
                except Exception: pass
        await update.message.reply_text(f"✅ پیام به {success} کاربر ارسال شد."); return

    if uid in reply_to:
        if not has_perm(uid, "can_reply"): return
        target_id = reply_to.pop(uid)
        try:
            mapped_data = message_map.get(f"reply_{target_id}_{uid}")
            reply_to_user_msg_id = None
            admin_msg_id_in_panel = None
            if isinstance(mapped_data, tuple):
                admin_msg_id_in_panel, reply_to_user_msg_id = mapped_data

            await context.bot.copy_message(
                chat_id=target_id, 
                from_chat_id=uid, 
                message_id=update.message.message_id,
                reply_to_message_id=reply_to_user_msg_id
            )
            if admin_msg_id_in_panel:
                await context.bot.send_message(chat_id=uid, text="✅ پاسخ شما ارسال شد.", reply_to_message_id=admin_msg_id_in_panel)
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
    
    print("✅ ربات ارشیا (به همراه منوی درخواست آنبلاک یکبارمصرف) روشن شد...")
    app.run_polling(allowed_updates=["message", "callback_query", "poll_answer"])

if __name__ == "__main__":
    main()
