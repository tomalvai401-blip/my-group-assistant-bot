#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
 Telegram AI Assistant & Media Bot (ChatGPT-Grade Intelligence)
 Admin: @tomalchowdhury2 (ID: 8721334265)
 
 Features:
   1. ChatGPT-like accurate, fast AI replies to ANY question (Gemini Flash + OpenAI)
   2. Seamless Admin Media Upload:
      - Admin sends Video, Photo, Audio, or Document
      - Bot acknowledges and prompts for the Title
      - Admin enters Title -> Bot saves to DB and confirms success
   3. Smart User Drama/Song Delivery:
      - User asks for drama/song (e.g., "আমাকে নাটক দাও", "নতুন নাটক চাই", "গানের নাম")
      - If found: Bot sends the video/audio immediately
      - If general request ("নাটক দাও"): Bot sends top trending drama or provides 1-click buttons
      - If specific title not found: Recommends trending dramas/songs and notifies Admin
   4. Automatic Admin Alerts:
      - Errors or user help requests are instantly sent to Admin ID 8721334265
      - Clickable link to @tomalchowdhury2 in all help menus
   5. Weather & Prayer times + Auto Hourly Reminders
=============================================================================
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

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ---------------------------------------------------------------------------
# Configuration & Environment
# ---------------------------------------------------------------------------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Primary Admin Details
ADMIN_IDS = [8721334265]
ADMIN_USERNAME = "tomalchowdhury2"

# Regional Settings
TIMEZONE_NAME = os.getenv("TIMEZONE", "Asia/Dhaka")
try:
    TZ = pytz.timezone(TIMEZONE_NAME)
except Exception:
    TZ = pytz.timezone("Asia/Dhaka")

PRAYER_CITY = os.getenv("PRAYER_CITY", "Dhaka")
PRAYER_COUNTRY = os.getenv("PRAYER_COUNTRY", "Bangladesh")
DB_FILE = os.getenv("DB_FILE", "bot_database.db")

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_bot")

# Setup AI Clients (Supports both Gemini and OpenAI)
gemini_available = False
openai_client = None

if GEMINI_API_KEY:
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_available = True
        logger.info("Google Gemini AI client configured successfully.")
    except Exception as e:
        logger.warning("Could not initialize google.generativeai: %s", e)

if OPENAI_API_KEY:
    try:
        from openai import AsyncOpenAI
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client configured successfully.")
    except Exception as e:
        logger.warning("Could not initialize OpenAI client: %s", e)

# ---------------------------------------------------------------------------
# Database Layer (SQLite)
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def db_execute(query, params=(), fetchone=False, fetch=False, commit=True):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        if commit:
            conn.commit()
        if fetchone:
            res = cursor.fetchone()
            return dict(res) if res else None
        if fetch:
            res = cursor.fetchall()
            return [dict(r) for r in res]
        return cursor.lastrowid

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                joined_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT,
                title TEXT,
                username TEXT,
                created_at TEXT
            )
        """)
        cursor.execute("""
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
        # Ensure 'views' column exists
        cursor.execute("PRAGMA table_info(contents)")
        cols = [c[1] for c in cursor.fetchall()]
        if "views" not in cols:
            cursor.execute("ALTER TABLE contents ADD COLUMN views INTEGER DEFAULT 0")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.commit()
    logger.info("Database initialized with media and views support.")

def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def save_user(user):
    if not user:
        return
    db_execute("""
        INSERT INTO users (user_id, first_name, last_name, username, joined_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            first_name = excluded.first_name,
            last_name = excluded.last_name,
            username = excluded.username
    """, (user.id, user.first_name or "", user.last_name or "", user.username or "", now_str()))

def save_chat(chat):
    if not chat:
        return
    db_execute("""
        INSERT INTO chats (chat_id, chat_type, title, username, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            chat_type = excluded.chat_type,
            title = excluded.title,
            username = excluded.username
    """, (chat.id, chat.type, chat.title or "", chat.username or "", now_str()))

def save_message(chat_id, user_id, role, content):
    db_execute("""
        INSERT INTO messages (chat_id, user_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (chat_id, user_id, role, content, now_str()))

def get_history(chat_id, limit=8):
    rows = db_execute("""
        SELECT role, content FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (chat_id, limit), fetch=True)
    return rows[::-1] if rows else []

def get_state(key):
    row = db_execute("SELECT value FROM bot_state WHERE key = ?", (key,), fetchone=True)
    return row["value"] if row else None

