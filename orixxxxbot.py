import logging
import os
import sqlite3
import json
import csv
import io
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8904443123:AAFJhOAE7a_yMB3KDB1mwDAZDfED7o6vi8I"
ADMIN_CHAT_ID = 5244281514
CHANNEL_LINK = "https://t.me/orix_global_agency"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads.db")

(Q1, Q2, Q3, Q4, NAME) = range(5)

LEAD_MAGNETS = {
    "topuni":  {"label": "🎓 TOP Universitetlar Qo'llanmasi"},
    "snu":     {"label": "🏛 Seoul National University Qo'llanmasi"},
    "gks":     {"label": "📘 GKS Grant Qo'llanmasi"},
    "topik":   {"label": "📗 TOPIK Tayyorgarlik Qo'llanmasi"},
    "default": {"label": "📖 Bepul Qo'llanma"},
}

QUESTIONS = {
    Q1: {
        "text": "Koreya universitetiga kirishga tayyorgarlikda hozirda qayerdasiz?",
        "options": [
            ("🔹 Sertifikatga hali topshirmaganman", "q1_a"),
            ("🔹 TOPIK yoki IELTS bor, hujjat kerak", "q1_b"),
            ("🔹 Universitet tanlangan, viza/hujjat kerak", "q1_c"),
        ]
    },
    Q2: {
        "text": "Koreya universitetiga hujjat topshirishda sizni eng ko'p nima qiynayapti?",
        "options": [
            ("🔹 Grant yuta olishim mumkinmi?", "q2_a"),
            ("🔹 Hujjat va viza jarayonining to'g'riligi", "q2_b"),
            ("🔹 To'g'ri universitet va yo'nalish tanlash", "q2_c"),
            ("🔹 Til darajam yetarli ekanligini bilmaslik", "q2_d"),
        ]
    },
    Q3: {
        "text": "Koreyadagi o'qishingizdan qanday natijani ideal deb hisoblaysiz?",
        "options": [
            ("🔹 Nufuzli universitet + to'liq grant (GKS)", "q3_a"),
            ("🔹 Grant bo'lmasa ham SKY universitetlari", "q3_b"),
        ]
    },
    Q4: {
        "text": "Universitetni bitirgandan keyin asosiy rejaingiz nima?",
        "options": [
            ("🔹 Koreyada nufuzli kompaniyada ishlash", "q4_a"),
            ("🔹 O'zbekistonga qaytib biznes yoki karyera", "q4_b"),
            ("🔹 O'qish davomida qonuniy ravishda ishlash", "q4_c"),
        ]
    },
}

ANSWER_LABELS = {
    "q1_a": "Sertifikatga hali topshirmaganman",
    "q1_b": "TOPIK/IELTS bor, hujjat kerak",
    "q1_c": "Universitet tanlangan, viza/hujjat kerak",
    "q2_a": "Grant yuta olishim mumkinmi?",
    "q2_b": "Hujjat va viza kafolati",
    "q2_c": "To'g'ri universitet/yo'nalish tanlash",
    "q2_d": "Til darajam yetarliligini bilmaslik",
    "q3_a": "Nufuzli universitet + to'liq grant (GKS)",
    "q3_b": "Grant bo'lmasa ham SKY universitetlari",
    "q4_a": "Koreyada nufuzli kompaniyada ishlash",
    "q4_b": "O'zbekistonga qaytib biznes/karyera",
    "q4_c": "O'qish davomida qonuniy ishlash",
}


# ─── Database ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            name TEXT,
            answers TEXT,
            lead_magnet TEXT DEFAULT 'default',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS starts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            username TEXT,
            lead_magnet TEXT DEFAULT 'default',
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
    conn.close()


def record_start(telegram_id, username, lead_magnet):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO starts (telegram_id, username, lead_magnet) VALUES (?, ?, ?)",
        (telegram_id, username or "", lead_magnet)
    )
    conn.commit()
    conn.close()


def save_lead(telegram_id, username, name, answers, lead_magnet):
    conn = sqlite3.connect(DB_PATH)
    # Bir xil foydalanuvchi qayta topshirsa — yangilaydi, takrorlanmaydi
    conn.execute("""
        INSERT INTO leads (telegram_id, username, name, answers, lead_magnet)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            username=excluded.username,
            name=excluded.name,
            answers=excluded.answers,
            lead_magnet=excluded.lead_magnet,
            created_at=datetime('now','localtime')
    """, (telegram_id, username or "", name, json.dumps(answers, ensure_ascii=False), lead_magnet))
    conn.commit()
    conn.close()


def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT telegram_id FROM leads").fetchall()
    conn.close()
    return [row[0] for row in rows]


