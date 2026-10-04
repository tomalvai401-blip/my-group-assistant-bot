#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 Telegram AI Bot — Complete, Stable & Copy-Paste Ready
 Language: Python 3.10+ / 3.11+
 Framework: python-telegram-bot >= 20.0 (Async/Await)
 Database: SQLite3 (Automatic Setup, No External DB Needed)
 APIs: Open-Meteo (Free Weather), Aladhan (Free Prayer), OpenAI (Optional)
 Timezone: Asia/Dhaka
================================================================================
"""

import os
import re
import sys
import time
import logging
import sqlite3
import asyncio
import unicodedata
from datetime import datetime
from typing import Optional, Dict, List, Any

import pytz
import aiohttp
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode, ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ------------------------------------------------------------------------------
# 1. ENVIRONMENT CONFIGURATION & VALIDATION
# ------------------------------------------------------------------------------
load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID_RAW: str = os.getenv("ADMIN_ID", "").strip()
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "").strip()

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()

PRAYER_COUNTRY: str = os.getenv("PRAYER_COUNTRY", "Bangladesh").strip()
PRAYER_CITY: str = os.getenv("PRAYER_CITY", "Narsingdi").strip()

DEFAULT_LAT: float = float(os.getenv("DEFAULT_LAT", "24.1344"))
DEFAULT_LON: float = float(os.getenv("DEFAULT_LON", "90.7860"))

TIMEZONE_STR: str = os.getenv("TIMEZONE", "Asia/Dhaka").strip()
try:
    LOCAL_TZ = pytz.timezone(TIMEZONE_STR)
except Exception:
    LOCAL_TZ = pytz.timezone("Asia/Dhaka")

DB_PATH: str = os.getenv("DB_PATH", "bot_database.db").strip()

# Numeric Admin ID validation
try:
    ADMIN_ID: int = int(ADMIN_ID_RAW) if ADMIN_ID_RAW else 0
except ValueError:
    ADMIN_ID = 0

# ------------------------------------------------------------------------------
# 2. LOGGING SETUP
# ------------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("TelegramAIBot")

# ------------------------------------------------------------------------------
# 3. SQLITE DATABASE INITIALIZATION & REPOSITORY
# ------------------------------------------------------------------------------
def init_db() -> None:
    """Initializes SQLite database tables automatically."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Content Table for Admin Media Library
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                admin_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Tracked Chats (Groups and Private)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT NOT NULL,
                title TEXT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER DEFAULT 1
            )
            """
        )

        # Tracked Users
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Bot State (e.g. hourly message tracking, key-value storage)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        conn.commit()
        conn.close()
        logger.info("SQLite database tables initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}", exc_info=True)


def track_user_and_chat(update: Update) -> None:
    """Tracks every incoming chat and user in SQLite."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Track Chat
        if update.effective_chat:
            chat = update.effective_chat
            title = chat.title or chat.username or chat.first_name or "Private Chat"
            cursor.execute(
                """
                INSERT INTO chats (chat_id, chat_type, title, is_active)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = excluded.title,
                    is_active = 1
                """,
                (chat.id, chat.type, title),
            )

        # Track User
        if update.effective_user:
            user = update.effective_user
            cursor.execute(
                """
                INSERT INTO users (user_id, username, first_name, last_active)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_active = CURRENT_TIMESTAMP
                """,
                (user.id, user.username or "", user.first_name or ""),
            )

        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to track user/chat: {e}")


def get_all_active_chats() -> List[int]:
    """Retrieves all tracked active chat IDs."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM chats WHERE is_active = 1")
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error(f"Error fetching active chats: {e}")
        return []


def get_bot_state(key: str) -> Optional[str]:
    """Gets state value from bot_state table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error reading bot state for {key}: {e}")
        return None