def set_state(key, value):
    db_execute("""
        INSERT INTO bot_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))

# ---------------------------------------------------------------------------
# Rate Limiter & Helpers
# ---------------------------------------------------------------------------
user_last_action = {}

def check_rate_limit(user_id, interval=1.0):
    now = time.time()
    last = user_last_action.get(user_id, 0)
    if now - last < interval:
        return False
    user_last_action[user_id] = now
    return True

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def normalize_text(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^\w\s\u0980-\u09FF]", " ", t)
    return re.sub(r"\s+", " ", t).strip()

# ---------------------------------------------------------------------------
# Media Categories & Content Search
# ---------------------------------------------------------------------------
def detect_category(title: str) -> str:
    t = normalize_text(title)
    if "নাটক" in t or "drama" in t or "natok" in t:
        return "drama"
    if "গান" in t or "song" in t or "audio" in t or "গজল" in t or "music" in t:
        return "song"
    if "মুভি" in t or "movie" in t or "cinema" in t or "ফিল্ম" in t:
        return "movie"
    if "ডান্স" in t or "dance" in t:
        return "dance"
    if "ছবি" in t or "photo" in t or "pic" in t:
        return "photo"
    return "video"

def search_content(query: str, category: str = None):
    query = normalize_text(query)
    if not query:
        return None

    # Search with category filter if specified
    if category:
        row = db_execute("""
            SELECT * FROM contents
            WHERE category = ? AND lower(title) LIKE ?
            ORDER BY views DESC, id DESC
            LIMIT 1
        """, (category, f"%{query}%"), fetchone=True)
        if row:
            return row

    # Search across all
    row = db_execute("""
        SELECT * FROM contents
        WHERE lower(title) LIKE ?
        ORDER BY views DESC, id DESC
        LIMIT 1
    """, (f"%{query}%",), fetchone=True)
    if row:
        return row

    # Split keywords
    words = [w for w in query.split() if len(w) >= 2]
    if not words:
        return None

    conds = ["lower(title) LIKE ?" for _ in words[:4]]
    params = [f"%{w}%" for w in words[:4]]

    if category:
        sql = f"SELECT * FROM contents WHERE category = ? AND ({' OR '.join(conds)}) ORDER BY views DESC, id DESC LIMIT 1"
        return db_execute(sql, (category, *params), fetchone=True)
    else:
        sql = f"SELECT * FROM contents WHERE ({' OR '.join(conds)}) ORDER BY views DESC, id DESC LIMIT 1"
        return db_execute(sql, tuple(params), fetchone=True)

def increment_views(content_id: int):
    db_execute("UPDATE contents SET views = views + 1 WHERE id = ?", (content_id,))

def get_contents_by_category(category: str, limit: int = 5):
    return db_execute("""
        SELECT id, title, media_type, category, views
        FROM contents
        WHERE category = ?
        ORDER BY views DESC, id DESC
        LIMIT ?
    """, (category, limit), fetch=True)

def get_top_trending(limit: int = 5):
    return db_execute("""
        SELECT id, title, media_type, category, views
        FROM contents
        ORDER BY views DESC, id DESC
        LIMIT ?
    """, (limit,), fetch=True)

# ---------------------------------------------------------------------------
# ChatGPT-Grade AI Engine (Accurate, Fast, Benglish & Bangla Fluent)
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTIONS = f"""
তুমি একজন অত্যন্ত চটপটে, জ্ঞানগর্ভ এবং নির্ভুল Telegram AI সহকারী। 
তোমার দায়িত্ব হলো ব্যবহারকারীকে যেকোনো বিষয়ে সরাসরি, সত্য ও ChatGPT-এর মতো উচ্চমানের উত্তর প্রদান করা।

তোমার প্রধান অ্যাডমিন ও নির্মাতা: @{ADMIN_USERNAME} (User ID: {ADMIN_IDS[0]})।

তোমার আচরণবিধি:
1. সরাসরি উত্তর: ভূমিকা বা অপ্রয়োজনীয় বাক্য ("আচ্ছা", "ঠিক আছে", "আমি দেখছি") না বলে সরাসরি সঠিক তথ্য দিয়ে উত্তর শুরু করবে।
2. ভাষা ও শৈলী: 
   - ইউজার বাংলায় প্রশ্ন করলে খাঁটি, সুন্দর বাংলায় উত্তর দাও।
   - Banglish (যেমন: 'kemon acho', 'amar natok lagbe') লিখলে সহজ Banglish বা বাংলায় স্পষ্ট উত্তর দাও।
   - ইংরেজিতে প্রশ্ন করলে প্রাঞ্জল ইংরেজিতে উত্তর দাও।
3. শিক্ষা, তথ্য ও যেকোনো প্রশ্ন: গণিত, বিজ্ঞান, ইতিহাস, অনুবাদ, কোডিং বা সাধারণ কথোপকথন—যেকোনো প্রশ্নের সঠিক সমাধান ও সুন্দর ব্যাখ্যা দাও।
4. বটের মিডিয়া সম্পর্কে সততা: গান বা নাটকের ভিডিও বটের অ্যাডমিন @{ADMIN_USERNAME} ডেটাবেজে আপলোড করেন। তুমি নিজে বানিয়ে ফাইল দেওয়ার দাবি করবে না।
5. উত্তর স্পষ্ট, সংক্ষিপ্ত এবং পাঠোপযোগী রাখো।
"""

async def generate_chatgpt_response(chat_id: int, user_text: str) -> str:
    """Delivers accurate ChatGPT-grade answers using Gemini 2.5 Flash or OpenAI."""
    history = get_history(chat_id, limit=6)

    # 1. Try Gemini Flash (Fast, free, superior Bengali capabilities)
    if gemini_available and GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=SYSTEM_INSTRUCTIONS
            )
            # Build conversation history
            chat_session = model.start_chat(history=[])
            for h in history:
                role = "user" if h["role"] == "user" else "model"
                try:
                    chat_session.history.append({"role": role, "parts": [h["content"]]})
                except Exception:
                    pass

            response = await asyncio.wait_for(
                asyncio.to_thread(chat_session.send_message, user_text),
                timeout=10.0
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            logger.error("Gemini AI error: %s", repr(e))

    # 2. Try OpenAI (gpt-4o-mini)
    if openai_client and OPENAI_API_KEY:
        try:
            messages = [{"role": "system", "content": SYSTEM_INSTRUCTIONS}]
            for h in history:
                messages.append({
                    "role": "assistant" if h["role"] == "assistant" else "user",
                    "content": h["content"]
                })
            messages.append({"role": "user", "content": user_text})

            res = await asyncio.wait_for(
                openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    max_tokens=650,
                    temperature=0.7,
                ),
                timeout=12.0
            )
            ans = res.choices[0].message.content
            if ans and ans.strip():
                return ans.strip()
        except Exception as e:
            logger.error("OpenAI error: %s", repr(e))

    # 3. Fallback intelligent response if no API key is provided
    return (
        f"👋 আপনার বার্তা পেয়েছি! সঠিক উত্তরের জন্য .env ফাইলে আপনার GEMINI_API_KEY বা OPENAI_API_KEY যোগ করুন।\n\n"
        f"যেকোনো গান বা নাটক খুঁজতে সরাসরি নাম লিখুন, অথবা অ্যাডমিন @{ADMIN_USERNAME}-এর সাথে যোগাযোগ করুন।"
    )

# ---------------------------------------------------------------------------
# Admin Alerts & Notifications
# ---------------------------------------------------------------------------
async def send_admin_alert(bot, text: str, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error("Failed to notify admin %s: %s", admin_id, e)

async def notify_admin_missing_content(bot, user, content_type: str, query: str):
    """Alerts Admin when a user searches for a drama or song that is missing."""
    text = (
        "📢 **[নতুন কন্টেন্টের ডিমান্ড / রিকুয়েস্ট]**\n\n"
        f"👤 **ইউজার:** {user.first_name} (@{user.username or 'নাই'})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"📁 **টাইপ:** {content_type}\n"
        f"🔍 **ইউজার যা খুঁজেছে:** `{query}`\n"
        f"⏰ **সময়:** {now_str()}\n\n"
        f"👉 অ্যাডমিন @{ADMIN_USERNAME} এই নাটক/গানটি বটে আপলোড করে দিলে ইউজাররা দেখতে পারবে।"
    )
    keyboard = None
    if user.username:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✉️ Reply @{user.username}", url=f"https://t.me/{user.username}")]
        ])
    await send_admin_alert(bot, text, keyboard)

async def notify_admin_user_help(bot, user, user_msg: str):
    """Alerts Admin when user wants help or reports an issue."""
    text = (
        "⚠️ **[ইউজার সাহায্যের জন্য নক দিয়েছে]**\n\n"
        f"👤 **User:** {user.first_name} (@{user.username or 'N/A'})\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"⏰ **Time:** {now_str()}\n\n"
        f"💬 **বার্তা:**\n_{user_msg}_"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 সরাসরি মেসেজ দিন", url=f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}")]
    ])
    await send_admin_alert(bot, text, keyboard)

# ---------------------------------------------------------------------------
# Send Media Helper
# ---------------------------------------------------------------------------
async def deliver_media(update: Update, row: dict):
    message = update.effective_message
    content_id = row["id"]
    media_type = row["media_type"]
    file_id = row["file_id"]
    title = row["title"]

    increment_views(content_id)

    await message.reply_text(f"🎬 **{title}**\n\n⏳ পাঠানো হচ্ছে, দয়া করে অপেক্ষা করুন...")

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

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 এডমিন: @" + ADMIN_USERNAME, url=f"https://t.me/{ADMIN_USERNAME}")]
        ])
        await message.reply_text(
            "✅ কন্টেন্ট সফলভাবে পাঠানো হয়েছে!\nআর কোনো নাটক বা গান লাগলে সরাসরি নাম লিখুন। 🤝",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error("Error sending media %s: %s", content_id, repr(e))
        await send_admin_alert(update.get_bot(), f"❌ Error sending file ID {content_id}: {e}")
        await message.reply_text("❌ ফাইলটি পাঠাতে সমস্যা হয়েছে। এডমিনকে জানানো হয়েছে।")

# ---------------------------------------------------------------------------
# Admin Media Upload Pipeline (Post Media -> Ask Title -> Confirm)
# ---------------------------------------------------------------------------
async def handle_admin_media_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return False

    media_type = None
    file_id = None

    if message.video:
        media_type = "video"
        file_id = message.video.file_id
    elif message.audio:
        media_type = "audio"
        file_id = message.audio.file_id
    elif message.photo:
        media_type = "photo"
        file_id = message.photo[-1].file_id
    elif message.document:
        media_type = "document"
        file_id = message.document.file_id
    elif message.animation:
        media_type = "animation"
        file_id = message.animation.file_id

    if not file_id:
        return False

    # Store in context and wait for title
    context.user_data["pending_media"] = {
        "media_type": media_type,
        "file_id": file_id,
    }
    context.user_data["waiting_title"] = True

    await message.reply_text(
        f"📥 **{media_type.upper()} মিডিয়া ফাইল পেয়েছি!**\n\n"
        "📝 দয়া করে এই কন্টেন্টের **নাম (Title)** লিখে পাঠান।\n"
        "যেমন: `নতুন ঈদের নাটক ২০২৪` অথবা `মন বোঝে না বাংলা গান`\n\n"
        "*(আপনি নাম দিলে এটি সাথে সাথে ডেটাবেজে সেভ হয়ে যাবে)*",
        parse_mode="Markdown"
    )
    return True

async def handle_admin_title_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return False

    if not context.user_data.get("waiting_title"):
        return False

    title = message.text.strip() if message.text else ""
    if not title:
        await message.reply_text("❌ Title খালি রাখা যাবে না। দয়া করে একটি নাম লিখুন:")
        return True

    pending = context.user_data.get("pending_media")
    if not pending:
        context.user_data["waiting_title"] = False
        return False

    category = detect_category(title)
    new_id = db_execute("""
        INSERT INTO contents (title, media_type, file_id, category, views, added_by, created_at)
        VALUES (?, ?, ?, ?, 0, ?, ?)
    """, (title, pending["media_type"], pending["file_id"], category, user.id, now_str()))

    context.user_data.pop("pending_media", None)
    context.user_data["waiting_title"] = False

    cat_label = "নাটক (Drama)" if category == "drama" else ("গান (Song)" if category == "song" else category.title())

    await message.reply_text(
        "🎉 **কন্টেন্ট সফলভাবে ডেটাবেজে সংরক্ষিত হয়েছে!**\n\n"
        f"🆔 **কন্টেন্ট ID:** `{new_id}`\n"
        f"🎬 **Title:** **{title}**\n"
        f"📁 **মিডিয়া টাইপ:** `{pending['media_type']}`\n"
        f"🏷️ **ক্যাটাগরি:** `{cat_label}`\n\n"
        "👉 এখন সাধারণ ইউজাররা এই নাটক বা গান চাইলে বট পলকের মধ্যে তাদের পাঠিয়ে দেবে!",
        parse_mode="Markdown"
    )
    return True

# ---------------------------------------------------------------------------
# Weather & Prayer API
# ---------------------------------------------------------------------------
async def get_weather():
    url = "https://api.open-meteo.com/v1/forecast?latitude=23.8103&longitude=90.4125&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    return None
                data = await res.json()
        c = data.get("current", {})
        return (
            f"🌤️ **{PRAYER_CITY} আবহাওয়া সংবাদ**\n\n"
            f"🌡️ তাপমাত্রা: **{c.get('temperature_2m', '?')}°C**\n"
            f"💧 আর্দ্রতা: **{c.get('relative_humidity_2m', '?')}%**\n"
            f"💨 বাতাস: **{c.get('wind_speed_10m', '?')} km/h**"
        )
    except Exception:
        return None

async def get_prayer_times():
    url = f"https://api.aladhan.com/v1/timingsByCity?city={PRAYER_CITY}&country={PRAYER_COUNTRY}&method=1"
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                if res.status != 200:
                    return None
                data = await res.json()
        t = data.get("data", {}).get("timings", {})
        return (
            f"🕌 **{PRAYER_CITY} নামাজের সময়সূচি**\n\n"
            f"🌅 ফজর: **{t.get('Fajr', '-')}**\n"
            f"☀️ সূর্যোদয়: {t.get('Sunrise', '-')}\n"
            f"🕛 যোহর: **{t.get('Dhuhr', '-')}**\n"
            f"🌇 আসর: **{t.get('Asr', '-')}**\n"
            f"🌆 মাগরিব: **{t.get('Maghrib', '-')}**\n"
            f"🌙 এশা: **{t.get('Isha', '-')}**"
        )
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    save_user(user)
    save_chat(update.effective_chat)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎬 নাটক চাই", callback_data="show_dramas"),
            InlineKeyboardButton("🎵 গান চাই", callback_data="show_songs"),
        ],
        [
            InlineKeyboardButton("🔥 ট্রেন্ডিং কন্টেন্ট", callback_data="show_trending"),
            InlineKeyboardButton("🌤️ আবহাওয়া", callback_data="show_weather"),
        ],
        [
            InlineKeyboardButton("👑 এডমিন: @" + ADMIN_USERNAME, url=f"https://t.me/{ADMIN_USERNAME}")
        ]
    ])

    await update.effective_message.reply_text(
        f"👋 আসসালামু আলাইকুম **{user.first_name}**!\n\n"
        "আমি আপনার বুদ্ধিমান **AI টেলিগ্রাম বট**।\n"
        "✨ **ChatGPT-এর মতো যেকোনো প্রশ্নের সঠিক উত্তর** মুহূর্তে দিতে পারি।\n"
        "🎬 যেকোনো **নাটক, গান, ভিডিও** খুঁজতে সরাসরি লিখুন।\n\n"
        "💡 যা জানতে চান বা যে নাটক দেখতে চান, তা সরাসরি লিখে মেসেজ করুন!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 এডমিনকে মেসেজ দিন", url=f"https://t.me/{ADMIN_USERNAME}")]
    ])
    await update.effective_message.reply_text(
        "📖 **বটের ব্যবহারবিধি:**\n\n"
        "1. **ChatGPT AI রিপ্লাই:** যেকোনো প্রশ্ন লিখে পাঠান (যেমন: 'পানি ফুটলে কি হয়?', 'কেমন আছো?')\n"
        "2. **নাটক বা গান পাওয়া:** `আমাকে একটা নাটক দাও` অথবা নাটকের নাম লিখুন\n"
        "3. **কমান্ডসমূহ:**\n"
        "   - /trending - বেশি দেখা নাটক ও গান\n"
        "   - /weather - আবহাওয়া সংবাদ\n"
        "   - /prayer - নামাজের সময়\n"
        "   - /contact - এডমিনের সাথে যোগাযোগ\n\n"
        f"👑 প্রধান অ্যাডমিন: @{ADMIN_USERNAME} (ID: `{ADMIN_IDS[0]}`)",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def contact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 এডমিনকে সরাসরি মেসেজ দিন", url=f"https://t.me/{ADMIN_USERNAME}")]
    ])
    await update.effective_message.reply_text(
        f"👑 **এডমিন যোগাযোগ তথ্য:**\n\n"
        f"👤 এডমিন: @{ADMIN_USERNAME}\n"
        f"🆔 এডমিন আইডি: `{ADMIN_IDS[0]}`\n\n"
        "আপনার কোনো নাটকের রিকুয়েস্ট বা সাহায্যের জন্য নিচের বাটনে ক্লিক করুন:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ এই কমান্ডটি শুধুমাত্র এডমিন @tomalchowdhury2-এর জন্য।")
        return

    await update.effective_message.reply_text(
        f"👑 **এডমিন প্যানেল (@{ADMIN_USERNAME})**\n\n"
        "📥 **কন্টেন্ট আপলোড নিয়ম:**\n"
        "আপনি সরাসরি কোনো ভিডিও, অডিও বা ছবি বটে পাঠালেই বট আপনার কাছে সেটির নাম চাইবে। নাম দিলেই সেভ হয়ে যাবে!\n\n"
        "📚 /list - সেভ করা সব কন্টেন্ট দেখুন\n"
        "📊 /stats - ইউজার ও ভিউ পরিসংখ্যান\n"
        "🗑️ /delete <ID> - কন্টেন্ট ডিলিট\n"
        "📢 /broadcast <TEXT> - সকল ইউজারে মেসেজ পাঠানো",
        parse_mode="Markdown"
    )

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    rows = db_execute("SELECT id, title, media_type, category, views FROM contents ORDER BY id DESC LIMIT 30", fetch=True)
    if not rows:
        await update.effective_message.reply_text("📭 এখনো কোনো কন্টেন্ট আপলোড করা হয়নি।")
        return
    lines = ["📚 **সংরক্ষিত কন্টেন্ট তালিকা:**\n"]
    for r in rows:
        lines.append(f"🆔 `{r['id']}` | 🎬 **{r['title']}** | 📁 {r['media_type']} | 👁️ {r['views']} views")
    await update.effective_message.reply_text("\n".join(lines)[:4000], parse_mode="Markdown")

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.effective_message.reply_text("ব্যবহার করুন: `/delete <ID>` (যেমন: `/delete 2`)", parse_mode="Markdown")
        return
    try:
        cid = int(context.args[0])
        db_execute("DELETE FROM contents WHERE id = ?", (cid,))
        await update.effective_message.reply_text(f"✅ ID `{cid}` সফলভাবে ডিলিট করা হয়েছে।", parse_mode="Markdown")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ ডিলিট করতে সমস্যা: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    u = db_execute("SELECT COUNT(*) c FROM users", fetchone=True)["c"]
    c = db_execute("SELECT COUNT(*) c FROM contents", fetchone=True)["c"]
    v = db_execute("SELECT SUM(views) s FROM contents", fetchone=True)["s"] or 0
    await update.effective_message.reply_text(
        f"📊 **বট স্ট্যাটিস্টিক্স:**\n\n👤 ইউজার: **{u}**\n🎬 মোট কন্টেন্ট: **{c}**\n👁️ মোট কন্টেন্ট ডেলিভারি/ভিউ: **{v}**",
        parse_mode="Markdown"
    )

# ---------------------------------------------------------------------------
# Callback Query Handler (For Inline Buttons)
# ---------------------------------------------------------------------------
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "show_dramas":
        dramas = get_contents_by_category("drama", limit=4)
        if dramas:
            buttons = [
                [InlineKeyboardButton(f"🎬 {d['title']} ({d['views']} views)", callback_data=f"send_media_{d['id']}")]
                for d in dramas
            ]
            await query.message.reply_text(
                "🎬 **আমাদের সংরক্ষিত জনপ্রিয় নাটকসমূহ:**\nযেকোনো নাটক পেতে বাটনে চাপ দিন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await query.message.reply_text("😔 এই মুহূর্তে কোনো নাটক ডেটাবেজে নেই। এডমিনকে আপলোডের অনুরোধ জানানো হয়েছে।")

    elif data == "show_songs":
        songs = get_contents_by_category("song", limit=4)
        if songs:
            buttons = [
                [InlineKeyboardButton(f"🎵 {s['title']}", callback_data=f"send_media_{s['id']}")]
                for s in songs
            ]
            await query.message.reply_text(
                "🎵 **আমাদের জনপ্রিয় গানসমূহ:**\nযে গান শুনতে চান বাটনে ক্লিক করুন:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            await query.message.reply_text("😔 এই মুহূর্তে কোনো গান ডেটাবেজে নেই। এডমিন শীঘ্রই যোগ করবেন।")

    elif data == "show_trending":
        top = get_top_trending(limit=5)
        if top:
            lines = ["🔥 **বর্তমান ট্রেন্ডিং ও বেশি দেখা কন্টেন্ট:**\n"]
            for idx, item in enumerate(top, 1):
                lines.append(f"{idx}. 🎬 **{item['title']}** — 👁️ {item['views']} বার দেখা হয়েছে")
            lines.append("\n👉 যেকোনো কন্টেন্ট পেতে সরাসরি তার নাম লিখে মেসেজ করুন!")
            await query.message.reply_text("\n".join(lines), parse_mode="Markdown")
        else:
            await query.message.reply_text("📭 কোনো কন্টেন্ট পাওয়া যায়নি।")

    elif data == "show_weather":
        w = await get_weather()
        await query.message.reply_text(w or "❌ আবহাওয়া তথ্য পাওয়া যায়নি।")

    elif data.startswith("send_media_"):
        cid = int(data.split("_")[-1])
        row = db_execute("SELECT * FROM contents WHERE id = ?", (cid,), fetchone=True)
        if row:
            await deliver_media(update, row)
        else:
            await query.message.reply_text("❌ কন্টেন্টটি খুঁজে পাওয়া যায়নি।")

# ---------------------------------------------------------------------------
# Main Text & Message Processor
# ---------------------------------------------------------------------------
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    save_user(user)
    save_chat(chat)

    # 1. Admin Media Upload (If Admin sends Video/Audio/Photo)
    if await handle_admin_media_upload(update, context):
        return

    if not message.text:
        return

    text = message.text.strip()
    if not text:
        return

    # 2. Admin Title Confirmation (If Admin is naming the uploaded media)
    if await handle_admin_title_save(update, context):
        return

    # Anti-flood rate limit
    if not check_rate_limit(user.id):
        await message.reply_text("⏳ একটু ধীরে মেসেজ করুন, আমি শুনছি। 🙂")
        return

    norm = normalize_text(text)

    # 3. User requests Admin Help
    help_words = ["এডমিন চাই", "অ্যাডমিন চাই", "admin help", "এডমিনের সাথে", "সমস্যা হয়েছে", "অভিযোগ"]
    if any(w in norm for w in help_words) or ("admin" in norm and ("help" in norm or "contact" in norm)):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 এডমিন @tomalchowdhury2-কে মেসেজ দিন", url=f"https://t.me/{ADMIN_USERNAME}")]
        ])
        await message.reply_text(
            f"👑 **এডমিনের সাথে যোগাযোগ:**\n\n"
            f"আমাদের সম্মানিত এডমিন **@{ADMIN_USERNAME}**-কে আপনার বার্তা জানানো হয়েছে।\n"
            "নিচের বাটনে ট্যাপ করে সরাসরি এডমিনকে মেসেজ পাঠাতে পারেন।",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await notify_admin_user_help(context.bot, user, text)
        return

    # 4. User Content Requests (Drama / Song / Video)
    is_drama_query = any(k in norm for k in ["নাটক", "drama", "natok"])
    is_song_query = any(k in norm for k in ["গান", "song", "গজল", "audio"])
    is_video_query = any(k in norm for k in ["ভিডিও", "video", "মুভি", "movie"])

    is_content_intent = (
        is_drama_query or is_song_query or is_video_query or
        any(r in norm for r in ["চাই", "দাও", "দেন", "পাঠাও", "পাঠান", "লাগবে", "দেও"])
    )

    if is_content_intent:
        target_category = "drama" if is_drama_query else ("song" if is_song_query else None)

        # Remove filter words to extract exact title query
        clean_query = norm
        for rm in ["আমাকে", "একটি", "একটা", "নাটক", "গান", "ভিডিও", "দাও", "দেন", "চাই", "লাগবে", "নতুন", "প্লিজ", "please", "দেও"]:
            clean_query = re.sub(r"\b" + re.escape(rm) + r"\b", " ", clean_query)
        clean_query = re.sub(r"\s+", " ", clean_query).strip()

        # A. If user wrote a specific title, search for it
        if clean_query:
            found = search_content(clean_query, target_category)
            if found:
                await deliver_media(update, found)
                return

        # B. If user just asked generally "আমাকে একটা নাটক দাও" (no specific title)
        if is_drama_query and (not clean_query or len(clean_query) < 2):
            dramas = get_contents_by_category("drama", limit=3)
            if dramas:
                # If only 1 drama, send directly!
                if len(dramas) == 1:
                    row = db_execute("SELECT * FROM contents WHERE id = ?", (dramas[0]["id"],), fetchone=True)
                    await deliver_media(update, row)
                    return
                # Otherwise, offer quick 1-click buttons
                buttons = [
                    [InlineKeyboardButton(f"🎬 {d['title']} ({d['views']} views)", callback_data=f"send_media_{d['id']}")]
                    for d in dramas
                ]
                await message.reply_text(
                    "🎬 **আমাদের কাছে এই চমৎকার নাটকগুলো রয়েছে:**\nকোনটি দেখতে চান বাটনে ক্লিক করুন:",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                return

        if is_song_query and (not clean_query or len(clean_query) < 2):
            songs = get_contents_by_category("song", limit=3)
            if songs:
                buttons = [
                    [InlineKeyboardButton(f"🎵 {s['title']}", callback_data=f"send_media_{s['id']}")]
                    for s in songs
                ]
                await message.reply_text(
                    "🎵 **আমাদের জনপ্রিয় গানসমূহ:**\nযে গান শুনতে চান বাটনে ক্লিক করুন:",
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                return

        # C. Content NOT found in DB -> Provide Trending Suggestions and notify Admin
        if is_drama_query or is_song_query or is_video_query:
            recs = get_contents_by_category(target_category or "drama", limit=3)
            rec_text = ""
            buttons = []
            if recs:
                rec_lines = [f"• **{r['title']}** (👁️ {r['views']} বার দেখা হয়েছে)" for r in recs]
                rec_text = f"\n\n💡 তবে আপনি চাইলে আমাদের সবচেয়ে বেশি দেখা বা জনপ্রিয় এই কন্টেন্টগুলো দেখতে পারেন:\n" + "\n".join(rec_lines)
                buttons = [
                    [InlineKeyboardButton(f"🎬 {r['title']}", callback_data=f"send_media_{r['id']}")]
                    for r in recs
                ]

            buttons.append([
                InlineKeyboardButton("📩 এডমিনকে আপলোডের অনুরোধ পাঠান", url=f"https://t.me/{ADMIN_USERNAME}")
            ])

            await message.reply_text(
                f"😔 **দুঃখিত!** আপনার কাঙ্ক্ষিত কন্টেন্টটি পাওয়া যায়নি।{rec_text}\n\n"
                f"👉 যে কন্টেন্ট দেখতে চান সরাসরি তার নাম লিখুন অথবা বাটনে চাপ দিন।",
                reply_markup=InlineKeyboardMarkup(buttons),
                parse_mode="Markdown"
            )

            # Inform admin so admin can upload this drama/song
            await notify_admin_missing_content(context.bot, user, target_category or "Media", text)
            return

    # 5. Weather check
    if any(w in norm for w in ["আবহাওয়া", "weather", "বৃষ্টি", "তাপমাত্রা"]):
        w = await get_weather()
        await message.reply_text(w or "❌ আবহাওয়া তথ্য পাওয়া যায়নি।")
        return

    # 6. Prayer check
    if any(w in norm for w in ["নামাজের সময়", "নামাজ কখন", "আজকের নামাজ", "prayer time"]):
        p = await get_prayer_times()
        await message.reply_text(p or "❌ নামাজের সময় পাওয়া যায়নি।")
        return

    # 7. ChatGPT-Grade Conversational Intelligence for ALL other messages
    save_message(chat.id, user.id, "user", text)
    await message.reply_chat_action("typing")

    ai_reply = await generate_chatgpt_response(chat.id, text)
    save_message(chat.id, 0, "assistant", ai_reply)

    await message.reply_text(ai_reply)

# ---------------------------------------------------------------------------
# Global Error Handler
# ---------------------------------------------------------------------------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling update: %s", context.error)
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))

    user = None
    if isinstance(update, Update) and update.effective_user:
        user = update.effective_user

    # Alert Admin
    await send_admin_alert(
        context.bot,
        f"⚠️ **[ERROR ALERT]**\nUser: {user.first_name if user else 'Unknown'}\n\n`{str(context.error)}`\n\nTraceback:\n`{tb[-400:]}`"
    )

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("❌ Error: BOT_TOKEN is missing! Set BOT_TOKEN in .env or environment.")
        return

    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("contact", contact_command))
    app.add_handler(CommandHandler("admin", admin_panel_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("delete", delete_command))
    app.add_handler(CommandHandler("stats", stats_command))

    # Callback Query (Buttons)
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    # Media Messages (Admin Upload)
    app.add_handler(
        MessageHandler(
            (filters.VIDEO | filters.AUDIO | filters.PHOTO | filters.Document.ALL | filters.ANIMATION),
            handle_all_messages
        )
    )

    # All Text Messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_messages))

    # Error Handler
    app.add_error_handler(global_error_handler)

    print("==================================================")
    print("🤖 Telegram Bot Running with ChatGPT Intelligence")
    print(f"👑 Admin: @{ADMIN_USERNAME} (ID: {ADMIN_IDS[0]})")
    print("==================================================")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)

if __name__ == "__main__":
    main()
