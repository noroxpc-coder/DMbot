cat > /mnt/user-data/outputs/telegram_bot/bot.py << 'PYEOF'
import logging, secrets, string
from datetime import datetime, timedelta, timezone

try:
    import pytz
    TZ = pytz.timezone("Asia/Tehran")
    now = lambda: datetime.now(TZ)
except ImportError:
    TZ = timezone(timedelta(hours=3, minutes=30))
    now = lambda: datetime.now(TZ)

fmt = lambda dt=None: (dt or now()).strftime("%Y-%m-%d | %H:%M") + " (تهران)"

from telegram import Update, InlineKeyboardButton as Btn, InlineKeyboardMarkup as Mkp
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, PollAnswerHandler, filters, ContextTypes

BOT_TOKEN     = "8977895133:AAHdVjMrr-9-ceXXviV5Zt5I_vP93HxQqZY"
ADMIN         = 1143598012
cfg           = {"card_number": "6037-XXXX-XXXX-XXXX", "card_owner": "نام صاحب کارت"}
users         = {}; blocked = set(); reply_to = {}; msg_map = {}
group_mode    = {}; u_mode = {}; coins = {}; history = {}
poll_q        = {}; poll_v = {}; subs = {}; receipts = {}; receipt_inp = set()
coin_inp      = {}; profiles = {}; tokens = {}; u_tokens = {}; submitting = set()
note_inp      = {}; bot_on = {"v": True}
PLANS         = {"p1": {"name": "اشتراک یک ماهه", "days": 30, "price": "۴۰,۰۰۰ تومان", "description": "دسترسی کامل ۳۰ روزه"}}
PRI           = {"normal": {"emoji":"🟢","cost":0,"title":"عادی"}, "vip":{"emoji":"🟡","cost":10,"title":"ویژه"}, "urgent":{"emoji":"🔴","cost":30,"title":"فوری"}}

logging.basicConfig(format="%(levelname)s - %(message)s", level=logging.WARNING)

# ── helpers ──────────────────────────────────────────────────────────────────
def gc(uid): return coins.get(uid, 0)
def ac(uid, n, r=""):
    coins[uid] = gc(uid) + n
    history.setdefault(uid, []).append(f"{'➕' if n>=0 else '➖'} {abs(n)} — {r or '—'} | {fmt()}")
    return coins[uid]

def ep(uid):
    if uid not in profiles: profiles[uid] = {"join":fmt(),"msgs":0,"note":"","bh":[],"seen":fmt()}
    return profiles[uid]

def sub_ok(uid):
    s = subs.get(uid); return bool(s) and now() < s["exp"]

def sub_txt(uid):
    s = subs.get(uid)
    if not s: return "❌ ندارید"
    p = PLANS.get(s["plan"], {})
    return f"⌛ منقضی" if now() >= s["exp"] else f"✅ {p.get('name','؟')} — {(s['exp']-now()).days} روز مانده"

def mk_token():
    while True:
        t = "BOT-" + "".join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(8))
        if t not in tokens: return t

def new_token(uid):
    t = mk_token()
    tokens[t] = {"uid": uid, "used": False, "bot": None, "at": fmt()}
    u_tokens.setdefault(uid, []).append(t)
    return t

def profile_txt(uid):
    u = users.get(uid, {"name": str(uid), "username": "ندارد"})
    p = ep(uid); tl = u_tokens.get(uid, [])
    t_lines = "".join(f"  • `{t}` — {'✅' if tokens.get(t,{}).get('used') else '⏳'}\n" for t in tl) or "  — ندارد\n"
    bh = "\n".join(f"  • {b}" for b in p.get("bh",[])[-3:]) or "  — سابقه‌ای ندارد"
    return (f"👤 *پروفایل*\n{'━'*18}\n🏷 {u['name']}\n🆔 @{u['username']}\n🔢 `{uid}`\n{'━'*18}\n"
            f"📅 عضویت: {p['join']}\n🕐 آخرین فعالیت: {p['seen']}\n📨 پیام‌ها: {p['msgs']}\n{'━'*18}\n"
            f"💰 سکه: {gc(uid)}\n📦 اشتراک: {sub_txt(uid)}\n🔐 حالت: {'🕵️ ناشناس' if u_mode.get(uid)=='anonymous' else '👤 عادی'}\n"
            f"🚫 بلاک: {'بله' if uid in blocked else 'خیر'}\n{'━'*18}\n🤖 توکن‌ها:\n{t_lines}{'━'*18}\n📋 بلاک:\n{bh}\n{'━'*18}\n📝 یادداشت: {p.get('note') or '—'}")

# ── keyboards ─────────────────────────────────────────────────────────────────
def K(*rows): return Mkp(list(rows))
def B(t, d): return Btn(t, callback_data=d)
def back(d="back"): return B("🔙 برگشت", d)