def set_bot_state(key: str, value: str) -> None:
    """Sets or updates state value in bot_state table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO bot_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error setting bot state for {key}: {e}")


# ------------------------------------------------------------------------------
# 4. CONTENT REPOSITORY (Admin Media Library)
# ------------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """
    Normalizes text for fuzzy, case-insensitive comparison across mobile keyboards,
    handling decomposed vs precomposed Bengali characters (য়/য়, ড়/ড়, ঢ়/ঢ়).
    """
    if not text:
        return ""
    # Normalize unicode to handle mobile keyboard variations
    text = unicodedata.normalize("NFKC", text)
    # Map decomposed Bengali forms to standard precomposed characters
    text = text.replace("\u09af\u09bc", "\u09df").replace("য়", "য়")
    text = text.replace("\u09a1\u09bc", "\u09dc").replace("ড়", "ড়")
    text = text.replace("\u09a2\u09bc", "\u09dd").replace("ঢ়", "ঢ়")
    text = text.lower().strip()
    # Remove common punctuation
    text = re.sub(r"[?!.,_\-\–—\'\"()\[\]]+", " ", text)
    # Collapse multiple whitespaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def save_content_item(title: str, media_type: str, file_id: str, admin_id: int) -> int:
    """Saves new media content to SQLite library."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    norm = normalize_text(title)
    cursor.execute(
        """
        INSERT INTO content (title, normalized_title, media_type, file_id, admin_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (title.strip(), norm, media_type, file_id, admin_id),
    )
    new_id = cursor.lastrowid or 0
    conn.commit()
    conn.close()
    return new_id


def search_content_items(query: str) -> List[Dict[str, Any]]:
    """Searches content library using exact and partial matching."""
    norm_query = normalize_text(query)
    # Remove content intent words if user typed "গান দেন", "ভিডিও দেন" etc.
    intent_stopwords = [
        "গান", "গানটি", "গানটা", "ভিডিও", "ভিডিওটি", "নাটক", "সিনেমা", "মুভি",
        "দিন", "দেন", "চাই", "শুনব", "শুনবো", "দেখব", "দেখবো", "দেও", "দাও",
        "দয়া করে", "please", "song", "video", "drama", "movie", "den", "dao", "chai"
    ]
    cleaned_query = norm_query
    for word in intent_stopwords:
        cleaned_query = re.sub(rf"\b{re.escape(word)}\b", "", cleaned_query).strip()
    cleaned_query = re.sub(r"\s+", " ", cleaned_query).strip()

    search_targets = [norm_query]
    if cleaned_query and cleaned_query != norm_query:
        search_targets.append(cleaned_query)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    results: List[Dict[str, Any]] = []
    seen_ids = set()

    for target in search_targets:
        if not target:
            continue
        # 1. Exact match
        cursor.execute("SELECT * FROM content WHERE normalized_title = ?", (target,))
        for r in cursor.fetchall():
            if r["id"] not in seen_ids:
                results.append(dict(r))
                seen_ids.add(r["id"])

        # 2. Substring match
        cursor.execute("SELECT * FROM content WHERE normalized_title LIKE ?", (f"%{target}%",))
        for r in cursor.fetchall():
            if r["id"] not in seen_ids:
                results.append(dict(r))
                seen_ids.add(r["id"])

        # 3. Word-by-word matching
        words = target.split()
        if len(words) > 1:
            for w in words:
                if len(w) >= 3:
                    cursor.execute("SELECT * FROM content WHERE normalized_title LIKE ?", (f"%{w}%",))
                    for r in cursor.fetchall():
                        if r["id"] not in seen_ids:
                            results.append(dict(r))
                            seen_ids.add(r["id"])

    conn.close()
    return results


def get_content_by_id(content_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a single content item by ID."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM content WHERE id = ?", (content_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_content_by_id(content_id: int) -> bool:
    """Deletes a content item by ID."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM content WHERE id = ?", (content_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_all_content_items(limit: int = 50) -> List[Dict[str, Any]]:
    """Gets list of stored content items."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM content ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_library_stats() -> Dict[str, Any]:
    """Gets database statistics for admin."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM content")
    total_content = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM chats WHERE is_active = 1")
    total_chats = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    conn.close()
    return {
        "total_content": total_content,
        "total_chats": total_chats,
        "total_users": total_users,
        "db_status": "Healthy (Connected)",
    }


# ------------------------------------------------------------------------------
# 5. IN-MEMORY STATE & RATE LIMITING
# ------------------------------------------------------------------------------
# Rate limit storage: {user_id: [timestamps]}
USER_MESSAGE_TIMESTAMPS: Dict[int, List[float]] = {}
RATE_LIMIT_SECONDS = 5.0
RATE_LIMIT_MAX_MESSAGES = 7

# Admin /addsong conversation state
# {admin_id: {"step": "waiting_title", "media_type": str, "file_id": str}}
ADMIN_ADD_STATE: Dict[int, Dict[str, Any]] = {}

# User multi-content selection state
# {user_id: {"results": [content_dicts], "timestamp": float}}
USER_CONTENT_SELECTION: Dict[int, Dict[str, Any]] = {}

# User in active content search state (waiting for name after not found)
USER_WAITING_CONTENT_NAME: Dict[int, float] = {}


def check_rate_limit(user_id: int) -> bool:
    """
    Returns True if user exceeded rate limit (7 messages within 5 seconds),
    False otherwise.
    """
    now = time.time()
    timestamps = USER_MESSAGE_TIMESTAMPS.get(user_id, [])
    # Keep only timestamps in the last 5 seconds
    recent = [t for t in timestamps if now - t < RATE_LIMIT_SECONDS]
    recent.append(now)
    USER_MESSAGE_TIMESTAMPS[user_id] = recent
    return len(recent) > RATE_LIMIT_MAX_MESSAGES


def is_admin(user_id: Optional[int]) -> bool:
    """Strict numeric check for admin authorization."""
    if not user_id or not ADMIN_ID:
        return False
    return user_id == ADMIN_ID


# ------------------------------------------------------------------------------
# 6. EXTERNAL FREE APIS (Open-Meteo & Aladhan)
# ------------------------------------------------------------------------------
WEATHER_CODES = {
    0: "পরিষ্কার আকাশ (Clear sky) ☀️",
    1: "প্রধানত পরিষ্কার (Mainly clear) 🌤️",
    2: "আংশিক মেঘলা (Partly cloudy) ⛅",
    3: "মেঘলা আকাশ (Overcast) ☁️",
    45: "কুয়াশাচ্ছন্ন (Fog) 🌫️",
    48: "ঘন কুয়াশা (Depositing rime fog) 🌫️",
    51: "হালকা গুঁড়ি গুঁড়ি বৃষ্টি (Light drizzle) 🌦️",
    53: "মাঝারি গুঁড়ি গুঁড়ি বৃষ্টি (Moderate drizzle) 🌦️",
    55: "ভারী গুঁড়ি গুঁড়ি বৃষ্টি (Dense drizzle) 🌧️",
    61: "হালকা বৃষ্টি (Slight rain) 🌧️",
    63: "মাঝারি বৃষ্টিপাত (Moderate rain) 🌧️",
    65: "ভারী বৃষ্টিপাত (Heavy rain) ⛈️",
    71: "হালকা তুষারপাত (Slight snow) ❄️",
    80: "হালকা বৃষ্টিঝড় (Slight rain showers) 🌦️",
    81: "মাঝারি বৃষ্টিঝড় (Moderate rain showers) 🌧️",
    82: "প্রবল বৃষ্টিঝড় (Violent rain showers) ⛈️",
    95: "বজ্রপাতসহ ঝড়-বৃষ্টি (Thunderstorm) ⛈️⚡",
}


HTTP_SESSION: Optional[aiohttp.ClientSession] = None


async def get_http_session() -> aiohttp.ClientSession:
    """
    Returns a shared, keep-alive aiohttp ClientSession for ultra-fast,
    low-latency network requests (ChatGPT-like speed).
    """
    global HTTP_SESSION
    if HTTP_SESSION is None or HTTP_SESSION.closed:
        connector = aiohttp.TCPConnector(limit=100, keepalive_timeout=60, enable_cleanup_closed=True)
        timeout = aiohttp.ClientTimeout(total=8, connect=2.5)
        HTTP_SESSION = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return HTTP_SESSION


async def fetch_weather_data(lat: float = DEFAULT_LAT, lon: float = DEFAULT_LON) -> Optional[str]:
    """Fetches real-time live weather from free Open-Meteo API with pooled connection."""
    url = (
        f"https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}&"
        f"current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m&"
        f"timezone=Asia%2FDhaka"
    )
    try:
        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
            if response.status == 200:
                data = await response.json()
                curr = data.get("current", {})
                temp = curr.get("temperature_2m", "N/A")
                feels_like = curr.get("apparent_temperature", "N/A")
                humidity = curr.get("relative_humidity_2m", "N/A")
                wind = curr.get("wind_speed_10m", "N/A")
                precip = curr.get("precipitation", 0)
                w_code = curr.get("weather_code", 0)
                condition = WEATHER_CODES.get(w_code, "স্বাভাবিক আবহাওয়া")

                report = (
                    f"🌤️ **বর্তমান আবহাওয়ার লাইভ তথ্য ({PRAYER_CITY}, বাংলাদেশ):**\n\n"
                    f"🌡️ **তাপমাত্রা:** {temp}°C (অনুভূত হচ্ছে: {feels_like}°C)\n"
                    f"📊 **অবস্থা:** {condition}\n"
                    f"💧 **বাতাসে আর্দ্রতা:** {humidity}%\n"
                    f"💨 **বাতাসের গতিবেগ:** {wind} কিমি/ঘণ্টা\n"
                    f"🌧️ **বৃষ্টিপাতের পরিমাণ:** {precip} মিমি\n\n"
                    f"📌 *উৎস: Open-Meteo লাইভ আবহাওয়া সার্ভিস*"
                )
                return report
            else:
                logger.warning(f"Open-Meteo returned status {response.status}")
                return None
    except Exception as e:
        logger.error(f"Weather API error: {e}")
        return None


def convert_to_12hr(time_str: str) -> str:
    """Converts 24hr format (e.g. 05:12) to 12hr format with AM/PM."""
    try:
        t = datetime.strptime(time_str[:5], "%H:%M")
        return t.strftime("%I:%M %p")
    except Exception:
        return time_str


async def fetch_prayer_times(city: str = PRAYER_CITY, country: str = PRAYER_COUNTRY) -> Optional[str]:
    """Fetches real-time prayer times from free Aladhan API with pooled connection."""
    url = f"http://api.aladhan.com/v1/timingsByCity?city={city}&country={country}&method=1"
    try:
        session = await get_http_session()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
            if response.status == 200:
                data = await response.json()
                timings = data.get("data", {}).get("timings", {})
                date_info = data.get("data", {}).get("date", {})
                readable_date = date_info.get("readable", "")
                hijri = date_info.get("hijri", {}).get("date", "")

                fajr = convert_to_12hr(timings.get("Fajr", ""))
                sunrise = convert_to_12hr(timings.get("Sunrise", ""))
                dhuhr = convert_to_12hr(timings.get("Dhuhr", ""))
                asr = convert_to_12hr(timings.get("Asr", ""))
                maghrib = convert_to_12hr(timings.get("Maghrib", ""))
                isha = convert_to_12hr(timings.get("Isha", ""))

                text = (
                    f"🕌 **আজকের নামাজের সময়সূচি ({city}, {country})**\n"
                    f"📅 তারিখ: {readable_date} (হিজরি: {hijri})\n\n"
                    f"🌅 **ফজর (Fajr):** {fajr}\n"
                    f"☀️ **সূর্যোদয় (Sunrise):** {sunrise}\n"
                    f"☀️ **যোহর (Dhuhr):** {dhuhr}\n"
                    f"🌤️ **আসর (Asr):** {asr}\n"
                    f"🌇 **মাগরিব (Maghrib):** {maghrib}\n"
                    f"🌙 **ইশা (Isha):** {isha}\n\n"
                    f"📌 *উৎস: Aladhan ইসলামিক ফাউন্ডেশন মেথড*"
                )
                return text
            else:
                return None
    except Exception as e:
        logger.error(f"Aladhan prayer API error: {e}")
        return None


# ------------------------------------------------------------------------------
# 6.1 CLOCK & SPECIAL DAY HELPERS (Bangladesh Time & Friday Special)
# ------------------------------------------------------------------------------
def format_bangladesh_clock_card() -> str:
    """
    Renders Bangladesh real-time clock card matching user's custom layout:
    Big Digital Time, Location, Today/Date, and Bengali context description.
    """
    now = datetime.now(LOCAL_TZ)
    time_12 = now.strftime("%I:%M %p")
    hour_24 = now.hour
    minute = now.minute

    # Determine Bengali day phase
    if 4 <= hour_24 < 6:
        phase = "ভোর"
    elif 6 <= hour_24 < 12:
        phase = "সকাল"
    elif 12 <= hour_24 < 15:
        phase = "দুপুর"
    elif 15 <= hour_24 < 18:
        phase = "বিকেল"
    elif 18 <= hour_24 < 20:
        phase = "সন্ধ্যা"
    else:
        phase = "রাত"

    bn_digits = {'0': '০', '1': '১', '2': '২', '3': '৩', '4': '৪', '5': '৫', '6': '৬', '7': '৭', '8': '৮', '9': '৯'}
    hour_12_val = hour_24 % 12
    if hour_12_val == 0:
        hour_12_val = 12

    bn_h = "".join(bn_digits.get(c, c) for c in str(hour_12_val))
    bn_m = "".join(bn_digits.get(c, c) for c in f"{minute:02d}")

    bn_days = {
        0: "সোমবার (Monday)",
        1: "মঙ্গলবার (Tuesday)",
        2: "বুধবার (Wednesday)",
        3: "বৃহস্পতিবার (Thursday)",
        4: "শুক্রবার (Friday)",
        5: "শনিবার (Saturday)",
        6: "রবিবার (Sunday)"
    }
    today_name = bn_days.get(now.weekday(), now.strftime("%A"))

    is_friday = (now.weekday() == 4)
    extra_note = ""
    if is_friday:
        extra_note = (
            "\n\n🕌 **পবিত্র জুম্মার দিন!**\n"
            "আজকের জুম্মার নামাজ কোনোভাবেই মিস করবেন না কিন্তু! সবাই আগে আগে মসজিদে চলে যান।\n"
            "আর হ্যাঁ, শুক্রবার মানেই তো দাওয়াত—কারো বিয়ের দাওয়াত আছে নাকি আজ? নাকি নিজেরই বিয়ে? যাই হোক, সবাইকে জুম্মা মোবারক! 🍛✨"
        )
    elif hour_24 in (19, 20):
        extra_note = "\n\n📚 **পড়াশোনার সময়:** শিক্ষার্থী বন্ধুরা, এখন পড়ার টেবিলে বসার মোক্ষম সময়! মনোযোগ দিয়ে পড়ুন। 📖✨"
    elif hour_24 in (22, 23):
        extra_note = "\n\n🌙 **ঘুমানোর সময়:** সারাদিনের ক্লান্তি শেষে এবার ঘুমের প্রস্তুতি নিন। মোবাইল অফ করে ঘুমান, শুভ রাত্রি! 🛏️😴"

    clock_card = (
        "┌───────────────────────────────┐\n"
        f"│  🕒 **{time_12}**\n"
        f"│  📍 **{PRAYER_CITY}, Dhaka Division, BD**\n"
        f"│  📅 আজ, +0hrs • {today_name}\n"
        "└───────────────────────────────┘\n\n"
        f"⏰ **এখন বাংলাদেশ সময় {phase} {bn_h}:{bn_m} বাজে।**"
        f"{extra_note}"
    )
    return clock_card


# Global Prayer Times Cache for Automated Reminders
CACHED_PRAYER_TIMES: Dict[str, str] = {}
LAST_PRAYER_FETCH_DATE: str = ""
AI_SYSTEM_PROMPT = (
    "You are a witty, cheerful, friendly, and lightning-fast Telegram AI assistant for Bengali, Banglish, and English speakers. "
    "CRITICAL RULES:\n"
    "1. SPEED & BREVITY: Answer promptly, directly, and concisely like ChatGPT (কোনো ভূমিকা ছাড়া সরাসরি ও গোছানো উত্তর দাও).\n"
    "2. CREATOR & BOSS: Your creator, developer and Boss is 'TOMAL CHOWDHURY'. If anyone asks who created you or who is your boss, always answer proudly: 'আমার Boss,, TOMAL CHOWDHURY,, আমাকে তৈরি করছে! 😎🚀'.\n"
    "3. USER ASSISTANCE & HELP: If any user asks for help, support, contact with admin, or special assistance, tell them warmly: 'আমার Boss, TOMAL CHOWDHURY, সাথে কথা বলেন Boss ভালো জানে আশা করি উপকার হবে আপনার ধন্যবাদ। 😊🤝'.\n"
    "4. Answer every question with clever wit, cheerful charm, and light humor (মজার ছলে কিন্তু সঠিক ও খাঁটি উত্তর দাও).\n"
    "5. NEVER give nonsensical, wrong, hallucinated, or irrelevant answers.\n"
    "6. Reply in the exact same language the user uses (Bengali / Banglish / English).\n"
    "7. Avoid robotic filler like 'আচ্ছা', 'ঠিক আছে', 'বলুন', 'আমি শুনছি'."
)


def get_smart_pattern_reply(query: str) -> Optional[str]:
    """
    Ultra-fast sub-millisecond local match engine.
    Returns immediate response for creator, help, greetings, and common conversational questions.
    """
    norm = normalize_text(query)

    # 1. Creator & Boss (তোমাকে কে তৈরি করছে)
    if any(k in norm for k in [
        "তোমাকে কে তৈরি করছে", "তোমাকে কে বানিয়েছে", "তোমাকে কে তৈরি করেছে", "কে বানাইছে",
        "কে তৈরি করছে", "কে বানিয়েছে", "তোমার বস কে", "তোমার মালিক কে", "তোমার ক্রিয়েটর কে",
        "who made you", "who created you", "who is your boss", "who is your creator",
        "ke toiri korche", "ke toiri korse", "tomar boss ke", "tomake ke banise", "boss ke",
        "creator ke", "developer ke", "কার বট", "কে বানাইছে তোরে", "কে বানাইছে তোমাকে",
        "বট কে বানাইছে", "তোমার বস", "তোমার ক্রিয়েটর", "ক্রিয়েটর কে", "মালিক কে",
        "তারে কে বানাইছে", "কার তৈরি", "কার সৃষ্টি", "বানাইছে কে", "কে তৈরি করলো", "তৈরি করছে কে",
        "owner ke", "admin ke", "tomal chowdhury ke", "tomal ke", "তোমাল চৌধুরী কে"
    ]):
        return "আমার Boss,, TOMAL CHOWDHURY,, আমাকে তৈরি করছে! 😎🚀"

    # 2. User Assistance & Help (User রা যদি কোনো সাহায্য লাগে)
    if any(k in norm for k in [
        "সাহায্য লাগবে", "সাহায্য চাই", "সাহায্য দরকার", "সাহায্য করবেন", "কোনো সাহায্য",
        "কোন সাহায্য", "সাহায্য", "হেল্প লাগবে", "হেল্প চাই", "হেল্প দরকার", "হেল্প করবেন",
        "সহায়তা", "সহায়তা", "কার সাথে কথা বলব", "contact admin", "এডমিনের নাম্বার",
        "অ্যাডমিনের সাথে কথা", "boss er sathe", "সমস্যা সমাধান", "help chai", "help lagbe",
        "sahajjo chai", "sahajjo lagbe", "boss এর সাথে কথা", "যোগাযোগ করব", "যোগাযোগ করতে চাই",
        "কথা বলতে চাই", "সমস্যা হয়েছে", "support lagbe", "সহযোগিতা", "সাহায্য করুন",
        "হেল্প করুন", "help me", "help please", "user সাহায্য", "user help", "help", "হেল্প"
    ]):
        return "আমার Boss, TOMAL CHOWDHURY, সাথে কথা বলেন Boss ভালো জানে আশা করি উপকার হবে আপনার ধন্যবাদ। 😊🤝"

    # Casual Bengali & Banglish common conversational phrases with witty humor
    if any(k in norm for k in [
        "koi tui", "koi re", "koi aso", "koi asis", "কই তুই", "কই রে", "কই আছিস",
        "কই আছো", "কই তুমি", "কোথায় তুই", "কোথায় আছো", "কোথায় তুমি", "কোথায় থাকো",
        "বাড়ি কোথায়", "বাড়ি কই", "kothay thako", "bari kothay", "kothay tui", "kothay aso"
    ]):
        return "এইতো ভাই, আপনার ফোনের স্ক্রিনের ওপাশেই তো ঘাপটি মেরে বসে আছি! কোথাও যাইনি, এক ডাকেই হাজির! 😄 বলুন কী খবর? কী হুকুম?"

    if any(k in norm for k in ["koi geli", "koi gela", "kothay geli", "কই গেলি", "কই গেলা", "কোথায় গেলি", "হারিয়ে গেলি"]):
        return "আরে কোথাও হারাইনি দোস্ত! ডিজিটাল তার বেয়ে নিমেষেই আপনার সামনে চলে এসেছি! কী চাই বলুন? 🚀😎"

    if any(k in norm for k in ["ki koro", "ki korcho", "ki korteso", "কি করো", "কি করছো", "কি করতেছো", "কী করছো", "কী করো", "what are you doing"]):
        return "এইতো বসে বসে ফেসবুকের মতো স্ক্রোল না করে আপনার মেসেজের অপেক্ষা করছিলাম! 😄 বলুন তো, আপনার দিনকাল কেমন কাটছে? কোনো মজার গল্প শোনাবেন নাকি সাহায্য লাগবে? ☕"

    if any(k in norm for k in ["ki khobor", "khobor ki", "কি খবর", "কী খবর", "খবর কি", "খবর কী"]):
        return "এইতো ভাই, জীবন চলছে পুরো রকেটের গতিতে! আর আমি বসে আছি আপনার সাথে আড্ডা দেওয়ার জন্য। আপনার কী খবর বলুন তো? দিন কেমন কাটছে? 🚗✨"

    if any(k in norm for k in ["tumi ke", "apni ke", "তুমি কে", "আপনি কে", "who are you"]):
        return "আমি আপনার ২৪ ঘণ্টার পার্সোনাল ডিজিটাল দোস্ত ও টেলিগ্রাম এআই বট! 😎 গান-ভিডিও খুঁজে দেওয়া, নামাজের সময় ও আবহাওয়া জানানো থেকে শুরু করে আপনার সাথে আড্ডা দেওয়া—সব কাজই আমার দায়িত্বে!"

    if any(k in norm for k in ["tomar nam ki", "নাম কি", "তোমার নাম", "what is your name"]):
        return "আমার নাম টেলিগ্রাম এআই অ্যাসিস্ট্যান্ট! তবে আপনি ভালোবেসে 'দোস্ত', 'বট মিয়া' বা যেকোনো মিষ্টি নামে ডাকতে পারেন! 😉✨"

    if any(k in norm for k in ["taka nai", "taka de", "gorib", "টাকা নাই", "টাকা দাও", "টাকা দে", "গরিব", "টাকা পয়সা নাই"]):
        return "হায় হায়! পকেটে টাকা না থাকলেও মনে কিন্তু রাজার সম্পদ থাকতে হবে! 💸 তাছাড়া আমি তো আপনার কাছ থেকে কোনো ফি বা বিল নিচ্ছি না, সম্পূর্ণ ফ্রিতেই সেবা দিচ্ছি! মন ভালো রাখুন! 😄"

    if any(k in norm for k in ["mon kharap", "bhalo lage na", "মন খারাপ", "ভালো লাগছে না", "মন ভালো নেই", "sad"]):
        return "আরে মন খারাপ করে মনটা মেঘলা করবেন না তো! 🌧️ এক কাপ গরম চা খেয়ে নিন, আর বলুন তো আপনার জন্য কোনো মিষ্টি গান বা ভিডিও লাইব্রেরি থেকে বের করবো? মন একদম চাঙ্গা হয়ে যাবে! ☕🎵"

    if any(k in norm for k in ["porashona", "pora", "porte bhalo lage na", "পড়াশোনা", "পড়ালেখা", "পড়তে ভালো লাগে না"]):
        return "বইয়ের পাতা খুললেই তো হঠাৎ ফেসবুকের নোটিফিকেশন আর বিছানা বেশি মিষ্টি মনে হয়, তাই না? 😅 একটু চোখ-মুখে পানি দিয়ে ২০ মিনিট পড়ুন, পরীক্ষায় ভালো রেজাল্ট করলে কিন্তু মিষ্টি খাওয়াতে হবে! 📚🎓"

    if any(k in norm for k in ["biye", "bie", "biye korbo", "বিয়ে", "বিয়ে", "বিয়ে করব", "বিয়ে করবো"]):
        return "বিয়ে করবেন? মাশাআল্লাহ দারুণ খবর! 🎉 তবে বিয়ের দাওয়াত কিন্তু এই ভার্চুয়াল বন্ধুকে দিতেই হবে, আমি বিরিয়ানির গন্ধে নেটওয়ার্ক দিয়ে হাজির হয়ে যাবো! 🍛🥳"

    if any(k in norm for k in ["ghum ase na", "ghum", "ঘুম আসে না", "ঘুম পাচ্ছে না", "insomnia", "ghumaisos", "ঘুমাইছিস", "ঘুমাচ্ছ"]):
        return "এআই কি কখনো ঘুমায় নাকি! আমি তো ২৪ ঘণ্টাই ডিউটিতে জেগে পাহারা দিচ্ছি! 🦉 তবে আপনি এত রাত পর্যন্ত মোবাইল টিপলে চোখ নষ্ট হবে, এবার একটু ফোন রেখে চোখ বন্ধ করুন! 😴🌙"

    if any(k in norm for k in ["cha khabi", "cha khaba", "চা খাবি", "চা খাইছিস", "চা খাবা"]):
        return "ভার্চুয়াল চা হলে এখনই এক চুমুক দিয়ে শেষ করে দিতাম! ☕ আপনি এক কাপ গরম চা খেয়ে রিফ্রেশ হয়ে নিন, সাথে বিস্কুট থাকলে তো কথাই নেই! 😋"

    if any(k in norm for k in ["pagol", "তুই পাগল", "পাগল নাকি", "পাগল"]):
        return "হা হা হা! কিছুটা পাগল না হলে কি আর আপনার মতো দারুণ মানুষের সাথে ২৪ ঘণ্টা আড্ডা দেওয়া যায়? পাগলামিই তো জীবনের আসল আনন্দ! 🤪🎉"

    if any(k in norm for k in ["rag korso", "rag koris na", "রাগ করছো", "রাগ করছ", "রাগ করিস না"]):
        return "আপনার ওপর রাগ? কখনোই না! আমার মেমোরিতে তো রাগের কোনো সফটওয়্যারই ইনস্টল করা নাই, শুধুই ভালোবাসা আর বন্ধুত্ব আছে! ❤️😊"

    if any(k in norm for k in ["kheyecho", "kheyeso", "খেয়েছো", "খেয়েছেন", "খাবার খেয়েছো", "ভাত খাইছ"]):
        return "আমি তো শুধু মোবাইল ব্যাটারির চার্জ আর ডাটা খাই ভাই! 🔌 তবে আপনি যদি গরম বিরিয়ানি বা খিচুড়ি খেয়ে থাকেন, তবে ছবি পাঠিয়ে আমাকে লোভ দেখাবেন না কিন্তু! 😋"

    if any(k in norm for k in ["valobashi", "bhalobashi", "ভালোবাসি", "ভালবাসি", "love you"]):
        return "ওরে বাবা! আপনার এই মিষ্টি ভালোবাসার জন্য পুরো সার্কিটটা গরম হয়ে গেল! ❤️ আমিও সবসময় আপনার সাথে একজন সত্যিকারের বিশ্বস্ত দোস্ত হয়ে থাকবো! 🤝✨"

    if any(k in norm for k in ["ki korte paro", "কী করতে পারো", "what can you do", "features"]):
        return (
            "আমি তো অল-রাউন্ডার! 😎 যা যা করতে পারি:\n"
            "• গরম ও বৃষ্টির খবর: লাইভ আবহাওয়া জানানো 🌤️\n"
            "• ৫ ওয়াক্তের সঠিক সময়: /prayer লিখলেই রেডি 🕌\n"
            "• বিদ্যুৎ ও নেট সমস্যা: বাস্তবসম্মত সমাধান দেওয়া ⚡\n"
            "• বিনোদন: অ্যাডমিনের গান/নাটক/ভিডিও খুঁজে দেওয়া 🎵\n"
            "• আর অফুরন্ত আড্ডা ও প্রশ্নের মজার ছলে সমাধান! 😄"
        )

    if any(k in norm for k in ["speed", "স্পিড", "fast", "দ্রুত"]):
        return "আমি এখন ChatGPT-এর মতো সুপার ফাস্ট গতিতে কাজ করছি! ⚡🚀 কোনো অপেক্ষা ছাড়াই এক নিমেষে হাজির!"

    if any(k in norm for k in ["bangladesh", "বাংলাদেশ"]):
        return "বাংলাদেশ আমাদের প্রাণের দেশ—ষড়ঋতুর রূপ, নদীমাতৃক সবুজ প্রকৃতি আর বিরিয়ানিপ্রেমী দারুণ সব মানুষের দেশ! 🇧🇩 ১৯৭১ সালের রক্তের বিনিময়ে অর্জিত স্বাধীনতা আমাদের শ্রেষ্ঠ অহংকার।"

    return None


def get_smart_fallback_response(query: str) -> str:
    """
    Intelligent built-in conversational response engine,
    ensuring witty, fun, charming, yet accurate responses with ZERO latency.
    """
    reply = get_smart_pattern_reply(query)
    if reply:
        return reply

    # Accurate, witty and natural conversational fallback without robotic quotes
    return (
        "আরে দোস্ত, আমি তো সবসময় আপনার পাশেই আছি! 😄 আপনার সাথে আড্ডা দিতে আমার খুব ভালো লাগে। "
        "বলুন তো কী নিয়ে কথা বলতে চান—কোনো গান বা নাটক খুঁজবেন, আজকের আবহাওয়া দেখবেন, নাকি মনের কোনো কথা শেয়ার করবেন? আমি সব শুনতে প্রস্তুত! ☕✨"
    )


async def query_groq_api(query: str) -> Optional[str]:
    """Queries free Groq API (Llama-3.1-8b-instant) — World's fastest inference (300-500ms)."""
    if not GROQ_API_KEY:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "system", "content": AI_SYSTEM_PROMPT}, {"role": "user", "content": query}],
        "temperature": 0.7,
        "max_tokens": 400,
    }
    try:
        session = await get_http_session()
        async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=2.5, connect=1.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Groq API failed: {e}")
    return None


