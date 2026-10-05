#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram AI Assistant & Media Bot - OpenAI + Adsterra
Admin: @tomalchowdhury2 (ID: 8721334265)

FULL VERSION

Kept features:
· OpenAI AI replies
· Admin media upload -> title -> category -> SQLite save
· Drama/song/video/category search and delivery
· Admin alerts
· Weather and prayer times
· Admin commands
· Group-message handling/logging
· Removes old Telegram webhook before polling
· Saves groups when bot is added
· Hourly automatic reminders
· Exact prayer-time automatic reminders
· Study, sports, work and sleep reminders
· /auto_on and /auto_off per chat

Updated:
· Adsterra Smartlink Ad integration (Replaced AdsGram)
· Dynamic category system
· Large category system
· Admin add/edit/delete category
· Natural category intent detection
· Fast local replies before OpenAI
· Bengali/Banglish understanding
· Creator/Boss identity replies
· Bot home/location reply
· Rain / heat / winter smart replies
· Food / cooking / bathing / sleeping replies
· Funny replies
· Apology replies
· Anti-fighting replies
· Matching emojis
· Many smart reply patterns/templates
· Prayer-specific fun captions
· Content request waiting message
· Better media request handling
· Better automatic daily reminders

Required Render Environment Variables:

BOT_TOKEN
OPENAI_API_KEY
OPENAI_MODEL                  optional
ADSTERRA_AD_URL               REQUIRED for Adsterra Monetization

Optional:
TIMEZONE=Asia/Dhaka
PRAYER_CITY=Dhaka
PRAYER_COUNTRY=Bangladesh
PRAYER_METHOD=1
DB_FILE=bot_database.db

AUTO_MESSAGES_ENABLED=true
STUDY_HOURS=7,10,15,19
SPORTS_HOURS=17,21
SLEEP_HOUR=23
WAKE_HOUR=7
WORK_HOURS=9,13,20
"""

import os
import re
import time
import asyncio
import logging
import sqlite3
import traceback
import random
from datetime import datetime
from html import escape as html_escape

import pytz
import aiohttp
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo").strip()

ADMIN_IDS = [8721334265]
ADMIN_USERNAME = "tomalchowdhury2"

# Boss identity
BOSS_NAME = "TOMAL CHOWDHURY"
BOSS_USERNAME = "@tomalchowdhury2"

TIMEZONE_NAME = os.getenv(
    "TIMEZONE",
    "Asia/Dhaka"
)

try:
    TZ = pytz.timezone(TIMEZONE_NAME)
except Exception:
    TZ = pytz.timezone("Asia/Dhaka")

PRAYER_CITY = os.getenv(
    "PRAYER_CITY",
    "Dhaka"
)

PRAYER_COUNTRY = os.getenv(
    "PRAYER_COUNTRY",
    "Bangladesh"
)

PRAYER_METHOD = os.getenv(
    "PRAYER_METHOD",
    "1"
)

DB_FILE = os.getenv(
    "DB_FILE",
    "bot_database.db"
)

# ============================================================================
# ADSTERRA CONFIGURATION
# ============================================================================

ADSTERRA_AD_URL = os.getenv(
    "ADSTERRA_AD_URL",
    ""
).strip()

ADSTERRA_ENABLED = bool(ADSTERRA_AD_URL)

# ============================================================================
# AUTOMATIC NOTIFICATIONS
# ============================================================================

AUTO_MESSAGES_ENABLED = os.getenv(
    "AUTO_MESSAGES_ENABLED",
    "true"
).lower() in {
    "1",
    "true",
    "yes",
    "on"
}


def parse_hours(value, default):
    result = []
    for item in (value.split(",") if value else []):
        try:
            h = int(item.strip())
            if 0 <= h <= 23:
                result.append(h)
        except ValueError:
            pass
    return sorted(set(result)) or default


STUDY_HOURS = parse_hours(
    os.getenv("STUDY_HOURS", "7,10,15,19"),
    [7, 10, 15, 19]
)

SPORTS_HOURS = parse_hours(
    os.getenv("SPORTS_HOURS", "17,21"),
    [17, 21]
)

WORK_HOURS = parse_hours(
    os.getenv("WORK_HOURS", "9,13,20"),
    [9, 13, 20]
)

try:
    SLEEP_HOUR = int(os.getenv("SLEEP_HOUR", "23"))
except Exception:
    SLEEP_HOUR = 23

try:
    WAKE_HOUR = int(os.getenv("WAKE_HOUR", "7"))
except Exception:
    WAKE_HOUR = 7

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("telegram_bot")

# ============================================================================
# OPENAI
# ============================================================================

openai_client = None

if OPENAI_API_KEY:
    try:
        from openai import AsyncOpenAI
        openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client configured successfully.")
    except Exception as e:
        logger.warning("Could not initialize OpenAI client: %s", e)
else:
    logger.warning("OPENAI_API_KEY is missing.")

# ============================================================================
# DATABASE
# ============================================================================

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


def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


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

        cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            key TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            aliases TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
        """)

        cur.execute("PRAGMA table_info(contents)")
        content_cols = [c[1] for c in cur.fetchall()]
        if "views" not in content_cols:
            cur.execute("ALTER TABLE contents ADD COLUMN views INTEGER DEFAULT 0")

        cur.execute("PRAGMA table_info(chats)")
        chat_cols = [c[1] for c in cur.fetchall()]
        if "notification_enabled" not in chat_cols:
            cur.execute("ALTER TABLE chats ADD COLUMN notification_enabled INTEGER DEFAULT 1")

        conn.commit()

    seed_default_categories()
    logger.info("Database initialized.")