def main_kb(): return K([B("📨 ارسال پیام به ادمین","goto_send")],[B("🛒 خرید اشتراک","show_plans")],[B("👤 حساب من","my_account")],[B("🤖 ربات من","my_bots")],[B("⚙️ تنظیمات","open_settings")])
def mode_kb(): return K([B("👤 با اسم (عادی)","set_mode_normal")],[B("🕵️ ناشناس","set_mode_anonymous")])
def pri_kb(uid): return K([B("🟢 عادی (رایگان)","priority_normal")],[B("🟡 ویژه (۱۰ سکه)","priority_vip")],[B("🔴 فوری (۳۰ سکه)","priority_urgent")],[B(f"💰 موجودی: {gc(uid)} سکه","noop")])
def plans_kb(): return Mkp([[B(f"⭐ {p['name']} — {p['price']}",f"buy_{pid}")] for pid,p in PLANS.items()]+[[back("back_main")]])
def admin_kb():
    s = "🟢 روشن" if bot_on["v"] else "🔴 خاموش"
    return K([B("👥 لیست کاربران","list_users")],[B("🚫 بلاک‌شده‌ها","list_blocked")],[B("📊 آمار","stats")],[B("📢 پیام همگانی","broadcast")],[B("👥 پیام به گروه","send_group")],[B("🗳 نظرسنجی","create_poll")],[B("💰 مدیریت سکه","manage_coins")],[B("🛒 مدیریت اشتراک‌ها","manage_subs")],[B("🧾 رسیدهای در انتظار","pending_receipts_admin")],[B("💳 شماره کارت","set_card")],[B("🤖 مدیریت توکن‌ها","manage_tokens")],[B(f"⚡ وضعیت: {s}","toggle_bot")])

# ── core handlers ─────────────────────────────────────────────────────────────
async def start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_chat.id
    if u.effective_chat.type != "private": return
    if uid == ADMIN: await panel(u, ctx); return
    if not bot_on["v"]: await u.message.reply_text("⛔ ربات غیرفعال است."); return
    user = u.effective_user
    users[uid] = {"name": user.full_name, "username": user.username or "ندارد", "chat_id": uid}
    ep(uid)["seen"] = fmt()
    if uid not in u_mode:
        await u.message.reply_text("👋 *سلام!*\n\nنحوه نمایش هویتت رو انتخاب کن:\n\n👤 *با اسم* — ادمین اسمت رو میبینه\n🕵️ *ناشناس* — هیچ اطلاعاتی نمیفرسته", parse_mode="Markdown", reply_markup=mode_kb())
    else:
        cur = "🕵️ ناشناس" if u_mode[uid]=="anonymous" else "👤 عادی"
        await u.message.reply_text(f"👋 *سلام {user.first_name}!*\n\nحالت: {cur}\nاشتراک: {sub_txt(uid)}", parse_mode="Markdown", reply_markup=main_kb())

