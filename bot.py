import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "@your_admin")
CITY = os.getenv("CITY", "Dhaka")
COUNTRY = os.getenv("COUNTRY", "Bangladesh")
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dhaka"))

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

logging.basicConfig(level=logging.INFO)
app = FastAPI()
bot_app = Application.builder().token(TOKEN).build()

MENU = [
    [("🎵 গান", "songs"), ("🎬 নাটক", "drama")],
    [("💃 নাচ", "dance"), ("✍️ ক্যাপশন", "caption")],
    [("🕌 আজানের সময়", "prayer"), ("❓ সাহায্য", "help")],
    [("👨‍💻 অ্যাডমিন", "admin"), ("⏰ সময়", "time")],
]

def keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in MENU]
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🤖 হ্যালো! আমি তোমাদের গ্রুপ সহকারী।\n\n"
        "নিচের মেনু থেকে বেছে নাও, অথবা সরাসরি লিখো—“গান দাও”, “নাটক চাই”, "
        "“ক্যাপশন দাও”, “সাহায্য” ইত্যাদি।",
        reply_markup=keyboard()
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "❓ আমি যা করতে পারি:\n"
        "🎵 গান — গানের তালিকা/লিংক\n"
        "🎬 নাটক — নাটকের তালিকা/লিংক\n"
        "💃 নাচ — কনটেন্ট/লিংক\n"
        "✍️ ক্যাপশন — ক্যাপশন\n"
        "🕌 আজানের সময় — আজকের নামাজের সময়\n"
        "🌅 সকাল/🌙 রাতের শুভেচ্ছা\n"
        "👨‍💻 অ্যাডমিন — যোগাযোগ\n"
        "⏰ বর্তমান সময়\n\n"
        "উদাহরণ: “একটা গান দাও”, “নাটক চাই”, “একটা ক্যাপশন দাও”"
    )

async def prayer_times():
    url = "https://api.aladhan.com/v1/timingsByCity"
    params = {"city": CITY, "country": COUNTRY, "method": 1}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()["data"]
        t = data["timings"]
        return (
            f"🕌 আজকের নামাজের সময় — {CITY}\n\n"
            f"ফজর: {t['Fajr']}\n"
            f"যোহর: {t['Dhuhr']}\n"
            f"আসর: {t['Asr']}\n"
            f"মাগরিব: {t['Maghrib']}\n"
            f"এশা: {t['Isha']}"
        )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == "songs":
        text = "🎵 গান\n\nএখানে তোমার পছন্দের গান/বৈধ ভিডিও লিংকগুলো পরে যোগ করা যাবে।\n\nলিখতে পারো: “গান দাও”"
    elif d == "drama":
        text = "🎬 নাটক\n\nএখানে তোমার দেওয়া নাটকের তালিকা ও বৈধ লিংক যোগ করা যাবে।"
    elif d == "dance":
        text = "💃 নাচ\n\nএখানে তোমার দেওয়া নাচের কনটেন্ট/বৈধ লিংক যোগ করা যাবে।"
    elif d == "caption":
        text = "✍️ ক্যাপশন\n\n❤️ ভালোবাসা\n😢 কষ্ট\n😎 Attitude\n🤲 ইসলামিক\n😂 মজার\n\nযে ধরনের ক্যাপশন চাও লিখে দাও।"
    elif d == "prayer":
        try:
            text = await prayer_times()
        except Exception:
            text = "🕌 আজানের সময় আনতে এখন সমস্যা হচ্ছে। একটু পরে আবার চেষ্টা করো।"
    elif d == "help":
        text = "❓ সাহায্যের জন্য /help লিখো। সমস্যা হলে 👨‍💻 অ্যাডমিন অপশন ব্যবহার করো।"
    elif d == "admin":
        text = f"👨‍💻 অ্যাডমিনের সাথে যোগাযোগ:\n{ADMIN_CONTACT}"
    elif d == "time":
        now = datetime.now(TZ).strftime("%I:%M:%S %p")
        text = f"⏰ এখন সময়: {now}"
    else:
        text = "🤖 অপশনটি পাওয়া যায়নি।"

    await q.message.reply_text(text, reply_markup=keyboard())

async def message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.effective_message.text or "").strip().lower()
    if not text:
        return

    if any(x in text for x in ["হাই", "হ্যালো", "hello", "hi", "সালাম", "আসসালামু"]):
        await update.effective_message.reply_text(
            "👋 হ্যালো! কেমন আছো? কী লাগবে বলো।", reply_markup=keyboard()
        )
    elif "গান" in text:
        await update.effective_message.reply_text(
            "🎵 গান চাই? তোমার পছন্দের গানের নাম লিখে দাও।\n"
            "অ্যাডমিন চাইলে পরে এখানে বৈধ গানের লিংক যোগ করতে পারবে।"
        )
    elif "নাটক" in text:
        await update.effective_message.reply_text(
            "🎬 কোন নাটক চাই? নাটকের নাম লিখে দাও।"
        )
    elif "নাচ" in text:
        await update.effective_message.reply_text(
            "💃 নাচের কনটেন্ট চাইলে নাম/বিষয় লিখে দাও।"
        )
    elif "ক্যাপশন" in text:
        await update.effective_message.reply_text(
            "✍️ কী ধরনের ক্যাপশন চাই?\n❤️ ভালোবাসা | 😢 কষ্ট | 😎 Attitude | 🤲 ইসলামিক"
        )
    elif any(x in text for x in ["সাহায্য", "help", "হেল্প"]):
        await help_cmd(update, context)
    elif "অ্যাডমিন" in text or "admin" in text:
        await update.effective_message.reply_text(f"👨‍💻 অ্যাডমিন: {ADMIN_CONTACT}")
    elif "আজান" in text or "নামাজের সময়" in text:
        try:
            await update.effective_message.reply_text(await prayer_times())
        except Exception:
            await update.effective_message.reply_text("🕌 আজানের সময় আনতে সমস্যা হচ্ছে।")
    elif "সময়" in text or "কয়টা বাজে" in text:
        now = datetime.now(TZ).strftime("%I:%M %p")
        await update.effective_message.reply_text(f"⏰ এখন সময়: {now}")
    elif "শুভ রাত্রি" in text or "good night" in text:
        await update.effective_message.reply_text("🌙 Good Night! সুন্দর ঘুম হোক।")
    elif "good morning" in text or "শুভ সকাল" in text:
        await update.effective_message.reply_text("🌅 Good Morning! সুন্দর একটি দিন হোক।")
    else:
        await update.effective_message.reply_text(
            "🤖 বুঝেছি। আরও একটু বিস্তারিত লিখো, অথবা নিচের মেনু থেকে একটি অপশন বেছে নাও।",
            reply_markup=keyboard()
        )

async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.process_update(update)
    return {"ok": True}

@app.get("/")
async def home():
    return {"status": "ok", "bot": "Telegram Group Assistant"}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    return await webhook(request)

bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(CommandHandler("help", help_cmd))
bot_app.add_handler(CallbackQueryHandler(button))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message))

@app.on_event("startup")
async def startup():
    await bot_app.initialize()
    await bot_app.start()

@app.on_event("shutdown")
async def shutdown():
    await bot_app.stop()
    await bot_app.shutdown()