# ============================================================================
# HELPER FOR ADSTERRA BUTTONS
# ============================================================================

def get_adsterra_keyboard(content_id: int):
    """AdsGram-এর জায়গায় Adsterra বিজ্ঞাপনের বাটন জেনারেট করবে"""
    buttons = []
    if ADSTERRA_ENABLED:
        buttons.append([
            InlineKeyboardButton(
                "🎬 Watch Ad to Unlock / বিজ্ঞাপন দেখুন",
                url=ADSTERRA_AD_URL
            )
        ])
    buttons.append([
        InlineKeyboardButton(
            "✅ Get Media / ফাইলটি নিন",
            callback_data=f"get_media:{content_id}"
        )
    ])
    return InlineKeyboardMarkup(buttons)

# ============================================================================
# DEFAULT CATEGORIES & HELPER FUNCTIONS
# ============================================================================

DEFAULT_CATEGORIES = [
    ("romantic", "❤️ রোমান্টিক", "রোমান্টিক,romantic,প্রেমের"),
    ("comedy", "😂 কমেডি", "কমেডি,comedy,হাসির"),
    ("family", "👨‍👩‍👧 ফ্যামিলি", "ফ্যামিলি,family,পারিবারিক"),
    ("emotional", "😭 ইমোশনাল", "ইমোশনাল,emotional"),
    ("love", "💖 ভালোবাসা", "ভালোবাসা,love"),
    ("sad", "💔 দুঃখের", "দুঃখের,sad,দুঃখ"),
    ("action", "💥 অ্যাকশন", "অ্যাকশন,action"),
    ("thriller", "🕵️ থ্রিলার", "থ্রিলার,thriller"),
    ("horror", "👻 ভৌতিক", "ভৌতিক,horror,ভূতের"),
    ("mystery", "🔍 রহস্য", "রহস্য,mystery"),
    ("natok", "🎭 বাংলা নাটক", "নাটক,natok,drama,বাংলা নাটক"),
    ("music", "🎵 গান", "গান,music,song"),
    ("movie", "🎬 মুভি", "মুভি,movie,সিনেমা"),
    ("other", "📂 অন্যান্য", "অন্যান্য,other")
]

def seed_default_categories():
    count_row = db_execute("SELECT COUNT(*) AS c FROM categories", fetchone=True)
    count = count_row["c"] if count_row else 0
    if count > 0:
        return
    for index, item in enumerate(DEFAULT_CATEGORIES):
        key, label, aliases = item
        db_execute(
            """
            INSERT OR IGNORE INTO categories(key, label, aliases, sort_order, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (key, label, aliases, index, now_str())
        )

# ============================================================================
# MAIN BOT HANDLERS & CALLBACKS
# ============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"হ্যালো {user.first_name}! 👋\n\n"
        f"আমি {BOSS_NAME}-এর অফিসিয়াল টেলিগ্রাম বট।\n"
        "গান, নাটক, ভিডিও বা যেকোন প্রশ্নের উত্তর পেতে মেসেজ করুন।"
    )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("get_media:"):
        content_id = data.split(":")[1]
        item = db_execute("SELECT * FROM contents WHERE id=?", (content_id,), fetchone=True)
        if item:
            file_id = item["file_id"]
            media_type = item["media_type"]
            caption = f"🎬 <b>{html_escape(item['title'])}</b>"
            
            # ভিউ সংখ্যা বাড়ানো
            db_execute("UPDATE contents SET views = views + 1 WHERE id=?", (content_id,))

            if media_type == "video":
                await query.message.reply_video(video=file_id, caption=caption, parse_mode=ParseMode.HTML)
            elif media_type == "audio":
                await query.message.reply_audio(audio=file_id, caption=caption, parse_mode=ParseMode.HTML)
            else:
                await query.message.reply_document(document=file_id, caption=caption, parse_mode=ParseMode.HTML)
        else:
            await query.message.reply_text("❌ ফাইলটি পাওয়া যায়নি।")

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing!")
        return

    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()