async def panel(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != ADMIN: return
    await u.message.reply_text("🎛 *پنل مدیریت*\nیه گزینه انتخاب کن:", parse_mode="Markdown", reply_markup=admin_kb())

async def settings(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_chat.id
    if u.effective_chat.type != "private" or uid == ADMIN: return
    cur = u_mode.get(uid)
    st = "🕵️ *ناشناس*" if cur=="anonymous" else ("👤 *عادی*" if cur=="normal" else "❓ انتخاب نشده")
    await u.message.reply_text(f"⚙️ *تنظیمات*\n\nحالت فعلی: {st}\n\nیه حالت انتخاب کن:", parse_mode="Markdown", reply_markup=mode_kb())

async def send_msg(ctx, uid, user, priority="normal", text=None, orig=None, tgt=None):
    lv = PRI[priority]; anon = u_mode[uid]=="anonymous"
    sub_tag = " | ⭐" if sub_ok(uid) else ""
    ptag = "\n🟡 *پیام ویژه*" if priority=="vip" else ("\n🔴 *پیام فوری* ⚡️" if priority=="urgent" else "")
    info = f"📩 *پیام جدید*{ptag}\n{'🕵️ ناشناس' if anon else f'👤 {user.full_name}'}{sub_tag}\n{'─'*20}"
    if not anon: info = f"📩 *پیام جدید*{ptag}\n👤 {user.full_name}{sub_tag}\n🆔 @{user.username or 'ندارد'}\n🔢 `{uid}`\n{'─'*20}"
    await ctx.bot.send_message(ADMIN, info, parse_mode="Markdown", reply_markup=Mkp([[B("↩️ پاسخ",f"reply_{uid}"),B("🚫 بلاک",f"block_{uid}")]]))
    fwd = await (ctx.bot.send_message(ADMIN, text) if text else (orig.copy_to(ADMIN) if anon else orig.forward(ADMIN)))
    msg_map[f"reply_{uid}"] = fwd.message_id
    if lv["cost"]: ac(uid, -lv["cost"], f"اولویت {lv['title']}")
    ctxt = "✅ پیامت دریافت شد." + (" 🟡" if priority=="vip" else " 🔴" if priority=="urgent" else "") + (" 🕵️" if anon else "")
    if tgt: await tgt.reply_text(ctxt, parse_mode="Markdown")
    else: await ctx.bot.send_message(uid, ctxt, parse_mode="Markdown")

async def forward_message(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user, uid = u.effective_user, u.effective_chat.id
    if u.effective_chat.type != "private" or uid == ADMIN: return
    if uid in blocked: await u.message.reply_text("⛔ مسدود شده‌اید."); return
    if not bot_on["v"]: await u.message.reply_text("⛔ ربات غیرفعال است."); return
    ep(uid)["seen"] = fmt()
    if uid in receipt_inp:
        if not (u.message.photo or u.message.document): await u.message.reply_text("📸 تصویر رسید رو ارسال کن."); return
        receipt_inp.discard(uid); ri = receipts.get(uid)
        if not ri: await u.message.reply_text("❌ خطا. دوباره /start بزن."); return
        plan = PLANS.get(ri["plan"], {}); ui = users.get(uid, {"name":str(uid),"username":"ندارد"})
        kb = Mkp([[B("✅ تایید",f"approve_sub_{uid}::{ri['plan']}"),B("❌ رد",f"reject_sub_{uid}")]])
        cap = f"🧾 *رسید جدید*\n👤 {ui['name']}\n🆔 `{uid}`\n📦 {plan.get('name','؟')}\n⏰ {fmt()}"
        try:
            fn = ctx.bot.send_photo if u.message.photo else ctx.bot.send_document
            fid = u.message.photo[-1].file_id if u.message.photo else u.message.document.file_id
            await fn(ADMIN, fid, caption=cap, parse_mode="Markdown", reply_markup=kb)
            await u.message.reply_text("✅ رسید دریافت شد! ادمین بررسی می‌کنه.")
        except: await u.message.reply_text("❌ خطا در ارسال رسید.")
        return
    if uid in submitting:
        t = (u.message.text or "").strip()
        if not t: await u.message.reply_text("❌ توکن نامعتبر."); return
        submitting.discard(uid); td = tokens.get(t)
        if not td: await u.message.reply_text("❌ توکن نامعتبر!"); return
        if td["uid"] != uid: await u.message.reply_text("❌ این توکن مال شما نیست."); return
        if td["used"]: await u.message.reply_text(f"⚠️ قبلاً استفاده شده. ربات: @{td.get('bot','؟')}"); return
        ctx.user_data["pending_token"] = t
        await u.message.reply_text("✅ توکن معتبر!\n\nیوزرنیم ربات تلگرامی که ساختی رو بفرست:", parse_mode="Markdown"); return
    if ctx.user_data.get("pending_token"):
        bot_u = (u.message.text or "").strip()
        if not bot_u: await u.message.reply_text("❌ یوزرنیم معتبر نیست."); return
        t = ctx.user_data.pop("pending_token"); td = tokens.get(t)
        if not td: await u.message.reply_text("❌ خطا."); return
        td.update({"used":True,"bot":bot_u,"used_at":fmt()})
        await u.message.reply_text(f"🎉 ربات ثبت شد!\n🤖 {bot_u}\n🔑 `{t}`", parse_mode="Markdown", reply_markup=main_kb())
        try: await ctx.bot.send_message(ADMIN, f"🤖 *ربات جدید*\n👤 {users.get(uid,{}).get('name',uid)}\n🔑 `{t}`\n🤖 {bot_u}\n⏰ {fmt()}", parse_mode="Markdown")
        except: pass
        return
    if uid not in u_mode: await u.message.reply_text("⚠️ اول حالت ارسال رو انتخاب کن:", reply_markup=mode_kb()); return
    users[uid] = {"name":user.full_name,"username":user.username or "ندارد","chat_id":uid}
    ep(uid)["msgs"] = ep(uid).get("msgs",0)+1
    if u.message.text:
        ctx.user_data["pending_text"] = u.message.text
        await u.message.reply_text("📨 با چه اولویتی ارسال شه?\n\n🟢 عادی | 🟡 ویژه ۱۰ سکه | 🔴 فوری ۳۰ سکه", reply_markup=pri_kb(uid)); return
    await send_msg(ctx, uid, user, orig=u.message, tgt=u.message)

# ── poll ──────────────────────────────────────────────────────────────────────
async def send_poll(ctx, info, target):
    q, opts = info["question"], info["options"]
    def store(pid): poll_v[pid] = {"question":q,"opts":{i:0 for i in range(len(opts))},"names":opts,"total":0}
    if target == "all":
        n = 0
        for uid in users:
            if uid not in blocked:
                try: s = await ctx.bot.send_poll(uid, q, opts, is_anonymous=False); store(s.poll.id); n+=1
                except: pass
        return n
    try: s = await ctx.bot.send_poll(target, q, opts, is_anonymous=False); store(s.poll.id); return 1
    except: return 0

async def handle_poll_answer(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    a, pid = u.poll_answer, u.poll_answer.poll_id
    if pid not in poll_v: poll_v[pid] = {"question":"نظرسنجی","opts":{},"names":[],"total":0}
    info = poll_v[pid]; info["total"] = info.get("total",0)+1
    for oid in a.option_ids: info["opts"][oid] = info["opts"].get(oid,0)+1
    t = info["total"]
    lines = [f"📊 *نتایج* — {info['question']}\n"]
    for i, nm in enumerate(info.get("names",[])):
        c = info["opts"].get(i,0); pct = round(c/t*100) if t else 0
        lines.append(f"• {nm}\n  {'█'*(pct//10)}{'░'*(10-pct//10)} {pct}% ({c})")
    lines.append(f"\n👥 مجموع: {t}")
    try: await ctx.bot.send_message(ADMIN, "\n".join(lines), parse_mode="Markdown")
    except: pass

# ── button handler ────────────────────────────────────────────────────────────
async def btn(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query; d = q.data; cid = q.message.chat.id
    await q.answer()
    if d == "noop": return

    # حالت کاربر
    if d in ("set_mode_normal","set_mode_anonymous"):
        uid = q.from_user.id
        if uid == ADMIN: return
        u_mode[uid] = "normal" if d=="set_mode_normal" else "anonymous"
        lbl = "✅ *حالت عادی فعال شد!*" if d=="set_mode_normal" else "✅ *حالت ناشناس فعال شد!*"
        await q.edit_message_text(lbl+"\n\nاز منوی زیر ادامه بده 👇", parse_mode="Markdown", reply_markup=main_kb()); return

    if d == "back_main":
        uid = q.from_user.id
        await q.edit_message_text(f"🏠 *منوی اصلی*\n\nحالت: {'🕵️ ناشناس' if u_mode.get(uid)=='anonymous' else '👤 عادی'}\nاشتراک: {sub_txt(uid)}", parse_mode="Markdown", reply_markup=main_kb()); return

    if d == "goto_send":
        uid = q.from_user.id
        if uid==ADMIN or not bot_on["v"]: await q.edit_message_text("⚠️ ربات غیرفعال است."); return
        await q.edit_message_text("📨 پیامت رو بفرست 👇\n(متن، عکس، فایل — همه قبوله)", parse_mode="Markdown"); return

    if d == "open_settings":
        uid = q.from_user.id
        if uid==ADMIN: return
        cur = u_mode.get(uid); st = "🕵️ ناشناس" if cur=="anonymous" else ("👤 عادی" if cur=="normal" else "انتخاب نشده")
        await q.edit_message_text(f"⚙️ *تنظیمات*\n\nحالت: {st}\n\nانتخاب کن:", parse_mode="Markdown", reply_markup=mode_kb()); return

    if d == "my_account":
        uid = q.from_user.id
        if uid==ADMIN: return
        p = ep(uid); hl = user_history.get(uid,[])
        await q.edit_message_text(f"👤 *حساب من*\n\n💰 سکه: {gc(uid)}\n🔐 حالت: {'🕵️ ناشناس' if u_mode.get(uid)=='anonymous' else '👤 عادی'}\n📦 اشتراک: {sub_txt(uid)}\n📨 پیام‌ها: {p.get('msgs',0)}\n📅 عضویت: {p.get('join','؟')}\n\n📋 *آخرین تراکنش‌ها:*\n{chr(10).join(hl[-5:]) or '—'}", parse_mode="Markdown", reply_markup=Mkp([[back("back_main")]])); return

    if d == "my_bots":
        uid = q.from_user.id
        if uid==ADMIN: return
        tl = u_tokens.get(uid,[])
        if not tl:
            await q.edit_message_text("🤖 *ربات من*\n\nتوکنی دریافت نکردی.\nاول اشتراک بخر سپس از ادمین توکن بگیر.", parse_mode="Markdown", reply_markup=Mkp([[B("📨 پیام به ادمین","goto_send")],[B("🛒 خرید اشتراک","show_plans")],[back("back_main")]])); return
        txt = "🤖 *ربات‌های من*\n\n"+"".join(f"🔑 `{t}`\n   {'✅ @'+tokens.get(t,{}).get('bot','؟') if tokens.get(t,{}).get('used') else '⏳ استفاده نشده'}\n\n" for t in tl)
        kb = ([[B("🔑 وارد کردن توکن","submit_token")]] if any(not tokens.get(t,{}).get("used") for t in tl) else [])+[[back("back_main")]]
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=Mkp(kb)); return

    if d == "submit_token":
        uid = q.from_user.id
        if uid==ADMIN: return
        submitting.add(uid)
        await q.edit_message_text("🔑 توکنی که از ادمین گرفتی رو بفرست:", parse_mode="Markdown"); return

    if d == "show_plans":
        uid = q.from_user.id
        if uid==ADMIN: return
        receipt_inp.discard(uid); receipts.pop(uid,None)
        txt = "🛒 *خرید اشتراک*\n\n"+"".join(f"⭐ *{p['name']}* — {p['price']}\n{p['description']}\n\n" for p in PLANS.values())
        await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=plans_kb()); return

    if d.startswith("buy_"):
        uid = q.from_user.id
        if uid==ADMIN: return
        pid = d[4:]; plan = PLANS.get(pid)
        if not plan: return
        receipts[uid]={"plan":pid}; receipt_inp.add(uid)
        await q.edit_message_text(f"💳 *پرداخت*\n📦 {plan['name']}\n💰 {plan['price']}\n\n💳 شماره کارت:\n`{cfg['card_number']}`\n👤 {cfg['card_owner']}\n\n📸 بعد از پرداخت تصویر رسید رو ارسال کن 👇", parse_mode="Markdown", reply_markup=Mkp([[B("🔙 انصراف","show_plans")]])); return

    if d.startswith("approve_sub_"):
        if cid!=ADMIN: return
        payload = d[len("approve_sub_"):]; tid_s, pid = payload.split("::",1)
        tid = int(tid_s); plan = PLANS.get(pid,{})
        exp = now() + timedelta(days=plan.get("days",30))
        subs[tid] = {"plan":pid,"exp":exp}; receipts.pop(tid,None); receipt_inp.discard(tid)
        sfx = f"\n\n✅ تایید شد — {now().strftime('%H:%M')}"
        try:
            if q.message.caption is not None: await q.edit_message_caption(q.message.caption+sfx, parse_mode="Markdown")
            else: await q.edit_message_text((q.message.text or "")+sfx, parse_mode="Markdown")
        except: pass
        try: await ctx.bot.send_message(tid, f"🎉 اشتراک فعال شد!\n📦 {plan.get('name','؟')}\n📅 تا {exp.strftime('%Y-%m-%d')}", parse_mode="Markdown", reply_markup=main_kb())
        except: pass
        return

    if d.startswith("reject_sub_"):
        if cid!=ADMIN: return
        tid = int(d[len("reject_sub_"):]); receipts.pop(tid,None); receipt_inp.discard(tid)
        sfx = f"\n\n❌ رد شد — {now().strftime('%H:%M')}"
        try:
            if q.message.caption is not None: await q.edit_message_caption(q.message.caption+sfx, parse_mode="Markdown")
            else: await q.edit_message_text((q.message.text or "")+sfx, parse_mode="Markdown")
        except: pass
        try: await ctx.bot.send_message(tid, "❌ رسید تایید نشد. با ادمین تماس بگیر.")
        except: pass
        return

    if d in ("priority_normal","priority_vip","priority_urgent"):
        uid = q.from_user.id
        if uid==ADMIN: return
        pri = d.split("_")[1]; lv = PRI[pri]
        if lv["cost"] > gc(uid): await q.answer(f"❌ سکه کافی نداری! ({gc(uid)}/{lv['cost']})", show_alert=True); return
        pt = ctx.user_data.get("pending_text")
        if not pt: await q.edit_message_text("⚠️ پیام منقضی شده، دوباره ارسال کن."); return
        await send_msg(ctx, uid, q.from_user, priority=pri, text=pt)
        ctx.user_data.pop("pending_text",None); await q.edit_message_reply_markup(reply_markup=None); return

    # ── ادمین ──
    if cid != ADMIN: return

    if d.startswith("reply_"):
        tid = int(d.split("_")[1]); reply_to[ADMIN] = tid
        nm = (users.get(tid,{}).get("name","ناشناس") if u_mode.get(tid)!="anonymous" else "🕵️ ناشناس")
        await q.message.reply_text(f"✍️ پیامت رو بنویس برای *{nm}*:", parse_mode="Markdown"); return

    if d.startswith("block_"):
        tid = int(d.split("_")[1]); blocked.add(tid)
        ep(tid).setdefault("bh",[]).append(f"🚫 {fmt()}")
        await q.message.reply_text(f"🚫 {users.get(tid,{}).get('name',tid)} بلاک شد."); return

    if d.startswith("unblock_"):
        tid = int(d.split("_")[1]); blocked.discard(tid)
        ep(tid).setdefault("bh",[]).append(f"✅ آنبلاک {fmt()}")
        await q.message.reply_text(f"✅ {users.get(tid,{}).get('name',tid)} آنبلاک شد."); return

    if d == "list_users":
        if not users: await q.message.reply_text("👥 هنوز کاربری نداری."); return
        txt = "👥 *کاربران:*\n\n"; kb = []
        for uid, info in users.items():
            p = ep(uid)
            txt += f"{'🚫' if uid in blocked else '✅'}{'🕵️' if u_mode.get(uid)=='anonymous' else '👤'}{'⭐' if sub_ok(uid) else ''} {info['name']} | @{info['username']} | `{uid}` | 💰{gc(uid)} | 📨{p.get('msgs',0)}\n"
            kb.append([B(f"👁 {info['name']}",f"full_profile_{uid}"),B("↩️",f"reply_{uid}"),B("🚫" if uid not in blocked else "✅",f"{'block' if uid not in blocked else 'unblock'}_{uid}")])
        kb.append([back()])
        await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=Mkp(kb)); return

    if d == "list_blocked":
        if not blocked: await q.message.reply_text("🚫 هیچ کاربری بلاک نشده."); return
        txt = "🚫 *بلاک‌شده‌ها:*\n\n"; kb = []
        for uid in blocked:
            info = users.get(uid,{"name":str(uid),"username":"ندارد"})
            txt += f"🚫 {info['name']} | @{info['username']} | `{uid}`\n"
            kb.append([B(f"✅ آنبلاک {info['name']}",f"unblock_{uid}")])
        kb.append([back()])
        await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=Mkp(kb)); return

    if d == "stats":
        t = len(users); bl = len(blocked)
        await q.message.reply_text(f"📊 *آمار*\n\n👥 کل: {t}\n✅ فعال: {t-bl}\n🚫 بلاک: {bl}\n⭐ اشتراک: {sum(1 for u in users if sub_ok(u))}\n🕵️ ناشناس: {sum(1 for u in users if u_mode.get(u)=='anonymous')}\n⚡ وضعیت: {'🟢 روشن' if bot_on['v'] else '🔴 خاموش'}", parse_mode="Markdown", reply_markup=Mkp([[back()]])); return

    if d == "broadcast": reply_to[ADMIN]="broadcast"; await q.message.reply_text("📢 پیام همگانیت رو بنویس:"); return
    if d == "send_group": group_mode[ADMIN]="waiting_id"; await q.message.reply_text("👥 آیدی گروه رو بفرست:\n(مثلاً `-1001234567890`)", parse_mode="Markdown"); return
    if d == "back": await q.message.reply_text("🎛 *پنل مدیریت*", parse_mode="Markdown", reply_markup=admin_kb()); return
    if d == "create_poll": poll_q[ADMIN]={"step":"question"}; await q.message.reply_text("🗳 سوال نظرسنجی رو بنویس:"); return

    if d == "poll_target_all":
        info = poll_q.get(ADMIN)
        if not info: return
        n = await send_poll(ctx, info, "all"); del poll_q[ADMIN]
        await q.message.reply_text(f"✅ نظرسنجی برای {n} کاربر ارسال شد."); return

    if d == "poll_target_group":
        info = poll_q.get(ADMIN)
        if not info: return
        info["step"]="waiting_group_id"; await q.message.reply_text("👥 آیدی گروه رو بفرست:"); return

    if d == "manage_coins":
        if not users: await q.message.reply_text("👥 کاربری نداری."); return
        kb = [[B(f"💰 {info['name']} ({gc(uid)} سکه)",f"addcoin_{uid}")] for uid,info in users.items()]+[[back()]]
        await q.message.reply_text("💰 *مدیریت سکه*", parse_mode="Markdown", reply_markup=Mkp(kb)); return

    if d.startswith("addcoin_"):
        tid = int(d.split("_")[1]); coin_inp[ADMIN]=tid
        info = users.get(tid,{"name":str(tid)})
        await q.message.reply_text(f"💰 موجودی {info['name']}: {gc(tid)} سکه\n\nعدد بفرست (مثبت یا منفی):", parse_mode="Markdown"); return

    if d == "manage_subs":
        if not users: await q.message.reply_text("👥 کاربری نداری."); return
        kb = [[B(f"⭐ {info['name']}",f"sub_manage_{uid}")] for uid,info in users.items()]+[[back()]]
        await q.message.reply_text("🛒 *اشتراک‌ها*", parse_mode="Markdown", reply_markup=Mkp(kb)); return

    if d.startswith("sub_manage_"):
        tid = int(d[len("sub_manage_"):]); info = users.get(tid,{"name":str(tid)})
        kb = [[B(f"➕ {p['name']} ({p['days']} روز)",f"admin_add_sub_{tid}__{pid}")] for pid,p in PLANS.items()]+[[B("🗑 لغو اشتراک",f"admin_del_sub_{tid}")],[back("manage_subs")]]
        await q.message.reply_text(f"👤 *{info['name']}*\n\n{sub_txt(tid)}", parse_mode="Markdown", reply_markup=Mkp(kb)); return

    if d.startswith("admin_add_sub_"):
        payload = d[len("admin_add_sub_"):]; tid_s, pid = payload.split("__",1)
        tid = int(tid_s); plan = PLANS.get(pid,{})
        base = subs.get(tid,{}).get("exp", now()); base = max(base, now())
        exp = base + timedelta(days=plan.get("days",30))
        subs[tid] = {"plan":pid,"exp":exp}
        await q.message.reply_text(f"✅ اشتراک {plan.get('name','؟')} برای {users.get(tid,{}).get('name',tid)} فعال شد.", parse_mode="Markdown")
        try: await ctx.bot.send_message(tid, f"🎉 اشتراک فعال شد!\n📦 {plan.get('name','؟')}\n📅 تا {exp.strftime('%Y-%m-%d')}", parse_mode="Markdown")
        except: pass
        return

    if d.startswith("admin_del_sub_"):
        tid = int(d[len("admin_del_sub_"):]); subs.pop(tid,None)
        await q.message.reply_text(f"🗑 اشتراک {users.get(tid,{}).get('name',tid)} لغو شد.")
        try: await ctx.bot.send_message(tid, "⚠️ اشتراک شما لغو شد.")
        except: pass
        return

    if d == "pending_receipts_admin":
        if not receipts: await q.message.reply_text("✅ رسید در انتظاری نیست."); return
        txt = "🧾 *رسیدهای در انتظار:*\n\n"+"".join(f"👤 {users.get(uid,{}).get('name',uid)} | `{uid}` | {PLANS.get(ri['plan'],{}).get('name','؟')}\n" for uid,ri in receipts.items())
        await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=Mkp([[back()]])); return

    if d == "set_card":
        await q.message.reply_text(f"💳 شماره کارت فعلی: `{cfg['card_number']}`\n👤 {cfg['card_owner']}\n\nشماره کارت جدید رو بفرست (۱۶ رقم):", parse_mode="Markdown")
        ctx.bot_data["pending_card"] = "number"; return

    if d == "toggle_bot":
        bot_on["v"] = not bot_on["v"]; s = "🟢 روشن" if bot_on["v"] else "🔴 خاموش"
        await q.message.reply_text(f"⚡ وضعیت: {s}", reply_markup=admin_kb()); return

    if d == "manage_tokens":
        kb = [[B(f"{'⭐' if sub_ok(uid) else '  '} {info['name']} — {len(u_tokens.get(uid,[]))} توکن",f"token_for_{uid}")] for uid,info in users.items()]+[[B("📋 همه توکن‌ها","list_all_tokens")],[back()]]
        await q.message.reply_text("🤖 *مدیریت توکن‌ها*", parse_mode="Markdown", reply_markup=Mkp(kb)); return

    if d.startswith("token_for_"):
        tid = int(d[len("token_for_"):]); info = users.get(tid,{"name":str(tid)})
        tl = u_tokens.get(tid,[]); tlines = "".join(f"  {'✅' if tokens.get(t,{}).get('used') else '⏳'} `{t}`\n" for t in tl) or "  — ندارد\n"
        await q.message.reply_text(f"🤖 *{info['name']}*\n\n📦 {sub_txt(tid)}\n\n🔑 توکن‌ها:\n{tlines}", parse_mode="Markdown",
            reply_markup=Mkp([[B("🆕 توکن جدید",f"issue_token_{tid}")],[B("👁 پروفایل",f"full_profile_{tid}")],[back("manage_tokens")]])); return

    if d.startswith("issue_token_") and not d.startswith("issue_token_confirm_"):
        tid = int(d[len("issue_token_"):]); info = users.get(tid,{"name":str(tid)})
        if not sub_ok(tid):
            await q.message.reply_text(f"⚠️ {info['name']} اشتراک ندارد! مطمئنی؟", parse_mode="Markdown",
                reply_markup=Mkp([[B("✅ بله",f"issue_token_confirm_{tid}")],[B("❌ خیر",f"token_for_{tid}")]])); return
        t = new_token(tid)
        await q.message.reply_text(f"✅ توکن `{t}` برای {info['name']} صادر شد.", parse_mode="Markdown")
        try: await ctx.bot.send_message(tid, f"🎉 *توکن ربات‌سازی:*\n`{t}`\n\nبه منوی «🤖 ربات من» برو و توکن رو وارد کن.", parse_mode="Markdown", reply_markup=Mkp([[B("🤖 ربات من","my_bots")]]))
        except: pass
        return

    if d.startswith("issue_token_confirm_"):
        tid = int(d[len("issue_token_confirm_"):]); info = users.get(tid,{"name":str(tid)})
        t = new_token(tid)
        await q.message.reply_text(f"✅ توکن `{t}` صادر شد.", parse_mode="Markdown")
        try: await ctx.bot.send_message(tid, f"🎉 توکن: `{t}`", parse_mode="Markdown")
        except: pass
        return

    if d == "list_all_tokens":
        if not tokens: await q.message.reply_text("🔑 توکنی صادر نشده."); return
        txt = "📋 *همه توکن‌ها:*\n\n"+"".join(f"🔑 `{t}`\n👤 {users.get(td['uid'],{}).get('name',td['uid'])} | {'✅ @'+td['bot'] if td.get('used') else '⏳'}\n\n" for t,td in tokens.items())
        await q.message.reply_text(txt, parse_mode="Markdown", reply_markup=Mkp([[back("manage_tokens")]])); return

    if d.startswith("full_profile_"):
        tid = int(d[len("full_profile_"):]); 
        await q.message.reply_text(profile_txt(tid), parse_mode="Markdown",
            reply_markup=Mkp([[B("↩️ پاسخ",f"reply_{tid}")],[B("📝 یادداشت",f"set_note_{tid}")],[B("🤖 توکن جدید",f"issue_token_{tid}")],[B("🚫 بلاک" if tid not in blocked else "✅ آنبلاک",f"{'block' if tid not in blocked else 'unblock'}_{tid}")],[back("list_users")]])); return

    if d.startswith("set_note_"):
        tid = int(d[len("set_note_"):]); note_inp[ADMIN]=tid
        await q.message.reply_text(f"📝 یادداشت جدید برای {users.get(tid,{}).get('name',tid)} رو بنویس\n(یا بفرست 'حذف'):", parse_mode="Markdown"); return