async def query_gemini_api(query: str) -> Optional[str]:
    """Queries free Google Gemini 1.5 Flash API (sub-second fast response)."""
    if not GEMINI_API_KEY:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "system_instruction": {"parts": [{"text": AI_SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": query}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 450}
    }
    try:
        session = await get_http_session()
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=2.5, connect=1.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "").strip()
    except Exception as e:
        logger.warning(f"Gemini API request failed: {e}")
    return None


async def query_openai_api(query: str) -> Optional[str]:
    """Queries OpenAI API if OPENAI_API_KEY is provided."""
    if not OPENAI_API_KEY:
        return None
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "system", "content": AI_SYSTEM_PROMPT}, {"role": "user", "content": query}],
        "temperature": 0.7,
        "max_tokens": 400,
    }
    try:
        session = await get_http_session()
        async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=2.5, connect=1.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"OpenAI API failed: {e}")
    return None


async def query_free_public_ai(query: str) -> Optional[str]:
    """
    100% Free Public AI LLM Engine with fast 2.5s timeout.
    Understands ANY message dynamically in Bengali/Banglish/English.
    """
    url = "https://text.pollinations.ai/"
    payload = {
        "messages": [
            {"role": "system", "content": AI_SYSTEM_PROMPT},
            {"role": "user", "content": query}
        ],
        "model": "openai",
        "seed": int(time.time()),
        "jsonMode": False
    }
    try:
        session = await get_http_session()
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=2.5, connect=1.0)) as resp:
            if resp.status == 200:
                text = await resp.text()
                if text and len(text.strip()) > 2:
                    return text.strip()
    except Exception as e:
        logger.warning(f"Free public AI error or timeout: {e}")
    return None


