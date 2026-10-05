#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram AI Assistant & Media Bot - OpenAI Only
Admin: @tomalchowdhury2 (ID: 8721334265)

Kept features:
- OpenAI AI replies
- Admin media upload -> title -> SQLite save
- Drama/song/video search and delivery
- Admin alerts
- Weather and prayer times
- Admin commands: /start /help /contact /admin /list /delete /stats

Added:
- Better group-message handling/logging
- Removes any old Telegram webhook before polling
- Saves groups when the bot is added
- Hourly automatic reminders
- Exact prayer-time automatic reminders
- Study, sports and sleep reminders
- /auto_on and /auto_off per chat

Automatic schedule is configurable with environment variables:
AUTO_MESSAGES_ENABLED=true
STUDY_HOURS=7,10,15,19
SPORTS_HOURS=17,21
SLEEP_HOUR=23
"""

import os
import re
import time
import asyncio
import logging
import sqlite3
import traceback
from datetime import datetime

import pytz
import aiohttp
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")

ADMIN_IDS = [8721334265]
ADMIN_USERNAME = "tomalchowdhury2"

TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Dhaka")
try:
    TZ = pytz.timezone(TIMEZONE_NAME)
except Exception:
    TZ = pytz.timezone("Asia/Dhaka")

PRAYER_CITY = os.getenv("PRAYER_CITY", "Dhaka")
PRAYER_COUNTRY = os.getenv("PRAYER_COUNTRY", "Bangladesh")
PRAYER_METHOD = os.getenv("PRAYER_METHOD", "1")
DB_FILE = os.getenv("DB_FILE", "bot_database.db")

AUTO_MESSAGES_ENABLED = os.getenv("AUTO_MESSAGES_ENABLED", "true").lower() in {
    "1", "true", "yes", "on"
}


def parse_hours(value, default):
    result = []
    for item in value.split(",") if value else []:
        try:
            h = int(item.strip())
            if 0 <= h <= 23:
                result.append(h)
        except ValueError:
            pass
    return sorted(set(result)) or default


STUDY_HOURS = parse_hours(os.getenv("STUDY_HOURS", "7,10,15,19"), [7, 10, 15, 19])
SPORTS_HOURS = parse_hours(os.getenv("SPORTS_HOURS", "17,21"), [17, 21])
SLEEP_HOUR = int(os.getenv("SLEEP_HOUR", "23"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_bot")

# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import AsyncOpenAI
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client configured successfully. Key=SET")
    except Exception as e:
        logger.warning("Could not initialize OpenAI client: %s", e)
else:
    logger.warning("OPENAI_API_KEY is missing. AI fallback will be used.")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(query, params=(), fetchone=False, fetch=False, commit=True):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        if commit:
            conn.commit()
        if fetchone:
            row = cur.fetchone()
            return dict(row) if row else None
        if fetch:
            return [dict(r) for r in cur.fetchall()]
        return cur.lastrowid


def init_db():
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                joined_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT,
                title TEXT,
                username TEXT,
                created_at TEXT,
                notification_enabled INTEGER DEFAULT 1
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                category TEXT DEFAULT 'other',
                views INTEGER DEFAULT 0,
                added_by INTEGER,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Backward compatibility with the user's existing DB.
        cur.execute("PRAGMA table_info(contents)")
        content_cols = [c[1] for c in cur.fetchall()]
        if "views" not in content_cols:
            cur.execute("ALTER TABLE contents ADD COLUMN views INTEGER DEFAULT 0")

        cur.execute("PRAGMA table_info(chats)")
        chat_cols = [c[1] for c in cur.fetchall()]
        if "notification_enabled" not in chat_cols:
            cur.execute(
                "ALTER TABLE chats ADD COLUMN notification_enabled INTEGER DEFAULT 1"
            )
        conn.commit()
    logger.info("Database initialized.")


def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def save_user(user):
    if not user:
        return
    db_execute("""
        INSERT INTO users(user_id, first_name, last_name, username, joined_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            username=excluded.username
    """, (user.id, user.first_name or "", user.last_name or "",
          user.username or "", now_str()))


def save_chat(chat):
    if not chat:
        return
    db_execute("""
        INSERT INTO chats(chat_id, chat_type, title, username, created_at, notification_enabled)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(chat_id) DO UPDATE SET
            chat_type=excluded.chat_type,
            title=excluded.title,
            username=excluded.username
    """, (chat.id, chat.type, chat.title or "", chat.username or "", now_str()))


def set_chat_notifications(chat_id, enabled):
    db_execute(
        "UPDATE chats SET notification_enabled=? WHERE chat_id=?",
        (1 if enabled else 0, chat_id),
    )


def get_notification_chats():
    return db_execute("""
        SELECT chat_id, chat_type, title
        FROM chats
        WHERE notification_enabled=1
        ORDER BY chat_id
    """, fetch=True)


def save_message(chat_id, user_id, role, content):
    db_execute("""
        INSERT INTO messages(chat_id, user_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, user_id, role, content, now_str()))