# ── admin text handler ────────────────────────────────────────────────────────
async def admin_text(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cid = u.effective_chat.id
    if u.effective_chat.type != "private": return
    if cid != ADMIN: await forward_message(u, ctx); return
    txt = u.message.text

    if ADMIN in note_inp:
        tid = note_inp.pop(ADMIN); p = ep(tid)
        p["note"] = "" if txt.strip()=="حذف" else txt.strip()
        await u.message.reply_text("🗑 یادداشت حذف شد." if txt.strip()=="حذف" else f"📝 ذخیره شد: {txt.strip()}"); return

    pc = ctx.bot_data.get("pending_card")
    if pc == "number":
        d2 = txt.strip().replace("-","").replace(" ","")
        if not d2.isdigit() or len(d2)!=16: await u.message.reply_text("❌ ۱۶ رقم بفرست."); return
        cfg["card_number"] = "-".join([d2[i:i+4] for i in range(0,16,4)]); ctx.bot_data["pending_card"]="owner"
        await u.message.reply_text(f"✅ `{cfg['card_number']}`\n\nحالا نام صاحب کارت:", parse_mode="Markdown"); return
    if pc == "owner":
        cfg["card_owner"]=txt.strip(); ctx.bot_data.pop("pending_card",None)
        await u.message.reply_text(f"✅ کارت بروز شد!\n`{cfg['card_number']}`\n{cfg['card_owner']}", parse_mode="Markdown", reply_markup=admin_kb()); return

    if ADMIN in coin_inp:
        tid = coin_inp.pop(ADMIN)
        try: n = int(txt.strip())
        except: await u.message.reply_text("❌ فقط عدد بفرست."); return
        nb = ac(tid, n, "تغییر ادمین"); info = users.get(tid,{"name":str(tid)})
        await u.message.reply_text(f"✅ موجودی {info['name']}: {'+' if n>=0 else ''}{n} → {nb} سکه", parse_mode="Markdown")
        try: await ctx.bot.send_message(tid, f"💰 موجودی تغییر کرد!\n{'➕' if n>=0 else '➖'} {abs(n)} سکه\nموجودی جدید: {nb}", parse_mode="Markdown")
        except: pass
        return

    if ADMIN in poll_q:
        info = poll_q[ADMIN]; step = info.get("step")
        if step=="question": info["question"]=txt; info["step"]="options"; info["options"]=[]; await u.message.reply_text("📝 گزینه‌ها رو یکی‌یکی بفرست. وقتی تموم شد بنویس *تمام*", parse_mode="Markdown"); return
        if step=="options":
            if txt.strip()=="تمام":
                if len(info["options"])<2: await u.message.reply_text("❌ حداقل ۲ گزینه."); return
                info["step"]="target"; prev="\n".join(f"• {o}" for o in info["options"])
                await u.message.reply_text(f"🗳 پیش‌نمایش:\n\n❓ {info['question']}\n\n{prev}\n\nکجا ارسال شه؟", parse_mode="Markdown",
                    reply_markup=Mkp([[B("👥 همه کاربران","poll_target_all")],[B("👥 یک گروه","poll_target_group")]])); return
            info["options"].append(txt.strip()); await u.message.reply_text(f"✅ گزینه اضافه شد ({len(info['options'])}). بعدی یا *تمام*", parse_mode="Markdown"); return
        if step=="waiting_group_id":
            try: gid=int(txt.strip())
            except: await u.message.reply_text("❌ آیدی باید عدد باشه."); return
            n = await send_poll(ctx, info, gid); del poll_q[ADMIN]
            await u.message.reply_text("✅ نظرسنجی ارسال شد." if n else "❌ ارسال ناموفق."); return

    if group_mode.get(ADMIN)=="waiting_id":
        try: group_mode[ADMIN]=int(txt.strip()); await u.message.reply_text(f"✅ آیدی: `{group_mode[ADMIN]}`\n\nحالا پیام رو بنویس:", parse_mode="Markdown")
        except: await u.message.reply_text("❌ آیدی باید عدد باشه.")
        return
    if isinstance(group_mode.get(ADMIN), int):
        gid = group_mode.pop(ADMIN)
        try: await ctx.bot.send_message(gid, txt); await u.message.reply_text("✅ ارسال شد!")
        except Exception as e: await u.message.reply_text(f"❌ خطا:\n{e}")
        return

    if reply_to.get(ADMIN)=="broadcast":
        del reply_to[ADMIN]; n=0
        for uid in users:
            if uid not in blocked:
                try: await ctx.bot.send_message(uid, f"📢 *پیام از ادمین:*\n\n{txt}", parse_mode="Markdown"); n+=1
                except: pass
        await u.message.reply_text(f"✅ ارسال به {n} کاربر."); return

    if ADMIN in reply_to:
        tid = reply_to.pop(ADMIN)
        try:
            await ctx.bot.send_message(tid, f"📨 *پیام از ادمین:*\n\n{txt}", parse_mode="Markdown")
            mid = msg_map.get(f"reply_{tid}")
            await (ctx.bot.send_message(ADMIN,"✅ پیام ارسال شد.",reply_to_message_id=mid) if mid else u.message.reply_text("✅ پیام ارسال شد."))
        except: await u.message.reply_text("❌ ارسال ناموفق.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.TEXT, forward_message))
    print("✅ ربات روشن شد!")
    app.run_polling(allowed_updates=["message","callback_query","poll_answer"])

if __name__ == "__main__":
    main()
PYEOF
wc -l /mnt/user-data/outputs/telegram_bot/bot.py