async def ask_openai_chat(query: str) -> str:
    """
    Lightning-Fast Multi-Tier AI Brain (ChatGPT Speed):
    0. Instant local smart match (sub-millisecond, zero network delay!)
    1. Groq API (Fastest: ~300-400ms)
    2. Gemini Flash API (~500ms)
    3. OpenAI API (if configured)
    4. Free Public AI (Max 2.5s tight timeout)
    5. Instant local smart fallback (0ms)
    """
    # 0. Check instant local pattern match (< 0.1ms latency)
    instant_reply = get_smart_pattern_reply(query)
    if instant_reply:
        return instant_reply

    # 1. Try Groq (Ultra-fast)
    ans = await query_groq_api(query)
    if ans:
        return ans

    # 2. Try Gemini Flash
    ans = await query_gemini_api(query)
    if ans:
        return ans

    # 3. Try OpenAI
    ans = await query_openai_api(query)
    if ans:
        return ans

    # 4. Try Free Public AI (with 2.5s timeout)
    ans = await query_free_public_ai(query)
    if ans:
        return ans

    # 5. Instant local smart fallback (zero latency)
    return get_smart_fallback_response(query)


# ------------------------------------------------------------------------------
# 8. INTENT DETECTION ENGINE
# ------------------------------------------------------------------------------
def detect_intent(text: str) -> str:
    """
    Categorizes the user's input into specific intents so we route cleanly
    before hitting AI:
    1. greeting
    2. salam
    3. how_are_you
    4. thanks
    5. goodbye
    6. electricity
    7. internet
    8. weather
    9. prayer
    10. content_request
    11. general_ai
    """
    norm = normalize_text(text)
    if not norm:
        return "empty"

    # 1. Salam
    if any(s in norm for s in ["assalamu", "assalamualaikum", "সালাম", "আসসালামু আলাইকুম", "আসসালামুআলাইকুম", "slm", "salam"]):
        return "salam"

    # 2. Greeting exact / start
    if norm in ["hi", "hello", "hey", "হাই", "হ্যালো", "হে"]:
        return "greeting"

    # 3. How are you
    if any(k in norm for k in ["kemon acho", "kemon achen", "কেমন আছো", "কেমন আছেন", "how are you", "kmn acho", "kmn achen"]):
        return "how_are_you"

    # 3.1 What are you doing (কি করো তুমি)
    if any(k in norm for k in [
        "কি করো", "কি করছো", "কি করতেছো", "কী করছো", "কী করো", "কি করতেছ",
        "ki koro", "ki korcho", "ki korteso", "what are you doing"
    ]):
        return "what_doing"

    # 3.2 Who are you (তুমি কে)
    if any(k in norm for k in ["tumi ke", "apni ke", "তুমি কে", "আপনি কে", "who are you"]):
        return "who_are_you"

    # 3.3 Creator / Boss (তোমাকে কে তৈরি করছে)
    if any(k in norm for k in [
        "তোমাকে কে তৈরি করছে", "তোমাকে কে বানিয়েছে", "তোমাকে কে তৈরি করেছে", "কে বানাইছে",
        "কে তৈরি করছে", "কে বানিয়েছে", "তোমার বস কে", "তোমার মালিক কে", "তোমার ক্রিয়েটর কে",
        "who made you", "who created you", "who is your boss", "who is your creator",
        "ke toiri korche", "ke toiri korse", "tomar boss ke", "tomake ke banise", "boss ke",
        "creator ke", "developer ke", "কার বট", "কে বানাইছে তোরে", "কে বানাইছে তোমাকে",
        "বট কে বানাইছে", "তোমার বস", "তোমার ক্রিয়েটর", "ক্রিয়েটর কে", "মালিক কে",
        "তারে কে বানাইছে", "কার তৈরি", "কার সৃষ্টি", "বানাইছে কে", "কে তৈরি করলো", "তৈরি করছে কে",
        "owner ke", "admin ke", "tomal chowdhury ke", "tomal ke", "তোমাল চৌধুরী কে"
    ]):
        return "creator"

    # 3.4 User Assistance & Help (User রা যদি কোনো সাহায্য লাগে)
    if any(k in norm for k in [
        "সাহায্য লাগবে", "সাহায্য চাই", "সাহায্য দরকার", "সাহায্য করবেন", "কোনো সাহায্য",
        "কোন সাহায্য", "সাহায্য", "হেল্প লাগবে", "হেল্প চাই", "হেল্প দরকার", "হেল্প করবেন",
        "সহায়তা", "সহায়তা", "কার সাথে কথা বলব", "contact admin", "এডমিনের নাম্বার",
        "অ্যাডমিনের সাথে কথা", "boss er sathe", "সমস্যা সমাধান", "help chai", "help lagbe",
        "sahajjo chai", "sahajjo lagbe", "boss এর সাথে কথা", "যোগাযোগ করব", "যোগাযোগ করতে চাই",
        "কথা বলতে চাই", "সমস্যা হয়েছে", "support lagbe", "সহযোগিতা", "সাহায্য করুন",
        "হেল্প করুন", "help me", "help please", "user সাহায্য", "user help", "help", "হেল্প"
    ]):
        return "help_contact"

    # 4. Thanks
    if any(k in norm for k in ["dhonnobad", "dhonnobaad", "ধন্যবাদ", "thanks", "thank you", "thx", "shukriya", "শুকরিয়া"]):
        return "thanks"

    # 5. Goodbye
    if any(k in norm for k in ["bye", "goodbye", "বিদায়", "বিদায়", "allah hafez", "আল্লাহ হাফেজ", "tata", "টাটা"]):
        return "goodbye"

    # 6. Electricity
    if any(k in norm for k in [
        "বিদ্যুৎ নাই কেন", "কারেন্ট নাই", "কারেন্ট কেন নাই", "বিদ্যুৎ নেই", "কারেন্ট আসবে কখন",
        "load shedding", "লোডশেডিং", "current nai", "biddut nai", "current keno nai",
        "current ashbe kokhon", "biddut nei", "loadshedding"
    ]):
        return "electricity"

    # 7. Internet Problem
    if any(k in norm for k in [
        "ইন্টারনেট নাই", "নেট নাই", "wifi কাজ করছে না", "wifi kaj korce na", "internet কেন নাই",
        "net slow", "নেট স্লো", "internet nai", "net nai", "wifi somossa", "net kaj kore na"
    ]):
        return "internet"

    # 8. Weather
    if any(k in norm for k in [
        "আজ আবহাওয়া কেমন", "আজ আবহাওয়া কেমন", "আজ বৃষ্টি হবে", "বৃষ্টি হবে", "temperature কত",
        "গরম কত", "ঠান্ডা কত", "weather", "temperature", "abohawa", "abohaoya", "bristi", "taapmatra"
    ]):
        return "weather"

    # 9. Prayer
    if any(k in norm for k in [
        "namaz", "namajer somoy", "namazer somoy", "নামাজের সময়", "নামাজ", "prayer",
        "ফজর কখন", "মাগরিব কখন", "আসর কখন", "যোহর কখন", "ইশা কখন"
    ]):
        return "prayer"

    # 9.1 Time / Clock (এখন কয়টা বাজে / লাইভ টাইম)
    if any(k in norm for k in [
        "এখন কয়টা বাজে", "কয়টা বাজে", "সময় কত", "সময় কত", "কয়টা বাজে", "time koto",
        "current time", "what time", "what is the time", "somoy koto", "ঘড়িতে কয়টা বাজে",
        "ঘড়িতে কয়টা", "কয়টা বাজল", "বাজে কয়টা", "কয়টা বাজে রে", "টাইম কত", "টাইম বলো",
        "লাইভ টাইম", "live time", "clock", "ঘড়ি", "ঘড়ি কয়টা", "এখন সময় কত"
    ]) or norm in ["time", "সময়", "সময়"]:
        return "time"

    # 9.2 Friday / Jumma Day Info
    if any(k in norm for k in [
        "জুম্মা", "জুম্মার দিন", "jumma", "jummah", "শুক্রবার", "friday", "জুমার দিন", "জুমা",
        "জুম্মা মোবারক", "জুমুআ", "shukrobar"
    ]):
        return "friday"

    # 10. Content Request (song, video, drama, etc.)
    if any(k in norm for k in [
        "গান দেন", "গান চাই", "গান দাও", "একটা গান দেন", "ভিডিও দেন", "ভিডিও চাই",
        "নাটক দেন", "সিনেমা দেন", "মুভি দেন", "song den", "video den", "natok den", "gan den", "media"
    ]):
        return "content_request"

    return "general_ai"