def get_history(chat_id, limit=8):
    rows = db_execute("""
        SELECT role, content FROM messages
        WHERE chat_id=? ORDER BY id DESC LIMIT ?
    """, (chat_id, limit), fetch=True)
    return rows[::-1] if rows else []


def get_state(key):
    row = db_execute("SELECT value FROM bot_state WHERE key=?", (key,), fetchone=True)
    return row["value"] if row else None


def set_state(key, value):
    db_execute("""
        INSERT INTO bot_state(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

user_last_action = {}


def check_rate_limit(user_id, interval=1.0):
    current = time.time()
    last = user_last_action.get(user_id, 0)
    if current - last < interval:
        return False
    user_last_action[user_id] = current
    return True


def is_admin(user_id):
    return user_id in ADMIN_IDS


def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^\w\s\u0980-\u09FF]", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# ---------------------------------------------------------------------------
# Content search
# ---------------------------------------------------------------------------

def detect_category(title):
    t = normalize_text(title)
    if any(x in t for x in ["নাটক", "drama", "natok"]):
        return "drama"
    if any(x in t for x in ["গান", "song", "audio", "গজল", "music"]):
        return "song"
    if any(x in t for x in ["মুভি", "movie", "cinema", "ফিল্ম"]):
        return "movie"
    if any(x in t for x in ["ডান্স", "dance"]):
        return "dance"
    if any(x in t for x in ["ছবি", "photo", "pic"]):
        return "photo"
    return "video"


def search_content(query, category=None):
    query = normalize_text(query)
    if not query:
        return None
    if category:
        row = db_execute("""
            SELECT * FROM contents
            WHERE category=? AND lower(title) LIKE ?
            ORDER BY views DESC, id DESC LIMIT 1
        """, (category, f"%{query}%"), fetchone=True)
        if row:
            return row

    row = db_execute("""
        SELECT * FROM contents
        WHERE lower(title) LIKE ?
        ORDER BY views DESC, id DESC LIMIT 1
    """, (f"%{query}%",), fetchone=True)
    if row:
        return row

    words = [w for w in query.split() if len(w) >= 2][:4]
    if not words:
        return None
    conds = ["lower(title) LIKE ?" for _ in words]
    params = [f"%{w}%" for w in words]
    if category:
        sql = (
            "SELECT * FROM contents WHERE category=? AND (" +
            " OR ".join(conds) + ") ORDER BY views DESC, id DESC LIMIT 1"
        )
        return db_execute(sql, (category, *params), fetchone=True)
    sql = (
        "SELECT * FROM contents WHERE (" + " OR ".join(conds) +
        ") ORDER BY views DESC, id DESC LIMIT 1"
    )
    return db_execute(sql, tuple(params), fetchone=True)


def increment_views(content_id):
    db_execute("UPDATE contents SET views=views+1 WHERE id=?", (content_id,))


def get_contents_by_category(category, limit=5):
    return db_execute("""
        SELECT id,title,media_type,category,views FROM contents
        WHERE category=? ORDER BY views DESC,id DESC LIMIT ?
    """, (category, limit), fetch=True)


def get_top_trending(limit=5):
    return db_execute("""
        SELECT id,title,media_type,category,views FROM contents
        ORDER BY views DESC,id DESC LIMIT ?
    """, (limit,), fetch=True)

# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS = f"""
তুমি একটি চটপটে, নির্ভুল Telegram AI সহকারী।
ব্যবহারকারীর প্রশ্নের সরাসরি ও পরিষ্কার উত্তর দেবে।
বাংলায় প্রশ্ন হলে সুন্দর বাংলায়, Banglish হলে সহজ Banglish/বাংলায়,
ইংরেজিতে প্রশ্ন হলে প্রাঞ্জল ইংরেজিতে উত্তর দেবে।
অপ্রয়োজনীয় ভূমিকা দেবে না।

প্রধান অ্যাডমিন: @{ADMIN_USERNAME}
User ID: {ADMIN_IDS[0]}

মিডিয়া সম্পর্কে মিথ্যা দাবি করবে না। বটের ডেটাবেজে থাকা ফাইলই বট পাঠাতে পারে।
"""


async def generate_chatgpt_response(chat_id, user_text):
    history = get_history(chat_id, limit=6)
    if openai_client and OPENAI_API_KEY:
        try:
            inputs = []
            for h in history:
                inputs.append({
                    "role": "assistant" if h["role"] == "assistant" else "user",
                    "content": h["content"],
                })
            inputs.append({"role": "user", "content": user_text})
            response = await asyncio.wait_for(
                openai_client.responses.create(
                    model=OPENAI_MODEL,
                    instructions=SYSTEM_INSTRUCTIONS,
                    input=inputs,
                    max_output_tokens=650,
                ),
                timeout=20.0,
            )
            answer = getattr(response, "output_text", None)
            if answer and answer.strip():
                return answer.strip()
            logger.error("OpenAI returned empty response.")
        except asyncio.TimeoutError:
            logger.error("OpenAI request timed out.")
        except Exception as e:
            logger.error("OpenAI AI error: %r", e)
    return (
        "👋 আপনার বার্তা পেয়েছি!\n\n"
        "AI উত্তর দেওয়ার জন্য OpenAI API Key সঠিকভাবে সেট করা হয়নি "
        "অথবা API request ব্যর্থ হয়েছে।\n\n"
        f"গান/নাটক খুঁজতে নাম লিখুন, অথবা অ্যাডমিন @{ADMIN_USERNAME}-এর সাথে যোগাযোগ করুন।"
    )

# ---------------------------------------------------------------------------
# Admin notifications
# ---------------------------------------------------------------------------

async def send_admin_alert(bot, text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id, text=text, parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)


async def notify_admin_missing_content(bot, user, content_type, query):
    text = (
        "📢 **[নতুন কন্টেন্টের ডিমান্ড]**\n\n"
        f"👤 **ইউজার:** {user.first_name} (@{user.username or 'নাই'})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"📁 **টাইপ:** {content_type}\n"
        f"🔍 **রিকুয়েস্ট:** `{query}`\n"
        f"⏰ **সময়:** {now_str()}\n\n"
        f"👉 @{ADMIN_USERNAME} কন্টেন্টটি আপলোড করতে পারেন।"
    )
    keyboard = None
    if user.username:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"✉️ Reply @{user.username}",
                url=f"https://t.me/{user.username}",
            )
        ]])
    await send_admin_alert(bot, text, keyboard)


async def notify_admin_user_help(bot, user, user_msg):
    text = (
        "⚠️ **[ইউজার সাহায্য চেয়েছে]**\n\n"
        f"👤 **User:** {user.first_name} (@{user.username or 'N/A'})\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"⏰ **Time:** {now_str()}\n\n"
        f"💬 **বার্তা:**\n_{user_msg}_"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "💬 সরাসরি মেসেজ দিন",
            url=(f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"),
        )
    ]])
    await send_admin_alert(bot, text, keyboard)

# ---------------------------------------------------------------------------
# Media delivery / upload
# ---------------------------------------------------------------------------

async def deliver_media(update, row):
    message = update.effective_message
    content_id = row["id"]
    media_type = row["media_type"]
    file_id = row["file_id"]
    title = row["title"]
    increment_views(content_id)

    await message.reply_text(
        f"🎬 **{title}**\n\n⏳ পাঠানো হচ্ছে, দয়া করে অপেক্ষা করুন...",
        parse_mode="Markdown",
    )
    try:
        if media_type == "video":
            await message.reply_video(video=file_id, caption=f"🎬 {title}", supports_streaming=True)
        elif media_type == "audio":
            await message.reply_audio(audio=file_id, caption=f"🎵 {title}")
        elif media_type == "photo":
            await message.reply_photo(photo=file_id, caption=f"🖼️ {title}")
        elif media_type == "animation":
            await message.reply_animation(animation=file_id, caption=f"✨ {title}")
        else:
            await message.reply_document(document=file_id, caption=f"📄 {title}")

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "💬 এডমিন: @" + ADMIN_USERNAME,
                url=f"https://t.me/{ADMIN_USERNAME}",
            )
        ]])
        await message.reply_text(
            "✅ কন্টেন্ট সফলভাবে পাঠানো হয়েছে!\nআর কোনো নাটক বা গান লাগলে নাম লিখুন। 🤝",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error("Error sending media %s: %r", content_id, e)
        await send_admin_alert(update.get_bot(), f"❌ Error sending file ID {content_id}: {e}")
        await message.reply_text("❌ ফাইলটি পাঠাতে সমস্যা হয়েছে। এডমিনকে জানানো হয়েছে।")


async def handle_admin_media_upload(update, context):
    user = update.effective_user
    message = update.effective_message
    if not user or not is_admin(user.id):
        return False

    media_type = None
    file_id = None
    if message.video:
        media_type, file_id = "video", message.video.file_id
    elif message.audio:
        media_type, file_id = "audio", message.audio.file_id
    elif message.photo:
        media_type, file_id = "photo", message.photo[-1].file_id
    elif message.document:
        media_type, file_id = "document", message.document.file_id
    elif message.animation:
        media_type, file_id = "animation", message.animation.file_id
    if not file_id:
        return False

    context.user_data["pending_media"] = {"media_type": media_type, "file_id": file_id}
    context.user_data["waiting_title"] = True
    await message.reply_text(
        f"📥 **{media_type.upper()} মিডিয়া ফাইল পেয়েছি!**\n\n"
        "📝 এই কন্টেন্টের **নাম (Title)** লিখে পাঠান।\n"
        "যেমন: `নতুন ঈদের নাটক` অথবা `বাংলা গান`",
        parse_mode="Markdown",
    )
    return True


async def handle_admin_title_save(update, context):
    user = update.effective_user
    message = update.effective_message
    if not user or not is_admin(user.id) or not context.user_data.get("waiting_title"):
        return False
    title = message.text.strip() if message.text else ""
    if not title:
        await message.reply_text("❌ Title খালি রাখা যাবে না।")
        return True
    pending = context.user_data.get("pending_media")
    if not pending:
        context.user_data["waiting_title"] = False
        return False

    category = detect_category(title)
    new_id = db_execute("""
        INSERT INTO contents(title,media_type,file_id,category,views,added_by,created_at)
        VALUES (?,?,?,?,0,?,?)
    """, (title, pending["media_type"], pending["file_id"], category, user.id, now_str()))

    context.user_data.pop("pending_media", None)
    context.user_data["waiting_title"] = False
    await message.reply_text(
        "🎉 **কন্টেন্ট সফলভাবে ডেটাবেজে সংরক্ষিত হয়েছে!**\n\n"
        f"🆔 **ID:** `{new_id}`\n"
        f"🎬 **Title:** **{title}**\n"
        f"📁 **মিডিয়া:** `{pending['media_type']}`\n"
        f"🏷️ **ক্যাটাগরি:** `{category}`",
        parse_mode="Markdown",
    )
    return True

# ---------------------------------------------------------------------------
# Weather / Prayer
# ---------------------------------------------------------------------------

async def get_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=23.8103&longitude=90.4125"
        "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
    )
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    return None
                data = await res.json()
        c = data.get("current", {})
        return (
            f"🌤️ **{PRAYER_CITY} আবহাওয়া**\n\n"
            f"🌡️ তাপমাত্রা: **{c.get('temperature_2m','?')}°C**\n"
            f"💧 আর্দ্রতা: **{c.get('relative_humidity_2m','?')}%**\n"
            f"💨 বাতাস: **{c.get('wind_speed_10m','?')} km/h**"
        )
    except Exception as e:
        logger.warning("Weather API error: %r", e)
        return None


async def get_prayer_data():
    global _prayer_cache_date, _prayer_cache_data

    today = datetime.now(TZ).strftime("%Y-%m-%d")
    if _prayer_cache_date == today and _prayer_cache_data:
        return _prayer_cache_data

    url = (
        "https://api.aladhan.com/v1/timingsByCity"
        f"?city={PRAYER_CITY}&country={PRAYER_COUNTRY}&method={PRAYER_METHOD}"
    )
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    return None
                data = await res.json()
        timings = data.get("data", {}).get("timings", {})
        if timings:
            _prayer_cache_date = today
            _prayer_cache_data = timings
        return timings
    except Exception as e:
        logger.warning("Prayer API error: %r", e)
        return None


async def get_prayer_times():
    t = await get_prayer_data()
    if not t:
        return None
    return (
        f"🕌 **{PRAYER_CITY} নামাজের সময়সূচি**\n\n"
        f"🌅 ফজর: **{t.get('Fajr','-')}**\n"
        f"☀️ সূর্যোদয়: {t.get('Sunrise','-')}\n"
        f"🕛 যোহর: **{t.get('Dhuhr','-')}**\n"
        f"🌇 আসর: **{t.get('Asr','-')}**\n"
        f"🌆 মাগরিব: **{t.get('Maghrib','-')}**\n"
        f"🌙 এশা: **{t.get('Isha','-')}**"
    )

# ---------------------------------------------------------------------------
# Automatic notifications
# ---------------------------------------------------------------------------

_prayer_cache_date = None
_prayer_cache_data = None

PRAYER_NAMES = {
    "Fajr": "ফজর",
    "Dhuhr": "যোহর",
    "Asr": "আসর",
    "Maghrib": "মাগরিব",
    "Isha": "এশা",
}


def hourly_message(hour):
    h12 = hour % 12 or 12
    ampm = "AM" if hour < 12 else "PM"
    text = f"🕐 **সময়: {h12}:00 {ampm} (বাংলাদেশ সময়)**\n\n"

    if hour in STUDY_HOURS:
        text += "📚 **পড়াশোনার সময়!**\nএখন মনোযোগ দিয়ে পড়াশোনা/স্কিল শেখার জন্য সময় দিন। 📖\n\n"
    if hour in SPORTS_HOURS:
        text += "⚽ **খেলার/ব্যায়ামের সময়!**\nকিছুক্ষণ খেলাধুলা বা শরীরচর্চা করুন। 🏃‍♂️\n\n"
    if hour == SLEEP_HOUR:
        text += "😴 **ঘুমানোর সময়!**\nসময়মতো ঘুমান, আগামী দিনের জন্য শরীর ও মনকে বিশ্রাম দিন। 🌙\n\n"
    if hour == 5:
        text += "🌅 **সুপ্রভাত!** আজকের দিনটি ভালো কাজে শুরু করুন।\n\n"
    if hour == 12:
        text += "🍚 দুপুর হয়েছে—খাওয়া, বিশ্রাম ও প্রয়োজনীয় কাজের সময় ঠিক রাখুন।\n\n"
    if hour == 18:
        text += "🌇 সন্ধ্যা হয়েছে। নামাজ ও পরিবারের জন্য কিছু সময় রাখুন।\n\n"
    if hour not in STUDY_HOURS and hour not in SPORTS_HOURS and hour != SLEEP_HOUR:
        text += "✅ আপনার কাজের তালিকা দেখে পরের এক ঘণ্টার লক্ষ্য ঠিক করুন।"
    return text


async def send_to_enabled_chats(bot, text):
    chats = get_notification_chats()
    sent = 0
    for row in chats:
        try:
            await bot.send_message(chat_id=row["chat_id"], text=text, parse_mode="Markdown")
            sent += 1
        except Exception as e:
            # Bot may have been removed/blocked. Keep DB intact for now.
            logger.warning("Auto message failed for chat %s: %s", row["chat_id"], e)
    return sent


async def send_hourly_notification(bot, now):
    key = now.strftime("%Y-%m-%d-%H")
    if get_state("last_hourly_notification") == key:
        return
    set_state("last_hourly_notification", key)
    text = hourly_message(now.hour)
    sent = await send_to_enabled_chats(bot, text)
    logger.info("Hourly notification sent to %s chats.", sent)


async def send_prayer_notifications(bot, now):
    # Check only once per minute, but allow a 2-minute window if the process starts
    # slightly late. State prevents duplicates.
    timings = await get_prayer_data()
    if not timings:
        return
    today = now.strftime("%Y-%m-%d")
    current_minutes = now.hour * 60 + now.minute
    for key, label in PRAYER_NAMES.items():
        value = timings.get(key, "")
        match = re.match(r"^(\d{1,2}):(\d{2})", str(value))
        if not match:
            continue
        target = int(match.group(1)) * 60 + int(match.group(2))
        if abs(current_minutes - target) <= 1:
            state_key = f"prayer_sent_{today}_{key}"
            if get_state(state_key) == "1":
                continue
            set_state(state_key, "1")
            text = (
                f"🕌 **{label} নামাজের সময় হয়েছে**\n\n"
                f"⏰ সময়: **{value}**\n"
                "🤲 নামাজ আদায়ের জন্য প্রস্তুত হোন।"
            )
            sent = await send_to_enabled_chats(bot, text)
            logger.info("Prayer notification %s sent to %s chats.", label, sent)


async def automatic_notification_loop(application):
    logger.info(
        "Automatic notifications started. Study=%s Sports=%s Sleep=%s",
        STUDY_HOURS, SPORTS_HOURS, SLEEP_HOUR,
    )
    while True:
        try:
            if AUTO_MESSAGES_ENABLED:
                now = datetime.now(TZ)
                if now.minute == 0:
                    await send_hourly_notification(application.bot, now)
                await send_prayer_notifications(application.bot, now)
            await asyncio.sleep(20)
        except asyncio.CancelledError:
            logger.info("Automatic notification loop stopped.")
            raise
        except Exception as e:
            logger.error("Automatic notification loop error: %r", e)
            await asyncio.sleep(20)

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start_command(update, context):
    logger.info(
        "START RECEIVED | chat_id=%s | chat_type=%s | user=%s",
        update.effective_chat.id if update.effective_chat else None,
        update.effective_chat.type if update.effective_chat else None,
        update.effective_user.username if update.effective_user else None,
    )
    user = update.effective_user
    save_user(user)
    save_chat(update.effective_chat)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 নাটক চাই", callback_data="show_dramas"),
         InlineKeyboardButton("🎵 গান চাই", callback_data="show_songs")],
        [InlineKeyboardButton("🔥 ট্রেন্ডিং", callback_data="show_trending"),
         InlineKeyboardButton("🌤️ আবহাওয়া", callback_data="show_weather")],
        [InlineKeyboardButton("👑 এডমিন: @" + ADMIN_USERNAME,
                              url=f"https://t.me/{ADMIN_USERNAME}")],
    ])
    await update.effective_message.reply_text(
        f"👋 আসসালামু আলাইকুম **{user.first_name}**!\n\n"
        "আমি আপনার **AI Telegram Bot**।\n"
        "✨ যেকোনো প্রশ্নের উত্তর দিতে পারি।\n"
        "🎬 নাটক/গান/ভিডিওর নাম লিখে খুঁজতে পারেন।\n\n"
        "💡 যা জানতে চান সরাসরি লিখুন।",
        reply_markup=keyboard, parse_mode="Markdown",
    )


async def help_command(update, context):
    await update.effective_message.reply_text(
        "📖 **বটের ব্যবহারবিধি:**\n\n"
        "1. যেকোনো প্রশ্ন লিখুন → OpenAI AI উত্তর দেবে।\n"
        "2. নাটক/গান/ভিডিওর নাম লিখুন → ডেটাবেজে থাকলে পাঠাবে।\n"
        "3. /trending → ট্রেন্ডিং কন্টেন্ট\n"
        "4. /weather → আবহাওয়া\n"
        "5. /prayer → নামাজের সময়\n"
        "6. /auto_on → এই চ্যাটে অটো নোটিফিকেশন চালু\n"
        "7. /auto_off → এই চ্যাটে অটো নোটিফিকেশন বন্ধ\n\n"
        f"👑 প্রধান অ্যাডমিন: @{ADMIN_USERNAME}",
        parse_mode="Markdown",
    )


async def contact_command(update, context):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 এডমিনকে মেসেজ দিন", url=f"https://t.me/{ADMIN_USERNAME}")
    ]])
    await update.effective_message.reply_text(
        f"👑 **এডমিন যোগাযোগ**\n\n@{ADMIN_USERNAME}\nID: `{ADMIN_IDS[0]}`",
        reply_markup=keyboard, parse_mode="Markdown",
    )


async def admin_panel_command(update, context):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ এই কমান্ডটি শুধুমাত্র এডমিনের জন্য।")
        return
    await update.effective_message.reply_text(
        f"👑 **এডমিন প্যানেল (@{ADMIN_USERNAME})**\n\n"
        "📥 ভিডিও/অডিও/ছবি পাঠান → বট Title চাইবে → DB-তে Save হবে।\n\n"
        "/list - কন্টেন্ট তালিকা\n"
        "/stats - পরিসংখ্যান\n"
        "/delete <ID> - কন্টেন্ট ডিলিট\n"
        "/auto_on / /auto_off - এই চ্যাটের অটো নোটিফিকেশন",
        parse_mode="Markdown",
    )


async def list_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    rows = db_execute("""
        SELECT id,title,media_type,category,views FROM contents
        ORDER BY id DESC LIMIT 30
    """, fetch=True)
    if not rows:
        await update.effective_message.reply_text("📭 এখনো কোনো কন্টেন্ট নেই।")
        return
    lines = ["📚 **সংরক্ষিত কন্টেন্ট:**\n"]
    for r in rows:
        lines.append(
            f"🆔 `{r['id']}` | 🎬 **{r['title']}** | "
            f"📁 {r['media_type']} | 👁️ {r['views']}"
        )
    await update.effective_message.reply_text("\n".join(lines)[:4000], parse_mode="Markdown")


async def delete_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.effective_message.reply_text("ব্যবহার: `/delete <ID>`", parse_mode="Markdown")
        return
    try:
        cid = int(context.args[0])
        db_execute("DELETE FROM contents WHERE id=?", (cid,))
        await update.effective_message.reply_text(f"✅ ID `{cid}` ডিলিট হয়েছে।", parse_mode="Markdown")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ ডিলিট করতে সমস্যা: {e}")


async def stats_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    u = db_execute("SELECT COUNT(*) c FROM users", fetchone=True)["c"]
    c = db_execute("SELECT COUNT(*) c FROM contents", fetchone=True)["c"]
    v = db_execute("SELECT SUM(views) s FROM contents", fetchone=True)["s"] or 0
    chats = db_execute("SELECT COUNT(*) c FROM chats", fetchone=True)["c"]
    await update.effective_message.reply_text(
        f"📊 **বট স্ট্যাটিস্টিক্স**\n\n👤 ইউজার: **{u}**\n"
        f"💬 চ্যাট: **{chats}**\n🎬 কন্টেন্ট: **{c}**\n👁️ ভিউ: **{v}**",
        parse_mode="Markdown",
    )


async def auto_on_command(update, context):
    save_chat(update.effective_chat)
    set_chat_notifications(update.effective_chat.id, True)
    await update.effective_message.reply_text("🔔 এই চ্যাটে অটো নোটিফিকেশন চালু হয়েছে।")


async def auto_off_command(update, context):
    save_chat(update.effective_chat)
    set_chat_notifications(update.effective_chat.id, False)
    await update.effective_message.reply_text("🔕 এই চ্যাটে অটো নোটিফিকেশন বন্ধ হয়েছে।")


async def notify_test_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.effective_message.reply_text(
        hourly_message(datetime.now(TZ).hour), parse_mode="Markdown"
    )

# ---------------------------------------------------------------------------
# Callback queries
# ---------------------------------------------------------------------------

async def handle_callback_query(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "show_dramas":
        items = get_contents_by_category("drama", 4)
        if not items:
            await query.message.reply_text("😔 কোনো নাটক ডেটাবেজে নেই।")
            return
        buttons = [[InlineKeyboardButton(f"🎬 {x['title']} ({x['views']} views)",
                                         callback_data=f"send_media_{x['id']}")] for x in items]
        await query.message.reply_text("🎬 **নাটকসমূহ:**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

    elif data == "show_songs":
        items = get_contents_by_category("song", 4)
        if not items:
            await query.message.reply_text("😔 কোনো গান ডেটাবেজে নেই।")
            return
        buttons = [[InlineKeyboardButton(f"🎵 {x['title']}", callback_data=f"send_media_{x['id']}")] for x in items]
        await query.message.reply_text("🎵 **গানসমূহ:**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

    elif data == "show_trending":
        items = get_top_trending(5)
        if not items:
            await query.message.reply_text("📭 কোনো কন্টেন্ট নেই।")
            return
        lines = ["🔥 **ট্রেন্ডিং কন্টেন্ট:**\n"]
        for i, x in enumerate(items, 1):
            lines.append(f"{i}. 🎬 **{x['title']}** — 👁️ {x['views']}")
        await query.message.reply_text("\n".join(lines), parse_mode="Markdown")

    elif data == "show_weather":
        await query.message.reply_text((await get_weather()) or "❌ আবহাওয়া তথ্য পাওয়া যায়নি।")

    elif data.startswith("send_media_"):
        try:
            cid = int(data.split("_")[-1])
        except ValueError:
            await query.message.reply_text("❌ ID সঠিক নয়।")
            return
        row = db_execute("SELECT * FROM contents WHERE id=?", (cid,), fetchone=True)
        if row:
            await deliver_media(update, row)
        else:
            await query.message.reply_text("❌ কন্টেন্ট পাওয়া যায়নি।")

# ---------------------------------------------------------------------------
# Group/member update handling
# ---------------------------------------------------------------------------

async def my_chat_member_handler(update, context):
    cm = update.my_chat_member
    if not cm or not cm.chat:
        return
    save_chat(cm.chat)
    logger.info(
        "MY_CHAT_MEMBER | chat_id=%s | type=%s | old=%s | new=%s",
        cm.chat.id, cm.chat.type,
        cm.old_chat_member.status, cm.new_chat_member.status,
    )

# ---------------------------------------------------------------------------
# Main message processor
# ---------------------------------------------------------------------------

async def handle_all_messages(update, context):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not message or not user or not chat:
        return

    logger.info(
        "MESSAGE RECEIVED | chat_id=%s | chat_type=%s | user=%s | text=%r",
        chat.id, chat.type, user.username or user.id, message.text,
    )

    save_user(user)
    save_chat(chat)

    if await handle_admin_media_upload(update, context):
        return
    if not message.text:
        return
    text = message.text.strip()
    if not text:
        return
    if await handle_admin_title_save(update, context):
        return

    if not check_rate_limit(user.id):
        await message.reply_text("⏳ একটু ধীরে মেসেজ করুন, আমি শুনছি। 🙂")
        return

    norm = normalize_text(text)

    help_words = ["এডমিন চাই", "অ্যাডমিন চাই", "admin help", "এডমিনের সাথে", "সমস্যা হয়েছে", "অভিযোগ"]
    if any(w in norm for w in help_words) or ("admin" in norm and ("help" in norm or "contact" in norm)):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("💬 এডমিন @tomalchowdhury2-কে মেসেজ দিন",
                                 url=f"https://t.me/{ADMIN_USERNAME}")
        ]])
        await message.reply_text(
            f"👑 **এডমিনের সাথে যোগাযোগ:** @{ADMIN_USERNAME}",
            reply_markup=keyboard, parse_mode="Markdown",
        )
        await notify_admin_user_help(context.bot, user, text)
        return

    is_drama_query = any(k in norm for k in ["নাটক", "drama", "natok"])
    is_song_query = any(k in norm for k in ["গান", "song", "গজল", "audio"])
    is_video_query = any(k in norm for k in ["ভিডিও", "video", "মুভি", "movie"])
    is_content_intent = (
        is_drama_query or is_song_query or is_video_query or
        any(r in norm for r in ["চাই", "দাও", "দেন", "পাঠাও", "পাঠান", "লাগবে", "দেও"])
    )

    if is_content_intent:
        target_category = "drama" if is_drama_query else ("song" if is_song_query else None)
        clean_query = norm
        for rm in ["আমাকে", "একটি", "একটা", "নাটক", "গান", "ভিডিও", "দাও", "দেন", "চাই", "লাগবে", "নতুন", "প্লিজ", "please", "দেও"]:
            clean_query = re.sub(r"\b" + re.escape(rm) + r"\b", " ", clean_query)
        clean_query = re.sub(r"\s+", " ", clean_query).strip()

        if clean_query:
            found = search_content(clean_query, target_category)
            if found:
                await deliver_media(update, found)
                return

        if is_drama_query and (not clean_query or len(clean_query) < 2):
            dramas = get_contents_by_category("drama", 3)
            if dramas:
                buttons = [[InlineKeyboardButton(f"🎬 {d['title']} ({d['views']} views)", callback_data=f"send_media_{d['id']}")] for d in dramas]
                await message.reply_text("🎬 **নাটকগুলো থেকে বেছে নিন:**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
                return

        if is_song_query and (not clean_query or len(clean_query) < 2):
            songs = get_contents_by_category("song", 3)
            if songs:
                buttons = [[InlineKeyboardButton(f"🎵 {s['title']}", callback_data=f"send_media_{s['id']}")] for s in songs]
                await message.reply_text("🎵 **গানগুলো থেকে বেছে নিন:**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")
                return

        if is_drama_query or is_song_query or is_video_query:
            recs = get_contents_by_category(target_category or "drama", 3)
            buttons = [[InlineKeyboardButton(f"🎬 {r['title']}", callback_data=f"send_media_{r['id']}")] for r in recs]
            buttons.append([InlineKeyboardButton("📩 এডমিনকে আপলোডের অনুরোধ", url=f"https://t.me/{ADMIN_USERNAME}")])
            rec_text = ""
            if recs:
                rec_text = "\n\n💡 জনপ্রিয় কন্টেন্ট:\n" + "\n".join(f"• **{r['title']}**" for r in recs)
            await message.reply_text(
                f"😔 **কাঙ্ক্ষিত কন্টেন্ট পাওয়া যায়নি।**{rec_text}\n\nনামটি ঠিকভাবে লিখে আবার চেষ্টা করুন।",
                reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown",
            )
            await notify_admin_missing_content(context.bot, user, target_category or "Media", text)
            return

    if any(w in norm for w in ["আবহাওয়া", "weather", "বৃষ্টি", "তাপমাত্রা"]):
        await message.reply_text((await get_weather()) or "❌ আবহাওয়া তথ্য পাওয়া যায়নি।")
        return

    if any(w in norm for w in ["নামাজের সময়", "নামাজ কখন", "আজকের নামাজ", "prayer time"]):
        await message.reply_text((await get_prayer_times()) or "❌ নামাজের সময় পাওয়া যায়নি।")
        return

    save_message(chat.id, user.id, "user", text)
    await message.reply_chat_action("typing")
    ai_reply = await generate_chatgpt_response(chat.id, text)
    save_message(chat.id, 0, "assistant", ai_reply)
    await message.reply_text(ai_reply)

# ---------------------------------------------------------------------------
# Error / startup
# ---------------------------------------------------------------------------

async def global_error_handler(update, context):
    logger.error("Exception while handling update: %s", context.error)
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    user = update.effective_user if isinstance(update, Update) else None
    try:
        await send_admin_alert(
            context.bot,
            "⚠️ **[ERROR ALERT]**\n"
            f"User: {user.first_name if user else 'Unknown'}\n\n"
            f"`{str(context.error)}`\n\n"
            f"Traceback:\n`{tb[-400:]}`",
        )
    except Exception:
        pass


async def post_init(application):
    # run_polling uses getUpdates. Telegram does not allow getUpdates while an
    # outgoing webhook is set, so clear any old webhook before polling.
    try:
        await application.bot.delete_webhook(drop_pending_updates=False)
        me = await application.bot.get_me()
        logger.info("BOT CONNECTED | username=@%s | id=%s", me.username, me.id)
    except Exception as e:
        logger.error("Bot startup check failed: %r", e)

    if AUTO_MESSAGES_ENABLED:
        application.create_task(
            automatic_notification_loop(application),
            name="automatic_notification_loop",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ Error: BOT_TOKEN is missing! Set BOT_TOKEN in environment.")
        return

    init_db()

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("contact", contact_command))
    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("auto_on", auto_on_command))
    app.add_handler(CommandHandler("auto_off", auto_off_command))
    app.add_handler(CommandHandler("notify_test", notify_test_command))

    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Saves a group as soon as the bot is added/changed there.
    app.add_handler(
        ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER)
    )

    # Media first; the text handler below processes normal messages.
    app.add_handler(MessageHandler(
        filters.VIDEO | filters.AUDIO | filters.PHOTO |
        filters.Document.ALL | filters.ANIMATION,
        handle_all_messages,
    ))

    # Text messages, including normal group messages.
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_all_messages,
    ))

    app.add_error_handler(global_error_handler)

    print("==================================================")
    print("🤖 Telegram Bot Running with OpenAI Intelligence")
    print(f"👑 Admin: @{ADMIN_USERNAME} (ID: {ADMIN_IDS[0]})")
    print(f"🧠 AI Model: {OPENAI_MODEL}")
    print(f"🔔 Auto notifications: {'ON' if AUTO_MESSAGES_ENABLED else 'OFF'}")
    print(f"📚 Study hours: {STUDY_HOURS}")
    print(f"⚽ Sports hours: {SPORTS_HOURS}")
    print(f"😴 Sleep hour: {SLEEP_HOUR}:00")
    print("==================================================")

    # Long polling. Do not run another instance with the same BOT_TOKEN.
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