def get_stats():
    conn = sqlite3.connect(DB_PATH)
    total_leads  = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    today_leads  = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE DATE(created_at) = DATE('now','localtime')"
    ).fetchone()[0]
    total_starts = conn.execute("SELECT COUNT(*) FROM starts").fetchone()[0]
    today_starts = conn.execute(
        "SELECT COUNT(*) FROM starts WHERE DATE(created_at) = DATE('now','localtime')"
    ).fetchone()[0]
    by_magnet = conn.execute(
        "SELECT lead_magnet, COUNT(*) FROM starts GROUP BY lead_magnet ORDER BY COUNT(*) DESC"
    ).fetchall()
    by_magnet_leads = conn.execute(
        "SELECT lead_magnet, COUNT(*) FROM leads GROUP BY lead_magnet ORDER BY COUNT(*) DESC"
    ).fetchall()
    conversion = round(total_leads / total_starts * 100, 1) if total_starts > 0 else 0
    conn.close()
    return total_leads, today_leads, total_starts, today_starts, by_magnet, by_magnet_leads, conversion


def get_recent_leads(limit=20):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT name, username, lead_magnet, created_at FROM leads ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_all_leads_csv():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, name, username, telegram_id, lead_magnet, answers, created_at FROM leads ORDER BY id DESC"
    ).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Ism", "Username", "TG ID", "Segment", "Javoblar", "Sana"])
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def get_usernames():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT username, name, lead_magnet, created_at FROM leads "
        "WHERE username IS NOT NULL AND username != '' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows


# ─── Helpers ───────────────────────────────────────────────────────────────────

def get_keyboard(options):
    return InlineKeyboardMarkup([[InlineKeyboardButton(l, callback_data=d)] for l, d in options])


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_CHAT_ID


# ─── Bot handlers ──────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["answers"] = {}

    lead_magnet = "default"
    if context.args:
        slug = context.args[0].lower()
        if slug in LEAD_MAGNETS:
            lead_magnet = slug
    context.user_data["lead_magnet"] = lead_magnet

    user = update.effective_user
    record_start(user.id, user.username, lead_magnet)

    await update.message.reply_text(
        "🇰🇷 Xush kelibsiz!\n\nBir necha savol — 1 daqiqa vaqt oladi. Boshlaylik! 👇"
    )

    video_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "welcome.mp4")
    if os.path.exists(video_path):
        try:
            with open(video_path, "rb") as vf:
                await update.message.reply_video_note(video_note=vf)
        except Exception as e:
            logger.warning(f"Video yuborishda xatolik: {e}")

    q = QUESTIONS[Q1]
    await update.message.reply_text(q["text"], reply_markup=get_keyboard(q["options"]))
    return Q1


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, next_state, next_q_key=None):
    query = update.callback_query
    await query.answer()
    context.user_data["answers"][query.data.split("_")[0]] = query.data

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if next_q_key is not None:
        q = QUESTIONS[next_q_key]
        await query.message.reply_text(q["text"], reply_markup=get_keyboard(q["options"]))
        return next_state

    await query.message.reply_text("Zo'r! Oxirgi savol — ismingizni kiriting ✍️")
    return NAME


async def q1_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, Q2, Q2)

async def q2_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, Q3, Q3)

async def q3_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, Q4, Q4)

async def q4_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_answer(update, context, NAME, None)


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("❗ To'liq ismingizni kiriting, iltimos.")
        return NAME
    context.user_data["name"] = name

    user = update.effective_user
    data = context.user_data
    lead_magnet = data.get("lead_magnet", "default")
    answers = data.get("answers", {})

    answers_text = ""
    for q_key, ans_key in sorted(answers.items()):
        label = ANSWER_LABELS.get(ans_key, ans_key)
        answers_text += f"  {q_key.upper()}: {label}\n"

    tg_link = f"@{user.username}" if user.username else f"ID: {user.id}"
    lm_label = LEAD_MAGNETS.get(lead_magnet, LEAD_MAGNETS["default"])["label"]

    admin_msg = (
        f"🆕 *YANGI LEAD*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Ism:* {name}\n"
        f"🔗 *Telegram:* {tg_link}\n"
        f"🎯 *Segment:* {lm_label}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Javoblar:*\n{answers_text}"
    )

    try:
        save_lead(user.id, user.username, name, answers, lead_magnet)
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_msg, parse_mode="Markdown")
        logger.info(f"Lead saqlandi: {name} / {tg_link} / {lead_magnet}")
    except Exception as e:
        logger.error(f"Lead saqlashda xatolik: {e}")

    final_msg = (
        f"🎉 Rahmat, {name}!\n\n"
        "So'rovnomani muvaffaqiyatli yakunladingiz.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📌 Va'da qilingan qo'llanma kanalimizda PIN xabarda joylashtirilgan.\n\n"
        f"👉 Kanalga o'tish va qo'llanmani olish: {CHANNEL_LINK}\n\n"
        "Kanalda siz uchun:\n"
        "• 📖 Bepul qo'llanma — PIN xabarda\n"
        "• 🎓 O'zbek talabalar tajribalari\n"
        "• 💰 GKS grant yangiliklari\n"
        "• 📋 Hujjat topshirish bo'yicha bepul materiallar"
    )
    await update.message.reply_text(final_msg)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("So'rovnoma to'xtatildi. Qayta boshlash uchun /start ni bosing.")
    return ConversationHandler.END