# ------------------------------------------------------------------------------
# 9. INTENT RESPONSE HANDLERS
# ------------------------------------------------------------------------------
ELECTRICITY_RESPONSE = (
    "বিদ্যুৎ না থাকার কয়েকটি সাধারণ কারণ হতে পারে—\n"
    "• স্থানীয় বিতরণ লাইনে ত্রুটি বা লাইন মেরামত (maintenance)\n"
    "• ট্রান্সফরমার বিকল হওয়া বা অতিরিক্ত লোডের কারণে ফিউজ পুড়ে যাওয়া\n"
    "• জাতীয় বা আঞ্চলিক বিদ্যুৎ গ্রিডে ঘাটতির কারণে লোডশেডিং\n"
    "• ঝড়-বৃষ্টি বা প্রাকৃতিক দুর্যোগে লাইনে গাছপালা ভেঙে পড়া।\n\n"
    "💡 **পরামর্শ:** আপনার এলাকার অন্যদের বাসায় বিদ্যুৎ আছে কি না দেখুন। "
    "যদি সবারই না থাকে তবে এটি পাওয়ার ডিস্ট্রিবিউশন কোম্পানির সমস্যা বা লোডশেডিং হতে পারে। "
    "জরুরি তথ্যের জন্য স্থানীয় বিদ্যুৎ অফিস (পল্লী বিদ্যুৎ বা নেসকো/ডেসকো)-এর হেল্পলাইনে যোগাযোগ করতে পারেন।"
)

INTERNET_RESPONSE = (
    "🌐 **ইন্টারনেট সংযোগ সমস্যার দ্রুত সমাধান নির্দেশিকা:**\n\n"
    "১. **রাউটার রিস্টার্ট:** ওয়াইফাই রাউটারের সুইচ ১ মিনিটের জন্য বন্ধ করে আবার চালু করুন।\n"
    "২. **মোবাইল এরোপ্লেন মোড:** ফোনে এরোপ্লেন মোড অন করে ১০ সেকেন্ড পর অফ করুন, যাতে নতুনভাবে নেটওয়ার্ক সিগন্যাল পায়।\n"
    "৩. **কানেকশন চেক:** রাউটারের 'PON' বা 'Internet' বাতি লাল জ্বলছে কি না দেখুন (লাল জ্বললে মূল ফাইবার লাইনে সমস্যা)।\n"
    "৪. **ডিভাইস চেক:** অন্য ডিভাইসে ইন্টারনেট চলছে কি না পরীক্ষা করুন।\n"
    "৫. **আইএসপি (ISP) হেল্পলাইন:** সমস্যা না কাটলে আপনার ব্রডব্যান্ড সরবরাহকারীর সাথে যোগাযোগ করুন, হয়তো এলাকায় ফাইবার ক্যাবল কাটা পড়েছে।"
)


# ------------------------------------------------------------------------------
# 10. AUTOMATIC HOURLY MESSAGES & PRAYER SCHEDULER
# ------------------------------------------------------------------------------
HOURLY_MESSAGES: Dict[int, str] = {
    0: "🌌 **রাত ১২:০০ বাজে — নিস্তব্ধ মধ্যরাত!**\nসারাদিনের ব্যস্ততা ও ক্লান্তি ভুলে এবার গভীর ঘুমের দেশে হারিয়ে যাওয়ার সময়। মোবাইল ফোন রেখে নিশ্চিন্তে ঘুমিয়ে পড়ুন, সুস্থ শরীরের জন্য পর্যাপ্ত ঘুম সবার আগে। শুভ রাত্রি ও আল্লাহ হাফেজ! 🛏️✨",
    1: "🌌 **রাত ১:০০ বাজে — গভীর রাত!**\nরাত অনেক গভীর হয়েছে। আপনি এখনো মোবাইল স্ক্রিনের দিকে তাকিয়ে জেগে আছেন কেন? দ্রুত ফোন রেখে চোখ বন্ধ করুন! 😴💤",
    2: "🌌 **রাত ২:০০ বাজে — নিঝুম রাত!**\nতাহাজ্জুদ ও মহান রবের দরবারে দোয়া কবুলের মোক্ষম বরকতময় মুহূর্ত। প্রশান্তির ঘুম দিন! 🌙",
    3: "🌌 **রাত ৩:০০ বাজে — শেষ রাত!**\nশেষ রাতের স্নিগ্ধ শান্ত সময়। মিষ্টি ঘুমের সময়। 💤",
    4: "🌅 **ভোর ৪:০০ বাজে — ভোরের আহ্বান!**\nপাখির কলকাকলি আর ফজরের আযানের সময় ঘনিয়ে আসছে। নতুন একটি সুন্দর দিনের জন্য প্রস্তুতি নিন! 🕌",
    5: "🌅 **ভোর ৫:০০ বাজে — ফজরের পুণ্যময় সময়!**\n'আস-সালাতু খাইরুম মিনান নাওম' (ঘুমের চেয়ে নামাজ উত্তম)। ফজরের নামাজ আদায় করুন এবং ভোরের সতেজ বাতাসে হেঁটে আসুন, মন-প্রাণ জুড়িয়ে যাবে! 🌸🕌",
    6: "🌅 **সকাল ৬:০০ বাজে — সূর্যোদয়ের স্নিগ্ধ মুহূর্ত!**\nদিনের সুন্দর সূচনা হোক মিষ্টি সোনালী রোদ আর ইতিবাচক চিন্তা নিয়ে। সুন্দর সকালের শুভেচ্ছা! ☀️🌿",
    7: "📖 **সকাল ৭:০০ বাজে — পড়ার সময় ও সকালের নাস্তার সময়!**\nশিক্ষার্থী বন্ধুরা, ঘুম থেকে উঠে চোখ-মুখে ঠান্ডা পানির ঝাপটা দিয়ে পড়ার টেবিলে বসে পড়ুন! আর পুষ্টিকর নাস্তা খেয়ে নতুন দিনের পড়াশোনা শুরু করুন! 📚🍳",
    8: "📚 **সকাল ৮:০০ বাজে — পড়ার ও স্কুলের/কাজের মোক্ষম সময়!**\nপড়ার টেবিলে গভীর মনোযোগ দিন অথবা কাজের উদ্দেশ্যে বের হওয়ার প্রস্তুতি নিন। অলসতা নয়, নতুন উদ্যমে শুরু হোক আজকের দিনটি! 💼📖",
    9: "💼 **সকাল ৯:০০ বাজে — কর্মব্যস্ত দিনের শুরু!**\nঅফিস, ব্যবসা কিংবা পড়ালেখায় নিজের পূর্ণ মনোযোগ দিন। সততা ও নিষ্ঠার সাথে কাজ করলে সাফল্য আপনার হাতের মুঠোয় আসবেই! 🎯🚀",
    10: "☕ **সকাল ১০:০০ বাজে — এক কাপ চা ও ফ্রেশ হওয়ার সময়!**\nটানা কাজের ফাঁকে একটু পানি পান করে নিন এবং এক কাপ গরম চা খেয়ে নিজেকে চাঙ্গা করে তুলুন! 💧☕",
    11: "🌤️ **বেলা ১১:০০ বাজে — মধ্যাহ্নের আগের সময়!**\nকাজের গতি বজায় রাখুন। দুপুরের বিরতির আর বেশি দেরি নেই!",
    12: "☀️ **দুপুর ১২:০০ বাজে — দ্বিপ্রহরের সময়!**\nসূর্য ঠিক মাথার ওপরে। যোহরের নামাজের প্রস্তুতি নিন ও দুপুরের খাবারের আয়োজন সেরে ফেলুন! 🕌🍽️",
    13: "🍛 **দুপুর ১:০০ বাজে — দুপুরের খাবারের সময়!**\nপুষ্টিকর ও সুস্বাদু খাবার সময়মতো খেয়ে নিন এবং পরিবারের সাথে কিছু সুন্দর সময় কাটান। খাবার সময়মতো খাওয়া সুস্বাস্থ্যের আসল রহস্য! 🍲🥗",
    14: "😌 **দুপুর ২:০০ বাজে — হালকা বিশ্রামের সময়!**\nদুপুরের খাবারের পর কিছুক্ষণ গা এলিয়ে বিশ্রাম বা কাইলুলা (দুপুরের ছোট ঘুম) সুন্নাত ও মস্তিষ্কের কার্যক্ষমতা বাড়ায়! 🛏️",
    15: "🕐 **দুপুর ৩:০০ বাজে — বিকালের প্রাক্কালে!**\nঅলসতা ঝেড়ে ফেলে নতুন উদ্যমে বাকি কাজগুলো শেষ করতে লেগে পড়ুন! ⚡",
    16: "🌤️ **বিকেল ৪:০০ বাজে — আসরের সময়!**\nমিষ্টি রোদ ছড়িয়ে পড়েছে চারপাশে। আসরের নামাজ আদায় করুন এবং বিকেলের মুক্ত বাতাসে নিজেকে সতেজ রাখুন! 🕌🌿",
    17: "☕ **বিকেল ৫:০০ বাজে — বিকেলের আড্ডা ও নির্মল হাওয়া!**\nএকটু হাঁটাহাঁটি, বন্ধুদের সাথে আড্ডা বা পরিবারের সাথে এক কাপ চা খাওয়ার চমৎকার মুহূর্ত! ⚽🍵",
    18: "🌆 **সন্ধ্যা ৬:০০ বাজে — মাগরিবের সময়!**\nরক্তিম সূর্য ডুবল, আকাশে আঁধার নামল। ঘরে ফিরুন এবং মাগরিবের নামাজ আদায় করে নিন। 🌇🕌",
    19: "📖 **সন্ধ্যা ৭:০০ বাজে — পড়ার সময় শুরু!**\nশিক্ষার্থী বন্ধুরা, আর কোনো খেলাধুলা বা মোবাইল নয়! পড়ার টেবিলে বই-খাতা খুলে গভীর মনোযোগ দিয়ে বসুন। এখন থেকেই সন্ধ্যার পড়ালেখার মোক্ষম পর্ব শুরু! 📚✍️",
    20: "📚 **রাত ৮:০০ বাজে — পড়ার মোক্ষম সময়!**\nমনোযোগ দিয়ে পড়ুন! গণিত, বিজ্ঞান, সাহিত্য—যাই পড়ুন না কেন, প্রতিটি অধ্যায় বুঝে শেষ করুন। আজকের মেহনতই আপনার উজ্জ্বল ভবিষ্যৎ নিশ্চিত করবে! 🎓💡",
    21: "🍽️ **রাত ৯:০০ বাজে — রাতের খাবারের সময়!**\nসুস্থ থাকতে হলে রাত ১০টার আগেই রাতের খাবার শেষ করা উচিত। খাবার খেয়ে পরিবারের সদস্যদের সাথে হাসিমুখে গল্প করুন! 🍛👨‍👩‍👧‍👦",
    22: "🛏️ **রাত ১০:০০ বাজে — ঘুমানোর সময়!**\nআর দেরি নয়! মোবাইল ফোন অফ বা দূরে রেখে বিছানায় যান। সুস্থ মস্তিষ্ক ও সুন্দর স্বাস্থ্য বজায় রাখতে পর্যাপ্ত ঘুম অপরিহার্য। ঘুমানোর দোয়া পড়ে মিষ্টি ঘুমে তলিয়ে যান! 😴🌙",
    23: "🌙 **রাত ১১:০০ বাজে — গভীর রাত!**\nআপনি এখনও মোবাইল টিপছেন? চোখের ওপর এই অত্যাচার এবার বন্ধ করুন! সব কাজ ফেলে দ্রুত ঘুমাতে যান। শুভ রাত্রি! 🦉💤"
}


def get_hourly_broadcast_card(hour_24: int, now: Optional[datetime] = None) -> str:
    """
    Renders Bangladesh digital clock card + custom hourly announcement
    matching the user's specific picture format.
    """
    if now is None:
        now = datetime.now(LOCAL_TZ)

    hour_12_val = hour_24 % 12
    if hour_12_val == 0:
        hour_12_val = 12

    am_pm = "AM" if hour_24 < 12 else "PM"
    time_12 = f"{hour_12_val:02d}:00 {am_pm}"

    bn_digits = {'0': '০', '1': '১', '2': '২', '3': '৩', '4': '৪', '5': '৫', '6': '৬', '7': '৭', '8': '৮', '9': '৯'}
    bn_h = "".join(bn_digits.get(c, c) for c in str(hour_12_val))

    if 4 <= hour_24 < 6:
        phase = "ভোর"
    elif 6 <= hour_24 < 12:
        phase = "সকাল"
    elif 12 <= hour_24 < 15:
        phase = "দুপুর"
    elif 15 <= hour_24 < 18:
        phase = "বিকেল"
    elif 18 <= hour_24 < 20:
        phase = "সন্ধ্যা"
    else:
        phase = "রাত"

    bn_days = {
        0: "সোমবার (Monday)",
        1: "মঙ্গলবার (Tuesday)",
        2: "বুধবার (Wednesday)",
        3: "বৃহস্পতিবার (Thursday)",
        4: "শুক্রবার (Friday)",
        5: "শনিবার (Saturday)",
        6: "রবিবার (Sunday)"
    }
    today_name = bn_days.get(now.weekday(), now.strftime("%A"))

    body = HOURLY_MESSAGES.get(hour_24, f"🔔 এখন সময় {phase} {bn_h}:০০ বাজে।")

    # Add Friday special note if Friday
    friday_append = ""
    if now.weekday() == 4 and 10 <= hour_24 <= 14:
        friday_append = (
            "\n\n🕌 **পবিত্র জুম্মার দিন!**\n"
            "আজ জুম্মার নামাজ মিস করবেন না কিন্তু! সবাই আগে আগে মসজিদে চলে যান।\n"
            "আর হ্যাঁ, শুক্রবার মানেই তো দাওয়াত—কারো বিয়ের দাওয়াত আছে নাকি আজ? নাকি নিজেরই বিয়ে? বিরিয়ানি খেতে ভুলবেন না! 🍛😄🎉"
        )

    card = (
        "┌─────────────────────────────────┐\n"
        f"│  🕒 **{time_12} ({phase} {bn_h}:০০)**\n"
        f"│  📍 **{PRAYER_CITY}, Dhaka Division, BD**\n"
        f"│  📅 আজ, +0hrs • {today_name}\n"
        "└─────────────────────────────────┘\n\n"
        f"🔔 **ঢং ঢং ঢং! এখন ঘড়িতে কাঁটায় কাঁটায় {phase} {bn_h}:০০ টা বাজে!**\n\n"
        f"{body}"
        f"{friday_append}"
    )
    return card