# ─── Admin buyruqlari ───────────────────────────────────────────────────────────

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ishlatilishi: /broadcast Salom! Yangilik bor...
    Bot barcha leadlarga o'sha xabarni yuboradi.
    """
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "❗ Xabar matni kiriting.\n\nMisol:\n/broadcast Salom! Yangi vebinar bo'ladi 27-iyunda..."
        )
        return

    text = " ".join(context.args)
    user_ids = get_all_user_ids()

    if not user_ids:
        await update.message.reply_text("Hali hech qanday foydalanuvchi yo'q.")
        return

    status_msg = await update.message.reply_text(f"📤 Xabar {len(user_ids)} ta foydalanuvchiga yuborilmoqda...")

    success = 0
    failed = 0

    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id, text=text)
            success += 1
            await asyncio.sleep(0.05)  # Telegram spam limitidan oshmaslik uchun
        except Exception as e:
            failed += 1
            logger.warning(f"Xabar yuborilmadi {user_id}: {e}")

    await status_msg.edit_text(
        f"✅ Broadcast tugadi!\n\n"
        f"📨 Yuborildi: {success} ta\n"
        f"❌ Yuborilmadi: {failed} ta\n"
        f"(Bot ni bloklagan yoki o'chirgan foydalanuvchilar — yuborilmadi)"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    total_leads, today_leads, total_starts, today_starts, by_magnet, by_magnet_leads, conversion = get_stats()

    start_lines = ""
    for magnet, count in by_magnet:
        label = LEAD_MAGNETS.get(magnet, LEAD_MAGNETS["default"])["label"]
        start_lines += f"  • {label}: *{count}* ta\n"

    lead_lines = ""
    for magnet, count in by_magnet_leads:
        label = LEAD_MAGNETS.get(magnet, LEAD_MAGNETS["default"])["label"]
        lead_lines += f"  • {label}: *{count}* ta\n"

    empty = "  Hali yo'q"
    msg = (
        f"📊 *Statistika*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👆 /start bosildi: *{total_starts}* ta  _(bugun: {today_starts})_\n"
        f"📥 Leadlar: *{total_leads}* ta  _(bugun: {today_leads})_\n"
        f"📈 Konversiya: *{conversion}%*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Segment bo'yicha (start):*\n{start_lines or empty}\n"
        f"📥 *Segment bo'yicha (lead):*\n{lead_lines or empty}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    rows = get_recent_leads(20)
    if not rows:
        await update.message.reply_text("Hali hech qanday lead yo'q.")
        return
    lines = []
    for i, (name, username, lead_magnet, created_at) in enumerate(rows, 1):
        tg = f"@{username}" if username else "—"
        date = created_at[:10] if created_at else "—"
        seg = LEAD_MAGNETS.get(lead_magnet, LEAD_MAGNETS["default"])["label"].split()[1]
        lines.append(f"{i}. {name} | {tg} | {seg} | {date}")
    msg = "📋 So'nggi 20 lead:\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines)
    await update.message.reply_text(msg)


async def cmd_usernames(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    rows = get_usernames()
    if not rows:
        await update.message.reply_text("Username'li foydalanuvchilar yo'q.")
        return
    lines = [
        f"@{u} — {name} | {LEAD_MAGNETS.get(lm, LEAD_MAGNETS['default'])['label'].split()[1]} | {date[:10]}"
        for u, name, lm, date in rows
    ]
    msg = f"👥 Telegram username'lar ({len(rows)} ta):\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines)
    await update.message.reply_text(msg)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    csv_bytes = get_all_leads_csv()
    now = datetime.now().strftime("%Y%m%d_%H%M")
    await update.message.reply_document(
        document=csv_bytes,
        filename=f"leads_{now}.csv",
        caption=f"📂 Barcha leadlar — {now}"
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    me = await context.bot.get_me()
    username = me.username
    base = f"https://t.me/{username}?start="
    msg = (
        "🛠 *Admin panel — buyruqlar:*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "/stats — Statistika\n"
        "/leads — So'nggi 20 lead\n"
        "/usernames — Telegram username'lar\n"
        "/export — Barcha leadlar CSV\n"
        "/broadcast [matn] — Hammaga xabar yuborish\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "*Segment deep linklar (reklamaga joylashtiring):*\n\n"
        f"🎓 TOP Universitetlar:\n`{base}topuni`\n\n"
        f"🏛 Seoul National University:\n`{base}snu`\n\n"
        f"📘 GKS Grant:\n`{base}gks`\n\n"
        f"📗 TOPIK:\n`{base}topik`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .build()
    )

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            Q1:   [CallbackQueryHandler(q1_handler, pattern="^q1_")],
            Q2:   [CallbackQueryHandler(q2_handler, pattern="^q2_")],
            Q3:   [CallbackQueryHandler(q3_handler, pattern="^q3_")],
            Q4:   [CallbackQueryHandler(q4_handler, pattern="^q4_")],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("admin",     cmd_admin))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("leads",     cmd_leads))
    app.add_handler(CommandHandler("usernames", cmd_usernames))
    app.add_handler(CommandHandler("export",    cmd_export))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    logger.info("Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