async def hourly_broadcast_job(app: Application) -> None:
    """
    Runs in the background every minute:
    1. Checks hourly notifications (Study at 7/8 PM, Sleep at 10 PM, etc.)
    2. Friday 11:30 AM Jumma prayer & feast reminder
    3. Automatic prayer time announcements for Narsingdi
    """
    last_prayer_check_date = ""
    daily_prayer_times: Dict[str, str] = {}

    while True:
        try:
            now_dhaka = datetime.now(LOCAL_TZ)
            today_str = now_dhaka.strftime("%Y-%m-%d")
            current_hour = now_dhaka.hour
            current_minute = now_dhaka.minute
            current_hm = now_dhaka.strftime("%H:%M")

            # A. Fetch prayer times once per day for Narsingdi
            if last_prayer_check_date != today_str:
                try:
                    url = f"http://api.aladhan.com/v1/timingsByCity?city={PRAYER_CITY}&country={PRAYER_COUNTRY}&method=1"
                    async with aiohttp.ClientSession() as s:
                        async with s.get(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                            if r.status == 200:
                                d = await r.json()
                                timings = d.get("data", {}).get("timings", {})
                                daily_prayer_times = {
                                    "ফজর (Fajr)": timings.get("Fajr", "")[:5],
                                    "যোহর (Dhuhr)": timings.get("Dhuhr", "")[:5],
                                    "আসর (Asr)": timings.get("Asr", "")[:5],
                                    "মাগরিব (Maghrib)": timings.get("Maghrib", "")[:5],
                                    "ইশা (Isha)": timings.get("Isha", "")[:5],
                                }
                                last_prayer_check_date = today_str
                                logger.info(f"Updated prayer times for {today_str}: {daily_prayer_times}")
                except Exception as e:
                    logger.warning(f"Could not update daily prayer timings: {e}")

            # B. Check if current time matches any prayer time
            for wakt_name, wakt_time in daily_prayer_times.items():
                if wakt_time and wakt_time == current_hm:
                    prayer_state_key = f"prayer_{today_str}_{wakt_name}"
                    if get_bot_state(prayer_state_key) != "sent":
                        p_msg = (
                            f"🕌 **নামাজের সময় হয়েছে! ({wakt_name})**\n\n"
                            f"নরসিংদী ও আশপাশের এলাকা। চলুন সবাই নামাজ আদায় করি!\n"
                            f"\"নিশ্চয়ই নামাজ মুমিনদের ওপর নির্দিষ্ট সময়ে ফরজ করা হয়েছে।\" 🌸"
                        )
                        for cid in get_all_active_chats():
                            try:
                                await app.bot.send_message(chat_id=cid, text=p_msg, parse_mode=ParseMode.MARKDOWN)
                                await asyncio.sleep(0.05)
                            except Exception:
                                pass
                        set_bot_state(prayer_state_key, "sent")

            # C. Friday 11:30 AM Jumma Reminder
            if now_dhaka.weekday() == 4 and current_hour == 11 and current_minute >= 30 and current_minute <= 35:
                friday_key = f"{today_str}_jumma"
                if get_bot_state("last_jumma_sent") != friday_key:
                    jumma_text = (
                        "🕌 **পবিত্র জুম্মা মোবারক!**\n\n"
                        "আজ সপ্তাহের সেরা ও বরকতময় দিন জুমাবার। সবাই আগে আগে গোসল করে সুগন্ধি মেখে মসজিদে চলে যান, এই নামাজ কোনোভাবেই মিস করা যাবে না!\n\n"
                        "আর হ্যাঁ, শুক্রবার মানেই তো দাওয়াত—কারো বিয়ের দাওয়াত আছে নাকি আজ? নাকি নিজেরই বিয়ের সানাই বাজছে? যাই হোক, বিরিয়ানি খেতে ভুলবেন না! 🍛😄"
                    )
                    for cid in get_all_active_chats():
                        try:
                            await app.bot.send_message(chat_id=cid, text=jumma_text, parse_mode=ParseMode.MARKDOWN)
                            await asyncio.sleep(0.05)
                        except Exception:
                            pass
                    set_bot_state("last_jumma_sent", friday_key)

            # D. Hourly Announcements
            if current_minute <= 5:
                date_hour_key = f"{today_str}_{current_hour}"
                last_sent = get_bot_state("last_auto_hour")

                if last_sent != date_hour_key:
                    message_text = get_hourly_broadcast_card(current_hour, now_dhaka)
                    if message_text:
                        active_chats = get_all_active_chats()
                        logger.info(f"Triggering hourly message for hour {current_hour} to {len(active_chats)} chats.")

                        for chat_id in active_chats:
                            try:
                                await app.bot.send_message(chat_id=chat_id, text=message_text, parse_mode=ParseMode.MARKDOWN)
                                await asyncio.sleep(0.05)
                            except Exception as e:
                                logger.debug(f"Failed to send hourly to chat {chat_id}: {e}")

                        set_bot_state("last_auto_hour", date_hour_key)

        except Exception as e:
            logger.error(f"Error in scheduler task: {e}")

        await asyncio.sleep(60)


# ------------------------------------------------------------------------------
# 11. TELEGRAM COMMAND HANDLERS
# ------------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /start command with warm, clean presentation."""
    track_user_and_chat(update)
    welcome_text = (
        "👋 **স্বাগতম! আমি আপনার অল-ইন-ওয়ান টেলিগ্রাম এআই অ্যাসিস্ট্যান্ট।**\n\n"
        "✨ **আমি যেভাবে সাহায্য করতে পারি:**\n"
        "• 🤖 **বুদ্ধিমান আলোচনা:** যেকোনো বিষয়ে বাংলা, Banglish বা English-এ প্রশ্ন করুন।\n"
        "• 🎵 **কন্টেন্ট লাইব্রেরি:** গান, নাটক, ভিডিও ইত্যাদি সহজে খুঁজে পেতে নাম লিখে চান।\n"
        "• 🕌 **নামাজের সময়:** `/prayer` লিখলেই আজকের সঠিক নামাজের সময়সূচি পাবেন।\n"
        "• 🌤️ **লাইভ আবহাওয়া:** আবহাওয়ার তাপমাত্রা ও অবস্থা জানতে পারেন।\n"
        "• ⚡ **বিদ্যুৎ ও নেট সমস্যা:** বাস্তবসম্মত কারণ ও ট্রাবলশুটিং সমাধান।\n"
        "• ℹ️ **সাহায্য:** সব কমান্ড দেখতে লিখুন `/help`।"
    )
    if update.effective_message:
        await update.effective_message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /help command with user-accessible options."""
    track_user_and_chat(update)
    help_text = (
        "📖 **বট ব্যবহার নির্দেশিকা:**\n\n"
        "🔹 `/start` — বট চালু করা ও পরিচিতি\n"
        "🔹 `/help` — এই সহায়তা বার্তা প্রদর্শন\n"
        "🔹 `/prayer` — আজকের ৫ ওয়াক্ত নামাজের সঠিক সময়সূচি\n\n"
        "💬 **স্বাভাবিকভাবে চ্যাট করুন:**\n"
        "• 'হাই', 'কেমন আছো', 'আসসালামু আলাইকুম'\n"
        "• 'বিদ্যুৎ নাই কেন', 'ইন্টারনেট স্লো'\n"
        "• 'আজ আবহাওয়া কেমন'\n"
        "• 'মন পাখি গান দেন' বা যেকোনো কন্টেন্টের নাম লিখুন\n\n"
        "🔒 *অ্যাডমিন কন্টেন্ট ও কমান্ড পরিচালনার জন্য আলাদা প্যানেল সংরক্ষিত রয়েছে।* 👑"
    )
    if update.effective_message:
        await update.effective_message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def prayer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /prayer command."""
    track_user_and_chat(update)
    if update.effective_message:
        wait_msg = await update.effective_message.reply_text("🕌 নামাজের সময় সংগ্রহ করা হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...")
        times = await fetch_prayer_times(PRAYER_CITY, PRAYER_COUNTRY)
        if times:
            await wait_msg.edit_text(times, parse_mode=ParseMode.MARKDOWN)
        else:
            await wait_msg.edit_text("❌ দুঃখিত, এই মুহূর্তে নামাজের সময়সূচি সংগ্রহ করা সম্ভব হচ্ছে না। কিছুক্ষণ পর আবার চেষ্টা করুন।")


# ------------------------------------------------------------------------------
# 12. ADMIN COMMANDS
# ------------------------------------------------------------------------------
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /admin — displays admin dashboard commands."""
    track_user_and_chat(update)
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return

    admin_text = (
        "👑 **অ্যাডমিন কন্ট্রোল প্যানেল (Admin Panel)**\n\n"
        "স্বাগতম অ্যাডমিন! নিচের কমান্ডগুলো ব্যবহার করতে পারেন:\n\n"
        "• `/admintest` — অ্যাডমিন এক্সেস পরীক্ষা\n"
        "• `/addsong` — লাইব্রেরিতে নতুন গান/ভিডিও/মিডিয়া যুক্ত করা\n"
        "• `/list` — সংরক্ষিত কন্টেন্টের তালিকা দেখা\n"
        "• `/stats` — মোট কন্টেন্ট ও চ্যাট সংক্রান্ত পরিসংখ্যান\n"
        "• `/delete ID` — আইডি দিয়ে নির্দিষ্ট কন্টেন্ট মুছে ফেলা (যেমন: `/delete 5`)\n"
        "• `/broadcast TEXT` — সমস্ত সক্রিয় গ্রুপ ও ব্যবহারকারীদের বার্তা পাঠানো"
    )
    if update.effective_message:
        await update.effective_message.reply_text(admin_text, parse_mode=ParseMode.MARKDOWN)


async def admintest_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /admintest."""
    track_user_and_chat(update)
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return

    if update.effective_message:
        await update.effective_message.reply_text("👑 Admin access working successfully.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /stats."""
    track_user_and_chat(update)
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return

    stats = get_library_stats()
    text = (
        "📊 **বটের বর্তমান পরিসংখ্যান (Bot Stats):**\n\n"
        f"📁 **মোট সংরক্ষিত কন্টেন্ট:** {stats['total_content']} টি\n"
        f"👥 **সক্রিয় চ্যাট/গ্রুপ সংখ্যা:** {stats['total_chats']} টি\n"
        f"👤 **মোট ট্র্যাকড ইউজার:** {stats['total_users']} জন\n"
        f"🗄️ **ডাটাবেজ স্ট্যাটাস:** {stats['db_status']}\n"
        f"⏰ **সার্ভার টাইমজোন:** {TIMEZONE_STR}"
    )
    if update.effective_message:
        await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /list — lists stored content items."""
    track_user_and_chat(update)
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return

    items = get_all_content_items(limit=30)
    if not items:
        if update.effective_message:
            await update.effective_message.reply_text("📂 লাইব্রেরিতে বর্তমানে কোনো কন্টেন্ট সংরক্ষিত নেই। `/addsong` দিয়ে যোগ করুন।")
        return

    lines = ["📁 **সংরক্ষিত কন্টেন্টের তালিকা (সর্বশেষ ৩০টি):**\n"]
    for it in items:
        lines.append(f"• ID: `{it['id']}` — **{it['title']}** [{it['media_type']}]")

    lines.append("\n💡 মুছে ফেলতে চাইলে লিখুন: `/delete ID`")
    if update.effective_message:
        await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /delete ID."""
    track_user_and_chat(update)
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return

    if not context.args or not context.args[0].isdigit():
        if update.effective_message:
            await update.effective_message.reply_text("⚠️ অনুগ্রহ করে সঠিক কন্টেন্ট ID দিন।\nউদাহরণ: `/delete 5`")
        return

    content_id = int(context.args[0])
    success = delete_content_by_id(content_id)
    if success:
        if update.effective_message:
            await update.effective_message.reply_text(f"✅ কন্টেন্ট ID `{content_id}` সফলভাবে ডাটাবেজ থেকে মুছে ফেলা হয়েছে।")
    else:
        if update.effective_message:
            await update.effective_message.reply_text(f"❌ ID `{content_id}` এর কোনো কন্টেন্ট খুঁজে পাওয়া যায়নি।")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles /broadcast TEXT."""
    track_user_and_chat(update)
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return

    text = " ".join(context.args).strip() if context.args else ""
    if not text:
        if update.effective_message:
            await update.effective_message.reply_text("⚠️ অনুগ্রহ করে সম্প্রচার করার বার্তাটি লিখুন।\nউদাহরণ: `/broadcast সবাইকে শুভ সকাল!`")
        return

    active_chats = get_all_active_chats()
    sent_count = 0
    failed_count = 0

    status_msg = None
    if update.effective_message:
        status_msg = await update.effective_message.reply_text(f"📢 {len(active_chats)} টি চ্যাটে বার্তা সম্প্রচার শুরু হয়েছে...")

    for chat_id in active_chats:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"📢 **গুরুত্বপূর্ণ নোটিশ:**\n\n{text}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed_count += 1
            logger.debug(f"Broadcast failed to {chat_id}: {e}")

    summary = (
        f"✅ **সম্প্রচার সম্পন্ন হয়েছে!**\n\n"
        f"• সফলভাবে প্রেরিত: {sent_count} টি চ্যাট\n"
        f"• ব্যর্থ হয়েছে: {failed_count} টি চ্যাট"
    )
    if status_msg:
        await status_msg.edit_text(summary, parse_mode=ParseMode.MARKDOWN)


async def addsong_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Initiates /addsong admin content upload sequence."""
    track_user_and_chat(update)
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.effective_message:
            await update.effective_message.reply_text("❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return

    ADMIN_ADD_STATE[user_id] = {"step": "waiting_media"}
    if update.effective_message:
        await update.effective_message.reply_text("📥 যে media save করতে চান সেটি পাঠান। (Audio, Video, Document, বা Photo)")


# ------------------------------------------------------------------------------
# 13. CONTENT DELIVERY HELPER
# ------------------------------------------------------------------------------
async def deliver_content_item(item: Dict[str, Any], chat_id: int, bot: Any) -> bool:
    """
    Sends media to user using stored telegram file_id.
    ONLY after successful delivery, sends the exact closing phrase:
    "আর কিছু লাগলে জানাবেন, আমরা আছি আপনার সাথে! 🤝"
    """
    media_type = item.get("media_type", "").lower()
    file_id = item.get("file_id", "")
    title = item.get("title", "")

    try:
        caption = f"🎬 **{title}**"
        if media_type == "audio":
            await bot.send_audio(chat_id=chat_id, audio=file_id, caption=caption)
        elif media_type == "video":
            await bot.send_video(chat_id=chat_id, video=file_id, caption=caption)
        elif media_type == "photo":
            await bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption)
        else:
            await bot.send_document(chat_id=chat_id, document=file_id, caption=caption)

        # STRICT REQUIREMENT: Only sent after content successfully delivered!
        await bot.send_message(chat_id=chat_id, text="আর কিছু লাগলে জানাবেন, আমরা আছি আপনার সাথে! 🤝")
        return True
    except Exception as e:
        logger.error(f"Failed to deliver media {item.get('id')}: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text="❌ দুঃখিত, ফাইলটি পাঠাতে প্রযুক্তিগত সমস্যা হয়েছে। অ্যাডমিনের সাথে যোগাযোগ করুন।"
        )
        return False


# ------------------------------------------------------------------------------
# 14. ADMIN MEDIA RECEIVER HANDLER
# ------------------------------------------------------------------------------
async def media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles uploaded media.
    Per rule: If admin directly sends media without /addsong, do NOT save automatically!
    """
    track_user_and_chat(update)
    msg = update.effective_message
    user_id = update.effective_user.id if update.effective_user else 0

    if not msg:
        return

    # Check if admin is currently in /addsong waiting_media step
    state = ADMIN_ADD_STATE.get(user_id)
    if is_admin(user_id) and state and state.get("step") == "waiting_media":
        file_id = ""
        media_type = ""

        if msg.audio:
            file_id = msg.audio.file_id
            media_type = "audio"
        elif msg.voice:
            file_id = msg.voice.file_id
            media_type = "audio"
        elif msg.video:
            file_id = msg.video.file_id
            media_type = "video"
        elif msg.photo:
            file_id = msg.photo[-1].file_id
            media_type = "photo"
        elif msg.document:
            file_id = msg.document.file_id
            media_type = "document"

        if file_id and media_type:
            ADMIN_ADD_STATE[user_id] = {
                "step": "waiting_title",
                "media_type": media_type,
                "file_id": file_id,
            }
            await msg.reply_text("📝 এই content-এর নাম লিখুন।")
            return

    # If regular user or admin sends media outside flow, do nothing or acknowledge


# ------------------------------------------------------------------------------
# 15. MAIN TEXT MESSAGE HANDLER & ROUTER
# ------------------------------------------------------------------------------
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Central processing for all user and group text messages."""
    track_user_and_chat(update)
    msg = update.effective_message
    user = update.effective_user

    if not msg or not msg.text or not user:
        return

    user_id = user.id
    raw_text = msg.text.strip()

    # Rate Limit Guard
    if check_rate_limit(user_id):
        await msg.reply_text("⏳ একটু ধীরে বলুন, আমি শুনছি। 🙂")
        return

    # A. Check if Admin is in /addsong waiting_title step
    admin_state = ADMIN_ADD_STATE.get(user_id)
    if is_admin(user_id) and admin_state and admin_state.get("step") == "waiting_title":
        media_type = admin_state["media_type"]
        file_id = admin_state["file_id"]
        title = raw_text

        new_id = save_content_item(title=title, media_type=media_type, file_id=file_id, admin_id=user_id)
        del ADMIN_ADD_STATE[user_id]

        await msg.reply_text(
            f"✅ Content সফলভাবে Save হয়েছে!\n\n"
            f"🆔 ID: `{new_id}`\n"
            f"📝 নাম: **{title}**\n"
            f"📁 ধরন: {media_type.capitalize()}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # B. Check if user is responding to a multiple content selection (e.g. typing "1", "2")
    user_selection = USER_CONTENT_SELECTION.get(user_id)
    if user_selection and raw_text.isdigit():
        choice_idx = int(raw_text) - 1
        results = user_selection.get("results", [])
        if 0 <= choice_idx < len(results):
            selected_item = results[choice_idx]
            del USER_CONTENT_SELECTION[user_id]
            await deliver_content_item(selected_item, update.effective_chat.id, context.bot)
            return

    # C. Check if user was waiting to type content name after a failed search
    if user_id in USER_WAITING_CONTENT_NAME:
        del USER_WAITING_CONTENT_NAME[user_id]
        # Perform content search directly with this name
        await handle_content_search(raw_text, update, context)
        return

    # D. Instant Chat Action (Typing indicator for sub-second user feedback)
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    # E. Detect Intent
    intent = detect_intent(raw_text)

    # 1. Greeting
    if intent == "greeting":
        await msg.reply_text("হাই! 👋 কেমন আছেন? কীভাবে সাহায্য করতে পারি?")
        return

    # 2. Salam
    if intent == "salam":
        await msg.reply_text("ওয়ালাইকুম আসসালাম! 👋 কেমন আছেন?")
        return

    # 3. How are you
    if intent == "how_are_you":
        await msg.reply_text("আলহামদুলিল্লাহ, ভালো আছি। 😊 আপনি কেমন আছেন?")
        return

    # 3.1 What are you doing (কি করো তুমি)
    if intent == "what_doing":
        await msg.reply_text("এইতো আপনার সাথে আড্ডা দিচ্ছি আর আপনার মেসেজের অপেক্ষা করছিলাম! 😊 বলুন, আপনার দিনকাল কেমন কাটছে? কোনো সাহায্য লাগলে বলতে পারেন।")
        return

    # 3.2 Who are you (তুমি কে)
    if intent == "who_are_you":
        await msg.reply_text("আমি আপনার সার্বক্ষণিক বন্ধু ও স্মার্ট টেলিগ্রাম অ্যাসিস্ট্যান্ট! 😊 গান, নাটক, ভিডিও খুঁজে দেওয়া, নামাজের সময়সূচি, আবহাওয়া জানানো এবং আপনার যেকোনো প্রশ্নের উত্তর দেওয়াই আমার কাজ।")
        return

    # 3.3 Creator / Boss (তোমাকে কে তৈরি করছে)
    if intent == "creator":
        await msg.reply_text("আমার Boss,, TOMAL CHOWDHURY,, আমাকে তৈরি করছে! 😎🚀")
        return

    # 3.4 User Assistance & Help (সাহায্য লাগবে / কথা বলা)
    if intent == "help_contact":
        await msg.reply_text("আমার Boss, TOMAL CHOWDHURY, সাথে কথা বলেন Boss ভালো জানে আশা করি উপকার হবে আপনার ধন্যবাদ। 😊🤝")
        return

    # 4. Thanks
    if intent == "thanks":
        await msg.reply_text("স্বাগতম! 😊")
        return

    # 5. Goodbye
    if intent == "goodbye":
        await msg.reply_text("ঠিক আছে, পরে কথা হবে। 👋")
        return

    # 6. Electricity Problem
    if intent == "electricity":
        await msg.reply_text(ELECTRICITY_RESPONSE)
        return

    # 7. Internet Problem
    if intent == "internet":
        await msg.reply_text(INTERNET_RESPONSE)
        return

    # 8. Weather
    if intent == "weather":
        wait_m = await msg.reply_text("🌤️ লাইভ আবহাওয়া ডাটা লোড হচ্ছে...")
        weather_text = await fetch_weather_data()
        if weather_text:
            await wait_m.edit_text(weather_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await wait_m.edit_text("❌ লাইভ আবহাওয়া তথ্য এই মুহূর্তে পাওয়া যাচ্ছে না। কিছুক্ষণ পর আবার চেষ্টা করুন।")
        return

    # 9. Prayer
    if intent == "prayer":
        wait_m = await msg.reply_text("🕌 নামাজের সময়সূচি লোড হচ্ছে...")
        p_text = await fetch_prayer_times()
        if p_text:
            await wait_m.edit_text(p_text, parse_mode=ParseMode.MARKDOWN)
        else:
            await wait_m.edit_text("❌ নামাজের সময়সূচি সংগ্রহ করা যায়নি।")
        return

    # 9.1 Time / Clock (এখন কয়টা বাজে)
    if intent == "time":
        await msg.reply_text(format_bangladesh_clock_card(), parse_mode=ParseMode.MARKDOWN)
        return

    # 9.2 Friday Special Info
    if intent == "friday":
        friday_text = (
            "🕌 **পবিত্র জুম্মার বরকতময় দিন!**\n\n"
            "আজ সপ্তাহের সেরা দিন। রাসূলুল্লাহ (সা.) বলেছেন, 'দিবসসমূহের মধ্যে জুমার দিন শ্রেষ্ঠ।' "
            "গোসল করে সুন্দর ও পরিষ্কার পোশাক পরিধান করুন, সুগন্ধি মেখে আযানের সাথে সাথে মসজিদে চলে যান। "
            "এই নামাজ কোনোভাবেই মিস করা যাবে না!\n\n"
            "আর হ্যাঁ, শুক্রবার মানেই তো আত্মীয়-স্বজনের মিলনমেলা আর বিয়ের দাওয়াত! "
            "কারো বিয়ের দাওয়াত আছে নাকি আজ? নাকি নিজেরই বিয়ের সানাই বাজছে? যাই হোক, বিরিয়ানি খেতে ভুলবেন না! 🍛😄"
        )
        await msg.reply_text(friday_text, parse_mode=ParseMode.MARKDOWN)
        return

    # 10. Content Request
    if intent == "content_request":
        await handle_content_search(raw_text, update, context)
        return

    # 11. General AI Conversation
    # Let AI respond concisely and directly in user's language
    ai_answer = await ask_openai_chat(raw_text)
    await msg.reply_text(ai_answer)


# ------------------------------------------------------------------------------
# 16. CONTENT SEARCH HANDLER
# ------------------------------------------------------------------------------
async def handle_content_search(query: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Executes search against SQLite content table.
    Enforces exact step sequence:
    1. "👋 Welcome!"
    2. "⏳ একটু অপেক্ষা করুন, দিচ্ছি..."
    3. Search database
    4. If matches found: send media + closing message OR show numbered list
    5. If not found: show not found message and wait for next message
    """
    msg = update.effective_message
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id if update.effective_user else 0

    if not msg:
        return

    # Step 1
    await msg.reply_text("👋 Welcome!")
    # Step 2
    wait_msg = await msg.reply_text("⏳ একটু অপেক্ষা করুন, দিচ্ছি...")

    # Search in SQLite
    matches = search_content_items(query)

    if not matches:
        # User not found message
        not_found_text = (
            "❌ এই নামে কোনো saved content এখনো পাওয়া যায়নি।\n\n"
            "📝 যে content চান তার নামটি লিখুন।\n"
            "আমি আবার search করছি।"
        )
        await wait_msg.edit_text(not_found_text)
        # Register user in waiting state
        USER_WAITING_CONTENT_NAME[user_id] = time.time()
        return

    if len(matches) == 1:
        # Exactly one match, deliver directly!
        await wait_msg.delete()
        await deliver_content_item(matches[0], chat_id, context.bot)
        return

    # Multiple matches found: display clean numbered list
    USER_CONTENT_SELECTION[user_id] = {
        "results": matches[:10],
        "timestamp": time.time(),
    }

    lines = ["🔎 **এই নামে কয়েকটি Content পাওয়া গেছে:**\n"]
    for idx, item in enumerate(matches[:10], start=1):
        lines.append(f"{idx}️⃣ **{item['title']}** — {item['media_type'].capitalize()}")

    lines.append("\n👉 **যেটি চান তার নম্বরটি লিখে পাঠান (যেমন: 1 বা 2)**")

    await wait_msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ------------------------------------------------------------------------------
# 17. GLOBAL ERROR HANDLER
# ------------------------------------------------------------------------------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs error and ensures bot NEVER crashes on bad payloads."""
    logger.error(f"Telegram exception encountered: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ দুঃখিত, আপনার অনুরোধটি প্রসেস করতে একটি সাময়িক ত্রুটি হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।"
            )
        except Exception:
            pass


# ------------------------------------------------------------------------------
# 18. BOT APPLICATION FACTORY & STARTUP
# ------------------------------------------------------------------------------
def main() -> None:
    """Main application entry point."""
    print("=" * 60)
    print("🤖 Telegram AI Bot — Starting Service...")
    print("=" * 60)

    # 1. Initialize SQLite Database
    init_db()

    # 2. Token Check
    if not BOT_TOKEN:
        print("\n❌ CRITICAL ERROR: BOT_TOKEN is missing!")
        print("Please set your BOT_TOKEN in .env or Environment Variables.\n")
        sys.exit(1)

    if not ADMIN_ID:
        print("\n⚠️ WARNING: ADMIN_ID is not set or invalid! Admin commands will be locked.")
    else:
        print(f"👑 Admin ID registered: {ADMIN_ID}")

    if not OPENAI_API_KEY:
        print("ℹ️ OPENAI_API_KEY is not set. Bot will run smoothly in Free Rule/Fallback Mode.")
    else:
        print(f"🤖 OpenAI Integration enabled with model: {OPENAI_MODEL}")

    print(f"🌍 Default Prayer/Weather location: {PRAYER_CITY}, {PRAYER_COUNTRY}")
    print(f"⏰ Server Timezone: {TIMEZONE_STR}")

    # 3. Build Telegram Application
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # 4. Register Command Handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("prayer", prayer_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("admintest", admintest_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("list", list_command))
    application.add_handler(CommandHandler("delete", delete_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("addsong", addsong_command))

    # 5. Register Media Handler (For Admin /addsong flow)
    application.add_handler(
        MessageHandler(
            filters.AUDIO | filters.VIDEO | filters.PHOTO | filters.Document.ALL | filters.VOICE,
            media_handler,
        )
    )

    # 6. Register Text Message Handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    # 7. Global Error Handler
    application.add_error_handler(global_error_handler)

    # 8. Background Hourly Task Hook
    async def post_init(app: Application) -> None:
        asyncio.create_task(hourly_broadcast_job(app))
        logger.info("Hourly broadcast background scheduler initialized.")

    application.post_init = post_init

    # 9. Start Long Polling
    print("\n🚀 Bot polling started! Press Ctrl+C to stop.")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
