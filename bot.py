#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram AI Assistant & Media Bot - OpenAI + AdsGram
Admin: @tomalchowdhury2 (ID: 8721334265)

Kept features:
- OpenAI AI replies
- Admin media upload -> title -> category -> SQLite save
- Drama/song/video/category search and delivery
- Admin alerts
- Weather and prayer times
- Admin commands: /start /help /contact /admin /list /delete /stats
- Group-message handling/logging
- Removes old Telegram webhook before polling
- Saves groups when bot is added
- Hourly automatic reminders
- Exact prayer-time automatic reminders
- Study, sports, work and sleep reminders
- /auto_on and /auto_off per chat

Added:
- AdsGram Bot API ad before media delivery
- Dynamic category system
- Admin add/edit/delete category
- Natural category intent detection
- Fast replies for known intents
- Better Bengali/Banglish category understanding
- Category aliases
- Category browsing
- Database migration for old installations

Required Render Environment Variables:

BOT_TOKEN
OPENAI_API_KEY
OPENAI_MODEL                  optional

ADSGRAM_BLOCK_ID              bot-52042
ADSGRAM_TOKEN                 REQUIRED for AdsGram Bot API
ADSGRAM_WEBAPP_URL            kept for compatibility; not used for Bot API

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
# Configuration
# ============================================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip()

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

# ============================================================================
# AdsGram
# ============================================================================

ADSGRAM_BLOCK_ID = os.getenv("ADSGRAM_BLOCK_ID", "").strip()
ADSGRAM_TOKEN = os.getenv("ADSGRAM_TOKEN", "").strip()

# Kept because user already added it.
# AdsGram Bot API does NOT use this URL.
ADSGRAM_WEBAPP_URL = os.getenv(
    "ADSGRAM_WEBAPP_URL",
    "https://sad.adsgram.ai/js/sad.js"
).strip()

ADSGRAM_ENABLED = bool(ADSGRAM_BLOCK_ID and ADSGRAM_TOKEN)

# AdsGram block may be supplied as bot-52042.
# Bot API requires numeric part only.
def adsgram_numeric_block_id():
    value = ADSGRAM_BLOCK_ID.strip()

    if value.lower().startswith("bot-"):
        value = value[4:]

    match = re.search(r"\d+", value)

    if match:
        return match.group(0)

    return value


ADSGRAM_NUMERIC_BLOCK_ID = adsgram_numeric_block_id()

# ============================================================================
# Automatic notifications
# ============================================================================

AUTO_MESSAGES_ENABLED = os.getenv(
    "AUTO_MESSAGES_ENABLED",
    "true"
).lower() in {"1", "true", "yes", "on"}


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
# Logging
# ============================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("telegram_bot")

# ============================================================================
# OpenAI
# ============================================================================

openai_client = None

if OPENAI_API_KEY:
    try:
        from openai import AsyncOpenAI

        openai_client = AsyncOpenAI(
            api_key=OPENAI_API_KEY
        )

        logger.info(
            "OpenAI client configured successfully. Key=SET"
        )

    except Exception as e:
        logger.warning(
            "Could not initialize OpenAI client: %s",
            e
        )

else:
    logger.warning(
        "OPENAI_API_KEY is missing."
    )

# ============================================================================
# Database
# ============================================================================


def get_db():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def db_execute(
    query,
    params=(),
    fetchone=False,
    fetch=False,
    commit=True
):
    with get_db() as conn:

        cur = conn.cursor()

        cur.execute(query, params)

        if commit:
            conn.commit()

        if fetchone:
            row = cur.fetchone()

            return dict(row) if row else None

        if fetch:
            return [
                dict(r)
                for r in cur.fetchall()
            ]

        return cur.lastrowid


def init_db():

    with get_db() as conn:

        cur = conn.cursor()

        # ------------------------------------------------------------
        # Users
        # ------------------------------------------------------------

        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            joined_at TEXT
        )
        """)

        # ------------------------------------------------------------
        # Chats
        # ------------------------------------------------------------

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

        # ------------------------------------------------------------
        # Contents
        # ------------------------------------------------------------

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

        # ------------------------------------------------------------
        # Messages
        # ------------------------------------------------------------

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

        # ------------------------------------------------------------
        # Bot state
        # ------------------------------------------------------------

        cur.execute("""
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        # ------------------------------------------------------------
        # Dynamic categories
        # ------------------------------------------------------------

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

        # ------------------------------------------------------------
        # Backward compatibility
        # ------------------------------------------------------------

        cur.execute(
            "PRAGMA table_info(contents)"
        )

        content_cols = [
            c[1]
            for c in cur.fetchall()
        ]

        if "views" not in content_cols:
            cur.execute(
                "ALTER TABLE contents "
                "ADD COLUMN views INTEGER DEFAULT 0"
            )

        cur.execute(
            "PRAGMA table_info(chats)"
        )

        chat_cols = [
            c[1]
            for c in cur.fetchall()
        ]

        if "notification_enabled" not in chat_cols:
            cur.execute(
                "ALTER TABLE chats "
                "ADD COLUMN notification_enabled "
                "INTEGER DEFAULT 1"
            )

        conn.commit()

    seed_default_categories()

    logger.info("Database initialized.")


def now_str():
    return datetime.now(TZ).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def save_user(user):

    if not user:
        return

    db_execute(
        """
        INSERT INTO users(
            user_id,
            first_name,
            last_name,
            username,
            joined_at
        )
        VALUES (?, ?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            username=excluded.username
        """,
        (
            user.id,
            user.first_name or "",
            user.last_name or "",
            user.username or "",
            now_str(),
        )
    )


def save_chat(chat):

    if not chat:
        return

    db_execute(
        """
        INSERT INTO chats(
            chat_id,
            chat_type,
            title,
            username,
            created_at,
            notification_enabled
        )
        VALUES (?, ?, ?, ?, ?, 1)

        ON CONFLICT(chat_id)
        DO UPDATE SET
            chat_type=excluded.chat_type,
            title=excluded.title,
            username=excluded.username
        """,
        (
            chat.id,
            chat.type,
            chat.title or "",
            chat.username or "",
            now_str(),
        )
    )


def set_chat_notifications(chat_id, enabled):

    db_execute(
        """
        UPDATE chats
        SET notification_enabled=?
        WHERE chat_id=?
        """,
        (
            1 if enabled else 0,
            chat_id,
        )
    )


def get_notification_chats():

    return db_execute(
        """
        SELECT chat_id, chat_type, title
        FROM chats
        WHERE notification_enabled=1
        ORDER BY chat_id
        """,
        fetch=True
    )


def save_message(
    chat_id,
    user_id,
    role,
    content
):

    db_execute(
        """
        INSERT INTO messages(
            chat_id,
            user_id,
            role,
            content,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            role,
            content,
            now_str(),
        )
    )


def get_history(chat_id, limit=6):

    rows = db_execute(
        """
        SELECT role, content
        FROM messages
        WHERE chat_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            chat_id,
            limit,
        ),
        fetch=True
    )

    return rows[::-1] if rows else []


def get_state(key):

    row = db_execute(
        """
        SELECT value
        FROM bot_state
        WHERE key=?
        """,
        (key,),
        fetchone=True
    )

    return row["value"] if row else None


def set_state(key, value):

    db_execute(
        """
        INSERT INTO bot_state(key, value)
        VALUES (?, ?)

        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (
            key,
            str(value),
        )
    )

# ============================================================================
# Default Categories
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
    ("adventure", "🏕️ অ্যাডভেঞ্চার", "অ্যাডভেঞ্চার,adventure"),
    ("family_drama", "🏠 পারিবারিক নাটক", "পারিবারিক নাটক"),
    ("village", "🌾 গ্রামের গল্প", "গ্রামের গল্প,গ্রাম,গ্রাম্য"),
    ("city", "🏙️ শহরের গল্প", "শহরের গল্প,শহর"),
    ("school", "🏫 স্কুল জীবন", "স্কুল,school,স্কুল জীবন"),
    ("college", "🎓 কলেজ জীবন", "কলেজ,college,কলেজ জীবন"),
    ("office", "💼 অফিস/কাজ", "অফিস,office,কাজের"),
    ("friendship", "🤝 বন্ধুত্ব", "বন্ধুত্ব,friendship"),
    ("couple", "💑 কাপল", "কাপল,couple"),
    ("breakup", "💔 ব্রেকআপ", "ব্রেকআপ,breakup"),
    ("marriage", "💍 বিয়ে", "বিয়ে,বিবাহ,marriage"),
    ("social", "🌍 সামাজিক", "সামাজিক,social"),
    ("islamic", "🕌 ইসলামিক", "ইসলামিক,islamic"),
    ("motivational", "🔥 মোটিভেশনাল", "মোটিভেশনাল,motivational"),
    ("educational", "📚 শিক্ষামূলক", "শিক্ষামূলক,educational"),
    ("funny", "🤣 হাসির", "হাসির,funny"),
    ("viral", "🚀 ভাইরাল", "ভাইরাল,viral"),
    ("trending", "🔥 ট্রেন্ডিং", "ট্রেন্ডিং,trending"),
    ("short", "⚡ শর্ট ভিডিও", "শর্ট,short,শর্ট ভিডিও"),
    ("tiktok", "📱 TikTok", "tiktok,TikTok"),
    ("reels", "🎞️ Reels", "reels,Reels"),
    ("youtube", "▶️ YouTube", "youtube,YouTube"),
    ("movie", "🎬 মুভি", "মুভি,movie,সিনেমা"),
    ("webseries", "📺 ওয়েব সিরিজ", "ওয়েব সিরিজ,webseries,series"),
    ("natok", "🎭 বাংলা নাটক", "নাটক,natok,drama,বাংলা নাটক"),
    ("music", "🎵 গান", "গান,music,song"),
    ("romantic_song", "🎶 রোমান্টিক গান", "রোমান্টিক গান"),
    ("sad_song", "🎼 স্যাড গান", "স্যাড গান"),
    ("folk", "🪕 লোকগান", "লোকগান,folk"),
    ("islamic_song", "🕋 ইসলামিক গান", "ইসলামিক গান"),
    ("gazal", "🎤 গজল", "গজল,gazal"),
    ("dance", "💃 ডান্স", "ডান্স,dance"),
    ("sports", "🏆 স্পোর্টস", "স্পোর্টস,sports"),
    ("cricket", "🏏 ক্রিকেট", "ক্রিকেট,cricket"),
    ("football", "⚽ ফুটবল", "ফুটবল,football"),
    ("wrestling", "🤼 রেসলিং", "রেসলিং,wrestling"),
    ("news", "📰 নিউজ", "নিউজ,news"),
    ("technology", "💻 টেকনোলজি", "টেক,technology,tech"),
    ("gaming", "🎮 গেমিং", "গেমিং,gaming"),
    ("travel", "✈️ ভ্রমণ", "ভ্রমণ,travel"),
    ("nature", "🌿 প্রকৃতি", "প্রকৃতি,nature"),
    ("rain", "🌧️ বৃষ্টি", "বৃষ্টি,rain"),
    ("winter", "❄️ শীত", "শীত,winter,শীতের"),
    ("summer", "☀️ গরম", "গরম,summer,hot,heat"),
    ("food", "🍔 খাবার", "খাবার,food"),
    ("cooking", "👨‍🍳 রান্না", "রান্না,cooking"),
    ("animals", "🐾 প্রাণী", "প্রাণী,animals"),
    ("kids", "🧒 শিশুদের", "শিশু,kids"),
    ("cartoon", "🧸 কার্টুন", "কার্টুন,cartoon"),
    ("documentary", "🎥 ডকুমেন্টারি", "ডকুমেন্টারি,documentary"),
    ("history", "🏛️ ইতিহাস", "ইতিহাস,history"),
    ("science", "🔬 বিজ্ঞান", "বিজ্ঞান,science"),
    ("health", "🩺 স্বাস্থ্য", "স্বাস্থ্য,health"),
    ("fitness", "💪 ফিটনেস", "ফিটনেস,fitness"),
    ("lifestyle", "✨ লাইফস্টাইল", "লাইফস্টাইল,lifestyle"),
    ("other", "📂 অন্যান্য", "অন্যান্য,other"),
]


def seed_default_categories():

    count_row = db_execute(
        "SELECT COUNT(*) AS c FROM categories",
        fetchone=True
    )

    count = count_row["c"] if count_row else 0

    if count > 0:
        return

    for index, item in enumerate(DEFAULT_CATEGORIES):

        key, label, aliases = item

        db_execute(
            """
            INSERT OR IGNORE INTO categories(
                key,
                label,
                aliases,
                sort_order,
                active,
                created_at
            )
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (
                key,
                label,
                aliases,
                index,
                now_str(),
            )
        )


def get_categories(active_only=True):

    if active_only:

        return db_execute(
            """
            SELECT *
            FROM categories
            WHERE active=1
            ORDER BY sort_order ASC, key ASC
            """,
            fetch=True
        )

    return db_execute(
        """
        SELECT *
        FROM categories
        ORDER BY sort_order ASC, key ASC
        """,
        fetch=True
    )


def get_category(key):

    return db_execute(
        """
        SELECT *
        FROM categories
        WHERE key=?
        """,
        (key,),
        fetchone=True
    )


def get_category_labels():

    rows = get_categories()

    return {
        row["key"]: row["label"]
        for row in rows
    }


def category_exists(key):

    return bool(
        get_category(key)
    )


# ============================================================================
# Text Helpers
# ============================================================================


def normalize_text(text):

    if not text:
        return ""

    text = str(text).lower()

    text = re.sub(
        r"[^\w\s\u0980-\u09FF]",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def clean_category_key(value):

    value = normalize_text(value)

    value = re.sub(
        r"\s+",
        "_",
        value
    )

    value = re.sub(
        r"[^a-z0-9_\u0980-\u09FF]",
        "",
        value
    )

    return value[:50]


# ============================================================================
# Category Intent System
# ============================================================================


def category_alias_map():

    result = {}

    rows = get_categories()

    for row in rows:

        key = row["key"]

        result[normalize_text(key)] = key

        label_clean = normalize_text(
            row["label"]
        )

        if label_clean:
            result[label_clean] = key

        aliases = row["aliases"] or ""

        for alias in aliases.split(","):

            alias = normalize_text(alias)

            if alias:
                result[alias] = key

    # Common direct aliases
    result.update({
        "নাটক": "natok",
        "drama": "natok",
        "natok": "natok",
        "গান": "music",
        "song": "music",
        "ভিডিও": "other",
        "video": "other",
        "মুভি": "movie",
        "movie": "movie",
        "শীত": "winter",
        "শীতের": "winter",
        "শীতের ভিডিও": "winter",
        "বৃষ্টি": "rain",
        "গরম": "summer",
        "ক্রিকেট": "cricket",
        "ফুটবল": "football",
        "স্পোর্টস": "sports",
        "ইসলামিক": "islamic",
        "গজল": "gazal",
        "ভাইরাল": "viral",
        "ট্রেন্ডিং": "trending",
        "কার্টুন": "cartoon",
        "গেম": "gaming",
        "গেমিং": "gaming",
        "ভ্রমণ": "travel",
        "প্রকৃতি": "nature",
        "খাবার": "food",
        "রান্না": "cooking",
    })

    return result


def detect_category_intent(text):

    norm = normalize_text(text)

    if not norm:
        return None

    aliases = category_alias_map()

    # Exact phrase first
    if norm in aliases:
        return aliases[norm]

    # Longest aliases first
    candidates = sorted(
        aliases.items(),
        key=lambda x: len(x[0]),
        reverse=True
    )

    for alias, key in candidates:

        if len(alias) < 2:
            continue

        if re.search(
            r"(^|\s)" +
            re.escape(alias) +
            r"($|\s)",
            norm
        ):
            return key

    # Substring fallback for Bengali phrases
    for alias, key in candidates:

        if len(alias) >= 3 and alias in norm:
            return key

    return None


def is_category_request(text):

    norm = normalize_text(text)

    category = detect_category_intent(norm)

    if not category:
        return False

    request_words = [
        "আছে",
        "আছে কি",
        "দাও",
        "দেন",
        "চাই",
        "লাগবে",
        "পাঠাও",
        "পাঠান",
        "দেও",
        "দিবে",
        "দিবেন",
        "দেখাও",
        "দেখান",
        "দেখতে",
        "কি আছে",
        "কিছু আছে",
        "ভিডিও",
        "কন্টেন্ট",
        "content",
        "show",
        "give",
        "please",
    ]

    if any(
        word in norm
        for word in request_words
    ):
        return True

    # A category alone should also open its category.
    # Example: "নাটক", "শীত", "ক্রিকেট"
    category_row = get_category(category)

    if category_row:
        return True

    return False


# ============================================================================
# Category Buttons
# ============================================================================


CATEGORY_PAGE_SIZE = 12


def category_buttons(
    page=0,
    prefix="usercat"
):

    categories = get_categories()

    total_pages = max(
        1,
        (
            len(categories)
            + CATEGORY_PAGE_SIZE
            - 1
        )
        // CATEGORY_PAGE_SIZE
    )

    page = max(
        0,
        min(
            page,
            total_pages - 1
        )
    )

    start = page * CATEGORY_PAGE_SIZE

    items = categories[
        start:start + CATEGORY_PAGE_SIZE
    ]

    buttons = []

    for i in range(
        0,
        len(items),
        2
    ):

        row = []

        for item in items[i:i + 2]:

            row.append(
                InlineKeyboardButton(
                    item["label"],
                    callback_data=(
                        f"{prefix}:{item['key']}"
                    )
                )
            )

        buttons.append(row)

    nav = []

    if page > 0:

        nav.append(
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=(
                    f"{prefix}_page:{page - 1}"
                )
            )
        )

    if page < total_pages - 1:

        nav.append(
            InlineKeyboardButton(
                "🔽 See More",
                callback_data=(
                    f"{prefix}_page:{page + 1}"
                )
            )
        )

    if nav:
        buttons.append(nav)

    return (
        buttons,
        page,
        total_pages
    )


def category_prompt(
    prefix="usercat",
    page=0,
    heading="📂 Category"
):

    buttons, page, total_pages = category_buttons(
        page,
        prefix
    )

    total = len(get_categories())

    if prefix == "usercat":

        text = (
            f"{heading}\n\n"
            "অবশ্যই! 👇\n"
            "আপনার প্রয়োজনীয় Category নির্বাচন করুন।\n\n"
            f"📂 মোট Category: {total}\n"
            f"📄 Page {page + 1}/{total_pages}"
        )

    else:

        text = (
            "🏷️ **Category নির্বাচন করুন**\n\n"
            "ভিডিওটি কোন Category-তে রাখতে চান "
            "সেটি নির্বাচন করুন। 👇\n\n"
            f"📂 মোট Category: {total}\n"
            f"📄 Page {page + 1}/{total_pages}"
        )

    return (
        text,
        InlineKeyboardMarkup(buttons)
    )


async def show_category_content(
    message,
    category_key
):

    category = get_category(
        category_key
    )

    if not category:

        await message.reply_text(
            "❌ এই Category পাওয়া যায়নি।"
        )

        return

    items = get_contents_by_category(
        category_key,
        10
    )

    if not items:

        await message.reply_text(
            "😔 **এই Category-তে এখনো কোনো "
            "কন্টেন্ট যোগ করা হয়নি।**\n\n"
            f"📂 Category: {category['label']}\n\n"
            "নতুন কন্টেন্ট এলে এখানেই পাওয়া যাবে।",
            parse_mode=ParseMode.MARKDOWN
        )

        return

    buttons = []

    for item in items:

        title = str(
            item["title"]
        )[:55]

        buttons.append([
            InlineKeyboardButton(
                f"🎬 {title}",
                callback_data=(
                    f"send_media_{item['id']}"
                )
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "⬅️ Category List",
            callback_data="usercat_page:0"
        )
    ])

    await message.reply_text(
        f"📂 **{category['label']}**\n\n"
        "অবশ্যই! নিচের কন্টেন্ট থেকে "
        "যেটি চান সেটি নির্বাচন করুন। 👇",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )


# ============================================================================
# Content Search
# ============================================================================


def detect_category(title):

    t = normalize_text(title)

    if any(
        x in t
        for x in [
            "নাটক",
            "drama",
            "natok"
        ]
    ):
        return "natok"

    if any(
        x in t
        for x in [
            "গান",
            "song",
            "audio",
            "গজল",
            "music"
        ]
    ):
        return "music"

    if any(
        x in t
        for x in [
            "মুভি",
            "movie",
            "cinema",
            "ফিল্ম"
        ]
    ):
        return "movie"

    if any(
        x in t
        for x in [
            "ডান্স",
            "dance"
        ]
    ):
        return "dance"

    if any(
        x in t
        for x in [
            "শীত",
            "শীতের",
            "winter"
        ]
    ):
        return "winter"

    if any(
        x in t
        for x in [
            "বৃষ্টি",
            "rain"
        ]
    ):
        return "rain"

    if any(
        x in t
        for x in [
            "গরম",
            "summer",
            "hot"
        ]
    ):
        return "summer"

    return "other"


def search_content(
    query,
    category=None
):

    query = normalize_text(query)

    if not query:
        return None

    if category:

        row = db_execute(
            """
            SELECT *
            FROM contents
            WHERE category=?
            AND lower(title) LIKE ?
            ORDER BY views DESC, id DESC
            LIMIT 1
            """,
            (
                category,
                f"%{query}%"
            ),
            fetchone=True
        )

        if row:
            return row

    row = db_execute(
        """
        SELECT *
        FROM contents
        WHERE lower(title) LIKE ?
        ORDER BY views DESC, id DESC
        LIMIT 1
        """,
        (
            f"%{query}%",
        ),
        fetchone=True
    )

    if row:
        return row

    words = [
        w
        for w in query.split()
        if len(w) >= 2
    ][:4]

    if not words:
        return None

    conditions = [
        "lower(title) LIKE ?"
        for _ in words
    ]

    params = [
        f"%{w}%"
        for w in words
    ]

    if category:

        sql = (
            "SELECT * FROM contents "
            "WHERE category=? AND ("
            + " OR ".join(conditions)
            + ") "
            "ORDER BY views DESC,id DESC "
            "LIMIT 1"
        )

        return db_execute(
            sql,
            (
                category,
                *params
            ),
            fetchone=True
        )

    sql = (
        "SELECT * FROM contents "
        "WHERE ("
        + " OR ".join(conditions)
        + ") "
        "ORDER BY views DESC,id DESC "
        "LIMIT 1"
    )

    return db_execute(
        sql,
        tuple(params),
        fetchone=True
    )


def increment_views(content_id):

    db_execute(
        """
        UPDATE contents
        SET views=views+1
        WHERE id=?
        """,
        (content_id,)
    )


def get_contents_by_category(
    category,
    limit=5
):

    return db_execute(
        """
        SELECT
            id,
            title,
            media_type,
            category,
            views
        FROM contents
        WHERE category=?
        ORDER BY views DESC,id DESC
        LIMIT ?
        """,
        (
            category,
            limit
        ),
        fetch=True
    )


def get_top_trending(limit=5):

    return db_execute(
        """
        SELECT
            id,
            title,
            media_type,
            category,
            views
        FROM contents
        ORDER BY views DESC,id DESC
        LIMIT ?
        """,
        (limit,),
        fetch=True
    )

# ============================================================================
# OpenAI
# ============================================================================


SYSTEM_INSTRUCTIONS = f"""
তুমি একটি দ্রুত, নির্ভুল Telegram AI সহকারী।

প্রধান অ্যাডমিন:
@{ADMIN_USERNAME}

User ID:
{ADMIN_IDS[0]}

নিয়ম:

1. ব্যবহারকারী বাংলায় লিখলে বাংলায় উত্তর দেবে।
2. Banglish হলে সহজ বাংলা/Banglish বুঝে উত্তর দেবে।
3. English হলে English-এ উত্তর দেবে।
4. কোনো কন্টেন্ট Category সম্পর্কে ব্যবহারকারী জিজ্ঞেস করলে
   Category system-এর বাইরে অনুমান করবে না।
5. Bot database-এ থাকা মিডিয়া ছাড়া কোনো মিডিয়া আছে বলে দাবি করবে না।
6. User যদি "নাটক", "গান", "শীত", "ক্রিকেট",
   "বৃষ্টি", "মুভি" ইত্যাদি Category চায়,
   তখন Category selection system ব্যবহার করা হবে।
7. User-এর কথার অর্থ না বুঝলে বানিয়ে উত্তর দেবে না।
8. সংক্ষিপ্ত এবং সরাসরি উত্তর দেবে।
9. অ্যাডমিন সম্পর্কে:
   @{ADMIN_USERNAME}
"""


async def generate_chatgpt_response(
    chat_id,
    user_text
):

    history = get_history(
        chat_id,
        limit=6
    )

    if not openai_client or not OPENAI_API_KEY:

        return (
            "👋 আপনার বার্তা পেয়েছি!\n\n"
            "AI উত্তর দেওয়ার জন্য OpenAI API Key "
            "সঠিকভাবে সেট করা হয়নি।\n\n"
            f"প্রয়োজনে @{ADMIN_USERNAME}-এর "
            "সাথে যোগাযোগ করুন।"
        )

    try:

        inputs = []

        for h in history:

            inputs.append({
                "role": (
                    "assistant"
                    if h["role"] == "assistant"
                    else "user"
                ),
                "content": h["content"]
            })

        inputs.append({
            "role": "user",
            "content": user_text
        })

        response = await asyncio.wait_for(
            openai_client.responses.create(
                model=OPENAI_MODEL,
                instructions=SYSTEM_INSTRUCTIONS,
                input=inputs,
                max_output_tokens=500,
            ),
            timeout=15.0
        )

        answer = getattr(
            response,
            "output_text",
            None
        )

        if answer and answer.strip():

            return answer.strip()

    except asyncio.TimeoutError:

        logger.error(
            "OpenAI request timed out."
        )

    except Exception as e:

        logger.error(
            "OpenAI AI error: %r",
            e
        )

    return (
        "দুঃখিত, এখন AI উত্তর দিতে একটু সমস্যা হচ্ছে। "
        "কিছুক্ষণ পর আবার চেষ্টা করুন।"
    )

# ============================================================================
# AdsGram Bot Integration
# ============================================================================


async def get_adsgram_ad(user_id):

    """
    AdsGram official Telegram Bot integration.

    Endpoint:
    https://api.adsgram.ai/advbot

    Required:
    tgid
    blockid
    language
    token
    """

    if not ADSGRAM_ENABLED:

        logger.warning(
            "AdsGram disabled: BLOCK_ID or TOKEN missing."
        )

        return None

    if not ADSGRAM_NUMERIC_BLOCK_ID:

        logger.warning(
            "AdsGram block ID is invalid."
        )

        return None

    url = (
        "https://api.adsgram.ai/advbot"
        f"?tgid={user_id}"
        f"&blockid={ADSGRAM_NUMERIC_BLOCK_ID}"
        "&language=bn"
        f"&token={ADSGRAM_TOKEN}"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=8
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as response:

                if response.status != 200:

                    logger.warning(
                        "AdsGram returned HTTP %s",
                        response.status
                    )

                    return None

                data = await response.json(
                    content_type=None
                )

                if not isinstance(data, dict):
                    return None

                return data

    except Exception as e:

        logger.warning(
            "AdsGram request failed: %r",
            e
        )

        return None


async def send_adsgram_ad(
    bot,
    chat_id,
    user_id
):

    """
    Sends AdsGram ad before media.

    Returns:
    True  = ad was successfully sent
    False = no ad available / AdsGram disabled
    """

    data = await get_adsgram_ad(
        user_id
    )

    if not data:

        return False

    text_html = data.get(
        "text_html",
        ""
    )

    image_url = data.get(
        "image_url"
    )

    click_url = data.get(
        "click_url"
    )

    button_name = data.get(
        "button_name"
    )

    reward_url = data.get(
        "reward_url"
    )

    button_reward_name = data.get(
        "button_reward_name"
    )

    buttons = []

    if click_url and button_name:

        buttons.append([
            InlineKeyboardButton(
                str(button_name)[:64],
                url=click_url
            )
        ])

    if reward_url and button_reward_name:

        buttons.append([
            InlineKeyboardButton(
                str(button_reward_name)[:64],
                url=reward_url
            )
        ])

    reply_markup = (
        InlineKeyboardMarkup(buttons)
        if buttons
        else None
    )

    if not text_html:

        text_html = "📢 Advertisement"

    try:

        if image_url:

            await bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=text_html[:1024],
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                protect_content=True,
            )

        else:

            await bot.send_message(
                chat_id=chat_id,
                text=text_html[:4096],
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                protect_content=True,
            )

        logger.info(
            "AdsGram ad sent to user=%s",
            user_id
        )

        return True

    except Exception as e:

        logger.warning(
            "Could not send AdsGram ad: %r",
            e
        )

        return False

# ============================================================================
# Admin notifications
# ============================================================================


async def send_admin_alert(
    bot,
    text,
    reply_markup=None
):

    for admin_id in ADMIN_IDS:

        try:

            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup,
            )

        except Exception as e:

            logger.error(
                "Failed to notify admin %s: %s",
                admin_id,
                e
            )


async def notify_admin_missing_content(
    bot,
    user,
    content_type,
    query
):

    text = (
        "📢 **[নতুন কন্টেন্টের ডিমান্ড]**\n\n"
        f"👤 **ইউজার:** "
        f"{user.first_name} "
        f"(@{user.username or 'নাই'})\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"📁 **Category:** {content_type}\n"
        f"🔍 **রিকুয়েস্ট:** `{query}`\n"
        f"⏰ **সময়:** {now_str()}\n\n"
        f"👉 @{ADMIN_USERNAME} "
        "কন্টেন্টটি আপলোড করতে পারেন।"
    )

    keyboard = None

    if user.username:

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"✉️ Reply @{user.username}",
                    url=(
                        f"https://t.me/"
                        f"{user.username}"
                    ),
                )
            ]
        ])

    await send_admin_alert(
        bot,
        text,
        keyboard
    )


async def notify_admin_user_help(
    bot,
    user,
    user_msg
):

    text = (
        "⚠️ **[ইউজার সাহায্য চেয়েছে]**\n\n"
        f"👤 **User:** "
        f"{user.first_name} "
        f"(@{user.username or 'N/A'})\n"
        f"🆔 **ID:** `{user.id}`\n"
        f"⏰ **Time:** {now_str()}\n\n"
        f"💬 **বার্তা:**\n"
        f"_{user_msg}_"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 সরাসরি মেসেজ দিন",
                url=(
                    f"https://t.me/{user.username}"
                    if user.username
                    else f"tg://user?id={user.id}"
                ),
            )
        ]
    ])

    await send_admin_alert(
        bot,
        text,
        keyboard
    )

# ============================================================================
# Media Delivery
# ============================================================================


async def deliver_media(
    update,
    row
):

    message = update.effective_message
    user = update.effective_user

    content_id = row["id"]
    media_type = row["media_type"]
    file_id = row["file_id"]
    title = row["title"]

    # ------------------------------------------------------------
    # Ads first
    # ------------------------------------------------------------

    if user:

        await send_adsgram_ad(
            update.get_bot(),
            message.chat_id,
            user.id
        )

    # ------------------------------------------------------------
    # View count
    # ------------------------------------------------------------

    increment_views(
        content_id
    )

    await message.reply_text(
        f"🎬 **{title}**\n\n"
        "⏳ পাঠানো হচ্ছে, দয়া করে অপেক্ষা করুন...",
        parse_mode=ParseMode.MARKDOWN
    )

    try:

        if media_type == "video":

            await message.reply_video(
                video=file_id,
                caption=f"🎬 {title}",
                supports_streaming=True,
            )

        elif media_type == "audio":

            await message.reply_audio(
                audio=file_id,
                caption=f"🎵 {title}"
            )

        elif media_type == "photo":

            await message.reply_photo(
                photo=file_id,
                caption=f"🖼️ {title}"
            )

        elif media_type == "animation":

            await message.reply_animation(
                animation=file_id,
                caption=f"✨ {title}"
            )

        else:

            await message.reply_document(
                document=file_id,
                caption=f"📄 {title}"
            )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 এডমিন: @"
                    + ADMIN_USERNAME,
                    url=(
                        f"https://t.me/"
                        f"{ADMIN_USERNAME}"
                    ),
                )
            ]
        ])

        await message.reply_text(
            "✅ কন্টেন্ট সফলভাবে পাঠানো হয়েছে!\n"
            "আর কোনো নাটক, গান বা ভিডিও লাগলে "
            "নাম লিখুন। 🤝",
            reply_markup=keyboard,
        )

    except Exception as e:

        logger.error(
            "Error sending media %s: %r",
            content_id,
            e
        )

        await send_admin_alert(
            update.get_bot(),
            f"❌ Error sending file ID "
            f"{content_id}: {e}"
        )

        await message.reply_text(
            "❌ ফাইলটি পাঠাতে সমস্যা হয়েছে। "
            "এডমিনকে জানানো হয়েছে।"
        )


async def handle_admin_media_upload(
    update,
    context
):

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

    context.user_data["pending_media"] = {
        "media_type": media_type,
        "file_id": file_id,
    }

    context.user_data["waiting_title"] = True

    await message.reply_text(
        f"📥 **{media_type.upper()} মিডিয়া ফাইল পেয়েছি!**\n\n"
        "📝 এই কন্টেন্টের **নাম (Title)** লিখে পাঠান।\n\n"
        "যেমন:\n"
        "`নতুন ঈদের নাটক`\n"
        "`বাংলা গান`",
        parse_mode=ParseMode.MARKDOWN
    )

    return True


async def handle_admin_title_save(
    update,
    context
):

    user = update.effective_user
    message = update.effective_message

    if (
        not user
        or not is_admin(user.id)
        or not context.user_data.get(
            "waiting_title"
        )
    ):
        return False

    title = (
        message.text.strip()
        if message.text
        else ""
    )

    if not title:

        await message.reply_text(
            "❌ Title খালি রাখা যাবে না।"
        )

        return True

    pending = context.user_data.get(
        "pending_media"
    )

    if not pending:

        context.user_data[
            "waiting_title"
        ] = False

        return False

    context.user_data[
        "pending_title"
    ] = title

    context.user_data[
        "waiting_title"
    ] = False

    context.user_data[
        "waiting_category"
    ] = True

    text, markup = category_prompt(
        prefix="admincat",
        page=0
    )

    await message.reply_text(
        f"✅ **নাম গ্রহণ করা হয়েছে:**\n"
        f"🎬 {title}\n\n"
        + text,
        reply_markup=markup,
        parse_mode=ParseMode.MARKDOWN
    )

    return True

# ============================================================================
# Weather / Prayer
# ============================================================================


async def get_weather():

    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=23.8103"
        "&longitude=90.4125"
        "&current=temperature_2m,"
        "relative_humidity_2m,"
        "weather_code,"
        "wind_speed_10m"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=6
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as res:

                if res.status != 200:
                    return None

                data = await res.json()

        c = data.get(
            "current",
            {}
        )

        return (
            f"🌤️ **{PRAYER_CITY} আবহাওয়া**\n\n"
            f"🌡️ তাপমাত্রা: "
            f"**{c.get('temperature_2m', '?')}°C**\n"
            f"💧 আর্দ্রতা: "
            f"**{c.get('relative_humidity_2m', '?')}%**\n"
            f"💨 বাতাস: "
            f"**{c.get('wind_speed_10m', '?')} km/h**"
        )

    except Exception as e:

        logger.warning(
            "Weather API error: %r",
            e
        )

        return None


_prayer_cache_date = None
_prayer_cache_data = None


async def get_prayer_data():

    global _prayer_cache_date
    global _prayer_cache_data

    today = datetime.now(
        TZ
    ).strftime("%Y-%m-%d")

    if (
        _prayer_cache_date == today
        and _prayer_cache_data
    ):
        return _prayer_cache_data

    url = (
        "https://api.aladhan.com/v1/timingsByCity"
        f"?city={PRAYER_CITY}"
        f"&country={PRAYER_COUNTRY}"
        f"&method={PRAYER_METHOD}"
    )

    try:

        timeout = aiohttp.ClientTimeout(
            total=8
        )

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.get(url) as res:

                if res.status != 200:
                    return None

                data = await res.json()

        timings = (
            data
            .get("data", {})
            .get("timings", {})
        )

        if timings:

            _prayer_cache_date = today
            _prayer_cache_data = timings

        return timings

    except Exception as e:

        logger.warning(
            "Prayer API error: %r",
            e
        )

        return None


async def get_prayer_times():

    t = await get_prayer_data()

    if not t:
        return None

    return (
        f"🕌 **{PRAYER_CITY} নামাজের সময়সূচি**\n\n"
        f"🌅 ফজর: **{t.get('Fajr', '-')}**\n"
        f"☀️ সূর্যোদয়: {t.get('Sunrise', '-')}\n"
        f"🕛 যোহর: **{t.get('Dhuhr', '-')}**\n"
        f"🌇 আসর: **{t.get('Asr', '-')}**\n"
        f"🌆 মাগরিব: **{t.get('Maghrib', '-')}**\n"
        f"🌙 এশা: **{t.get('Isha', '-')}**"
    )

# ============================================================================
# Automatic Notifications
# ============================================================================


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

    text = (
        f"🕐 **সময়: {h12}:00 {ampm} "
        "(বাংলাদেশ সময়)**\n\n"
    )

    if hour == WAKE_HOUR:

        text += (
            "🌅 **ঘুম থেকে ওঠার সময়!**\n"
            "সুপ্রভাত! পানি পান করুন এবং "
            "আজকের দিনের পরিকল্পনা করুন। ☀️💧\n\n"
        )

    if hour in STUDY_HOURS:

        text += (
            "📚 **পড়াশোনার সময়!**\n"
            "এখন মনোযোগ দিয়ে পড়াশোনা/"
            "স্কিল শেখার জন্য সময় দিন। 📖\n\n"
        )

    if hour in SPORTS_HOURS:

        text += (
            "⚽ **খেলার/ব্যায়ামের সময়!**\n"
            "কিছুক্ষণ খেলাধুলা বা শরীরচর্চা করুন। "
            "🏃‍♂️\n\n"
        )

    if hour in WORK_HOURS:

        text += (
            "💼 **কাজের সময়!**\n"
            "গুরুত্বপূর্ণ কাজগুলো গুছিয়ে করুন। "
            "✅\n\n"
        )

    if hour == SLEEP_HOUR:

        text += (
            "😴 **ঘুমানোর সময়!**\n"
            "সময়মতো ঘুমান এবং শরীর ও মনকে "
            "বিশ্রাম দিন। 🌙\n\n"
        )

    if hour == 12:

        text += (
            "🍚 দুপুর হয়েছে—খাওয়া, বিশ্রাম ও "
            "প্রয়োজনীয় কাজের সময় ঠিক রাখুন।\n\n"
        )

    if hour == 18:

        text += (
            "🌇 সন্ধ্যা হয়েছে। নামাজ ও পরিবারের "
            "জন্য কিছু সময় রাখুন।\n\n"
        )

    if (
        hour not in STUDY_HOURS
        and hour not in SPORTS_HOURS
        and hour not in WORK_HOURS
        and hour != SLEEP_HOUR
        and hour != WAKE_HOUR
    ):

        text += (
            "✅ আপনার কাজের তালিকা দেখে "
            "পরের এক ঘণ্টার লক্ষ্য ঠিক করুন।"
        )

    return text


async def send_to_enabled_chats(
    bot,
    text
):

    chats = get_notification_chats()

    sent = 0

    for row in chats:

        try:

            await bot.send_message(
                chat_id=row["chat_id"],
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )

            sent += 1

        except Exception as e:

            logger.warning(
                "Auto message failed for chat %s: %s",
                row["chat_id"],
                e
            )

    return sent


async def send_hourly_notification(
    bot,
    now
):

    key = now.strftime(
        "%Y-%m-%d-%H"
    )

    if get_state(
        "last_hourly_notification"
    ) == key:

        return

    set_state(
        "last_hourly_notification",
        key
    )

    text = hourly_message(
        now.hour
    )

    sent = await send_to_enabled_chats(
        bot,
        text
    )

    logger.info(
        "Hourly notification sent to %s chats.",
        sent
    )


async def send_prayer_notifications(
    bot,
    now
):

    timings = await get_prayer_data()

    if not timings:
        return

    today = now.strftime(
        "%Y-%m-%d"
    )

    current_minutes = (
        now.hour * 60
        + now.minute
    )

    for key, label in PRAYER_NAMES.items():

        value = timings.get(
            key,
            ""
        )

        match = re.match(
            r"^(\d{1,2}):(\d{2})",
            str(value)
        )

        if not match:
            continue

        target = (
            int(match.group(1)) * 60
            + int(match.group(2))
        )

        if abs(
            current_minutes - target
        ) <= 1:

            state_key = (
                f"prayer_sent_"
                f"{today}_{key}"
            )

            if get_state(state_key) == "1":
                continue

            set_state(
                state_key,
                "1"
            )

            text = (
                f"🕌 **{label} নামাজের সময় হয়েছে**\n\n"
                f"⏰ সময়: **{value}**\n"
                "🤲 নামাজ আদায়ের জন্য প্রস্তুত হোন।"
            )

            sent = await send_to_enabled_chats(
                bot,
                text
            )

            logger.info(
                "Prayer notification %s sent "
                "to %s chats.",
                label,
                sent
            )


async def automatic_notification_loop(
    application
):

    logger.info(
        "Automatic notifications started. "
        "Study=%s Sports=%s Sleep=%s",
        STUDY_HOURS,
        SPORTS_HOURS,
        SLEEP_HOUR,
    )

    while True:

        try:

            if AUTO_MESSAGES_ENABLED:

                now = datetime.now(TZ)

                if now.minute == 0:

                    await send_hourly_notification(
                        application.bot,
                        now
                    )

                await send_prayer_notifications(
                    application.bot,
                    now
                )

            await asyncio.sleep(20)

        except asyncio.CancelledError:

            logger.info(
                "Automatic notification loop stopped."
            )

            raise

        except Exception as e:

            logger.error(
                "Automatic notification loop error: %r",
                e
            )

            await asyncio.sleep(20)

# ============================================================================
# Helpers
# ============================================================================


user_last_action = {}


def check_rate_limit(
    user_id,
    interval=0.7
):

    current = time.time()

    last = user_last_action.get(
        user_id,
        0
    )

    if current - last < interval:
        return False

    user_last_action[
        user_id
    ] = current

    return True


def is_admin(user_id):

    return user_id in ADMIN_IDS

# ============================================================================
# Commands
# ============================================================================


async def start_command(
    update,
    context
):

    user = update.effective_user

    save_user(user)
    save_chat(
        update.effective_chat
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎬 নাটক চাই",
                callback_data="show_dramas"
            ),
            InlineKeyboardButton(
                "🎵 গান চাই",
                callback_data="show_songs"
            )
        ],
        [
            InlineKeyboardButton(
                "🔥 ট্রেন্ডিং",
                callback_data="show_trending"
            ),
            InlineKeyboardButton(
                "📂 সব Category",
                callback_data="usercat_page:0"
            )
        ],
        [
            InlineKeyboardButton(
                "🌤️ আবহাওয়া",
                callback_data="show_weather"
            )
        ],
        [
            InlineKeyboardButton(
                "👑 এডমিন: @"
                + ADMIN_USERNAME,
                url=(
                    f"https://t.me/"
                    f"{ADMIN_USERNAME}"
                )
            )
        ]
    ])

    await update.effective_message.reply_text(
        f"👋 আসসালামু আলাইকুম "
        f"**{user.first_name}**!\n\n"
        "আমি আপনার **AI Telegram Bot**।\n\n"
        "✨ যেকোনো প্রশ্ন করতে পারেন।\n"
        "🎬 নাটক/গান/ভিডিওর নাম লিখে "
        "খুঁজতে পারেন।\n"
        "📂 অথবা Category-এর নাম লিখুন।\n\n"
        "উদাহরণ:\n"
        "• নাটক\n"
        "• নাটক দেন\n"
        "• শীত\n"
        "• শীতের ভিডিও দেখাও\n"
        "• ক্রিকেট আছে?\n\n"
        "💡 যা জানতে চান সরাসরি লিখুন।",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )


async def help_command(
    update,
    context
):

    await update.effective_message.reply_text(
        "📖 **বটের ব্যবহারবিধি:**\n\n"
        "1. যেকোনো প্রশ্ন লিখুন → AI উত্তর দেবে।\n"
        "2. Category-এর নাম লিখুন → সেই Category দেখাবে।\n"
        "3. নাটক/গান/ভিডিওর নাম লিখুন → "
        "ডেটাবেজে থাকলে পাঠাবে।\n"
        "4. /trending → ট্রেন্ডিং কন্টেন্ট\n"
        "5. /weather → আবহাওয়া\n"
        "6. /prayer → নামাজের সময়\n"
        "7. /categories → সব Category\n"
        "8. /auto_on → অটো নোটিফিকেশন চালু\n"
        "9. /auto_off → অটো নোটিফিকেশন বন্ধ\n\n"
        "👑 প্রধান অ্যাডমিন: "
        f"@{ADMIN_USERNAME}",
        parse_mode=ParseMode.MARKDOWN
    )


async def contact_command(
    update,
    context
):

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 এডমিনকে মেসেজ দিন",
                url=(
                    f"https://t.me/"
                    f"{ADMIN_USERNAME}"
                )
            )
        ]
    ])

    await update.effective_message.reply_text(
        f"👑 **এডমিন যোগাযোগ**\n\n"
        f"@{ADMIN_USERNAME}\n"
        f"ID: `{ADMIN_IDS[0]}`",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )


async def admin_panel_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):

        await update.effective_message.reply_text(
            "⛔ এই কমান্ডটি শুধুমাত্র "
            "এডমিনের জন্য।"
        )

        return

    await update.effective_message.reply_text(
        f"👑 **এডমিন প্যানেল "
        f"(@{ADMIN_USERNAME})**\n\n"
        "📥 ভিডিও/অডিও/ছবি পাঠান → "
        "Title → Category → DB Save হবে।\n\n"
        "📂 Category Management:\n"
        "/categories - Category list\n"
        "/addcategory - নতুন Category\n"
        "/editcategory - Category edit\n"
        "/delcategory - Category delete\n\n"
        "📚 Content:\n"
        "/list - কন্টেন্ট তালিকা\n"
        "/stats - পরিসংখ্যান\n"
        "/delete <ID> - কন্টেন্ট Delete\n\n"
        "🔔 Notification:\n"
        "/auto_on\n"
        "/auto_off\n"
        "/notify_test",
        parse_mode=ParseMode.MARKDOWN
    )


async def categories_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):

        # User-দেরও category list দেখানো যাবে
        text, markup = category_prompt(
            prefix="usercat",
            page=0,
            heading="📂 সব Category"
        )

        await update.effective_message.reply_text(
            text,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN
        )

        return

    rows = get_categories(
        active_only=False
    )

    if not rows:

        await update.effective_message.reply_text(
            "📭 কোনো Category নেই।"
        )

        return

    lines = [
        "📂 **Category List**\n"
    ]

    for index, row in enumerate(
        rows,
        1
    ):

        status = (
            "✅"
            if row["active"]
            else "❌"
        )

        lines.append(
            f"{index}. {status} "
            f"`{row['key']}` → "
            f"{row['label']}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)[:4000],
        parse_mode=ParseMode.MARKDOWN
    )


async def addcategory_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if len(context.args) < 2:

        await update.effective_message.reply_text(
            "ব্যবহার:\n"
            "/addcategory key | label | aliases\n\n"
            "উদাহরণ:\n"
            "/addcategory winter2 | ❄️ শীতের ভিডিও 2 | "
            "শীতের ভিডিও,শীত ২,winter 2"
        )

        return

    raw = " ".join(
        context.args
    )

    parts = [
        p.strip()
        for p in raw.split("|")
    ]

    key = clean_category_key(
        parts[0]
    )

    label = (
        parts[1]
        if len(parts) > 1
        else key
    )

    aliases = (
        parts[2]
        if len(parts) > 2
        else label
    )

    if not key:

        await update.effective_message.reply_text(
            "❌ Category key সঠিক নয়।"
        )

        return

    if category_exists(key):

        await update.effective_message.reply_text(
            "❌ এই Category আগে থেকেই আছে।"
        )

        return

    max_row = db_execute(
        """
        SELECT MAX(sort_order) AS m
        FROM categories
        """,
        fetchone=True
    )

    next_order = (
        (max_row["m"] or 0) + 1
        if max_row
        else 1
    )

    db_execute(
        """
        INSERT INTO categories(
            key,
            label,
            aliases,
            sort_order,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            key,
            label,
            aliases,
            next_order,
            now_str(),
        )
    )

    await update.effective_message.reply_text(
        "✅ **নতুন Category যোগ হয়েছে।**\n\n"
        f"🔑 Key: `{key}`\n"
        f"🏷️ Label: {label}\n"
        f"🔎 Alias: {aliases}",
        parse_mode=ParseMode.MARKDOWN
    )


async def editcategory_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if len(context.args) < 3:

        await update.effective_message.reply_text(
            "ব্যবহার:\n"
            "/editcategory key | নতুন label | নতুন aliases\n\n"
            "উদাহরণ:\n"
            "/editcategory winter | ❄️ শীতের ভিডিও | "
            "শীত,শীতের ভিডিও,winter"
        )

        return

    raw = " ".join(
        context.args
    )

    parts = [
        p.strip()
        for p in raw.split("|")
    ]

    key = clean_category_key(
        parts[0]
    )

    label = parts[1]

    aliases = parts[2]

    row = get_category(
        key
    )

    if not row:

        await update.effective_message.reply_text(
            "❌ এই Category পাওয়া যায়নি।\n"
            "আগে /categories দিয়ে key দেখুন।"
        )

        return

    db_execute(
        """
        UPDATE categories
        SET label=?,
            aliases=?
        WHERE key=?
        """,
        (
            label,
            aliases,
            key
        )
    )

    await update.effective_message.reply_text(
        "✅ **Category Edit হয়েছে।**\n\n"
        f"🔑 Key: `{key}`\n"
        f"🏷️ Label: {label}\n"
        f"🔎 Alias: {aliases}",
        parse_mode=ParseMode.MARKDOWN
    )


async def delcategory_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.effective_message.reply_text(
            "ব্যবহার:\n"
            "/delcategory <key>\n\n"
            "উদাহরণ:\n"
            "/delcategory winter"
        )

        return

    key = clean_category_key(
        context.args[0]
    )

    row = get_category(
        key
    )

    if not row:

        await update.effective_message.reply_text(
            "❌ Category পাওয়া যায়নি।"
        )

        return

    # Existing content is not deleted.
    # Category is only disabled.
    db_execute(
        """
        UPDATE categories
        SET active=0
        WHERE key=?
        """,
        (key,)
    )

    await update.effective_message.reply_text(
        "✅ Category বন্ধ করা হয়েছে।\n\n"
        f"📂 `{key}`\n\n"
        "এই Category-এর পুরোনো content "
        "ডিলিট করা হয়নি।",
        parse_mode=ParseMode.MARKDOWN
    )


async def list_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    rows = db_execute(
        """
        SELECT
            id,
            title,
            media_type,
            category,
            views
        FROM contents
        ORDER BY id DESC
        LIMIT 30
        """,
        fetch=True
    )

    if not rows:

        await update.effective_message.reply_text(
            "📭 এখনো কোনো কন্টেন্ট নেই।"
        )

        return

    lines = [
        "📚 **সংরক্ষিত কন্টেন্ট:**\n"
    ]

    labels = get_category_labels()

    for r in rows:

        label = labels.get(
            r["category"],
            r["category"]
        )

        lines.append(
            f"🆔 `{r['id']}` | "
            f"🎬 **{r['title']}** | "
            f"📁 {label} | "
            f"👁️ {r['views']}"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)[:4000],
        parse_mode=ParseMode.MARKDOWN
    )


async def delete_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.effective_message.reply_text(
            "ব্যবহার: `/delete <ID>`",
            parse_mode=ParseMode.MARKDOWN
        )

        return

    try:

        cid = int(
            context.args[0]
        )

        db_execute(
            "DELETE FROM contents WHERE id=?",
            (cid,)
        )

        await update.effective_message.reply_text(
            f"✅ ID `{cid}` ডিলিট হয়েছে।",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:

        await update.effective_message.reply_text(
            f"❌ ডিলিট করতে সমস্যা: {e}"
        )


async def stats_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    u = db_execute(
        "SELECT COUNT(*) c FROM users",
        fetchone=True
    )["c"]

    c = db_execute(
        "SELECT COUNT(*) c FROM contents",
        fetchone=True
    )["c"]

    v = db_execute(
        "SELECT SUM(views) s FROM contents",
        fetchone=True
    )["s"] or 0

    chats = db_execute(
        "SELECT COUNT(*) c FROM chats",
        fetchone=True
    )["c"]

    cats = db_execute(
        "SELECT COUNT(*) c FROM categories "
        "WHERE active=1",
        fetchone=True
    )["c"]

    await update.effective_message.reply_text(
        f"📊 **বট স্ট্যাটিস্টিক্স**\n\n"
        f"👤 ইউজার: **{u}**\n"
        f"💬 চ্যাট: **{chats}**\n"
        f"🎬 কন্টেন্ট: **{c}**\n"
        f"📂 Active Category: **{cats}**\n"
        f"👁️ ভিউ: **{v}**",
        parse_mode=ParseMode.MARKDOWN
    )


async def auto_on_command(
    update,
    context
):

    save_chat(
        update.effective_chat
    )

    set_chat_notifications(
        update.effective_chat.id,
        True
    )

    await update.effective_message.reply_text(
        "🔔 এই চ্যাটে অটো নোটিফিকেশন চালু হয়েছে।"
    )


async def auto_off_command(
    update,
    context
):

    save_chat(
        update.effective_chat
    )

    set_chat_notifications(
        update.effective_chat.id,
        False
    )

    await update.effective_message.reply_text(
        "🔕 এই চ্যাটে অটো নোটিফিকেশন বন্ধ হয়েছে।"
    )


async def notify_test_command(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    await update.effective_message.reply_text(
        hourly_message(
            datetime.now(TZ).hour
        ),
        parse_mode=ParseMode.MARKDOWN
    )


async def trending_command(
    update,
    context
):

    items = get_top_trending(10)

    if not items:

        await update.effective_message.reply_text(
            "📭 কোনো কন্টেন্ট নেই।"
        )

        return

    buttons = []

    for index, item in enumerate(
        items,
        1
    ):

        buttons.append([
            InlineKeyboardButton(
                f"{index}. 🎬 "
                f"{item['title'][:55]}",
                callback_data=(
                    f"send_media_{item['id']}"
                )
            )
        ])

    await update.effective_message.reply_text(
        "🔥 **ট্রেন্ডিং কন্টেন্ট:**\n\n"
        "যেটি চান সেটি নির্বাচন করুন।",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
        parse_mode=ParseMode.MARKDOWN
    )


async def weather_command(
    update,
    context
):

    await update.effective_message.reply_text(
        (
            await get_weather()
        )
        or
        "❌ আবহাওয়া তথ্য পাওয়া যায়নি।"
    )


async def prayer_command(
    update,
    context
):

    await update.effective_message.reply_text(
        (
            await get_prayer_times()
        )
        or
        "❌ নামাজের সময় পাওয়া যায়নি।"
    )

# ============================================================================
# Callback Queries
# ============================================================================


async def handle_callback_query(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # ------------------------------------------------------------
    # Admin category pagination
    # ------------------------------------------------------------

    if data.startswith(
        "admincat_page:"
    ):

        try:
            page = int(
                data.split(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            page = 0

        text, markup = category_prompt(
            prefix="admincat",
            page=page
        )

        await query.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN
        )

        return

    # ------------------------------------------------------------
    # Admin category selection
    # ------------------------------------------------------------

    if data.startswith(
        "admincat:"
    ):

        key = data.split(
            ":",
            1
        )[1]

        if not is_admin(
            query.from_user.id
        ):

            await query.message.reply_text(
                "❌ শুধু Admin Category নির্বাচন করতে পারবেন।"
            )

            return

        if not context.user_data.get(
            "waiting_category"
        ):

            await query.message.reply_text(
                "ℹ️ বর্তমানে কোনো মিডিয়া "
                "Category নির্বাচন করার অপেক্ষায় নেই।"
            )

            return

        pending = context.user_data.get(
            "pending_media"
        )

        title = context.user_data.get(
            "pending_title"
        )

        if not pending or not title:

            await query.message.reply_text(
                "❌ Pending upload পাওয়া যায়নি। "
                "ভিডিওটি আবার পাঠান।"
            )

            return

        category = get_category(
            key
        )

        if not category:

            await query.message.reply_text(
                "❌ Category পাওয়া যায়নি।"
            )

            return

        new_id = db_execute(
            """
            INSERT INTO contents(
                title,
                media_type,
                file_id,
                category,
                views,
                added_by,
                created_at
            )
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (
                title,
                pending["media_type"],
                pending["file_id"],
                key,
                query.from_user.id,
                now_str(),
            )
        )

        context.user_data.pop(
            "pending_media",
            None
        )

        context.user_data.pop(
            "pending_title",
            None
        )

        context.user_data[
            "waiting_category"
        ] = False

        await query.message.reply_text(
            "🎉 **SUCCESSFUL! "
            "কন্টেন্ট সংরক্ষণ হয়েছে।**\n\n"
            f"🆔 ID: `{new_id}`\n"
            f"🎬 Title: **{title}**\n"
            f"📁 Media: `{pending['media_type']}`\n"
            f"🏷️ Category: "
            f"**{category['label']}**\n\n"
            "👤 User এখন এই Category "
            "সিলেক্ট করলে কন্টেন্টটি পাবে।",
            parse_mode=ParseMode.MARKDOWN
        )

        return

    # ------------------------------------------------------------
    # User category pagination
    # ------------------------------------------------------------

    if data.startswith(
        "usercat_page:"
    ):

        try:
            page = int(
                data.split(
                    ":",
                    1
                )[1]
            )
        except ValueError:
            page = 0

        text, markup = category_prompt(
            prefix="usercat",
            page=page
        )

        await query.message.reply_text(
            text,
            reply_markup=markup,
            parse_mode=ParseMode.MARKDOWN
        )

        return

    # ------------------------------------------------------------
    # User category selection
    # ------------------------------------------------------------

    if data.startswith(
        "usercat:"
    ):

        key = data.split(
            ":",
            1
        )[1]

        await show_category_content(
            query.message,
            key
        )

        return

    # ------------------------------------------------------------
    # Drama
    # ------------------------------------------------------------

    if data == "show_dramas":

        await show_category_content(
            query.message,
            "natok"
        )

        return

    # ------------------------------------------------------------
    # Songs
    # ------------------------------------------------------------

    if data == "show_songs":

        await show_category_content(
            query.message,
            "music"
        )

        return

    # ------------------------------------------------------------
    # Trending
    # ------------------------------------------------------------

    if data == "show_trending":

        items = get_top_trending(
            5
        )

        if not items:

            await query.message.reply_text(
                "📭 কোনো কন্টেন্ট নেই।"
            )

            return

        buttons = []

        for i, item in enumerate(
            items,
            1
        ):

            buttons.append([
                InlineKeyboardButton(
                    f"{i}. 🎬 "
                    f"{item['title'][:55]}",
                    callback_data=(
                        f"send_media_{item['id']}"
                    )
                )
            ])

        await query.message.reply_text(
            "🔥 **ট্রেন্ডিং কন্টেন্ট:**\n\n"
            "যেটি চান সেটি নির্বাচন করুন।",
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
            parse_mode=ParseMode.MARKDOWN
        )

        return

    # ------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------

    if data == "show_weather":

        await query.message.reply_text(
            (
                await get_weather()
            )
            or
            "❌ আবহাওয়া তথ্য পাওয়া যায়নি।"
        )

        return

    # ------------------------------------------------------------
    # Media
    # ------------------------------------------------------------

    if data.startswith(
        "send_media_"
    ):

        try:

            cid = int(
                data.split("_")[-1]
            )

        except ValueError:

            await query.message.reply_text(
                "❌ ID সঠিক নয়।"
            )

            return

        row = db_execute(
            """
            SELECT *
            FROM contents
            WHERE id=?
            """,
            (cid,),
            fetchone=True
        )

        if row:

            await deliver_media(
                update,
                row
            )

        else:

            await query.message.reply_text(
                "❌ কন্টেন্ট পাওয়া যায়নি।"
            )

        return

# ============================================================================
# Group/member update handling
# ============================================================================


async def my_chat_member_handler(
    update,
    context
):

    cm = update.my_chat_member

    if not cm or not cm.chat:
        return

    save_chat(
        cm.chat
    )

    logger.info(
        "MY_CHAT_MEMBER | chat_id=%s | type=%s | old=%s | new=%s",
        cm.chat.id,
        cm.chat.type,
        cm.old_chat_member.status,
        cm.new_chat_member.status,
    )

# ============================================================================
# Fast Everyday Replies
# ============================================================================


RAIN_REPLIES = [
    "আহা, আজ তো বৃষ্টি! 🌧️",
    "বৃষ্টি নামলেই মনটা অন্যরকম হয়ে যায়। ☔",
    "আজ আকাশের মুড একদম বৃষ্টিময়। 🌧️",
    "বৃষ্টি + চা = সুন্দর কম্বিনেশন। ☕🌧️",
]


HEAT_REPLIES = [
    "গরম বেশি হলে পানি পান করুন এবং রোদ এড়িয়ে চলুন। ☀️💧",
    "গরমে শরীর ঠান্ডা রাখতে পর্যাপ্ত পানি পান করুন। 💧",
    "বাইরে গেলে পানি সঙ্গে রাখুন এবং সম্ভব হলে ছায়ায় থাকুন। ☀️",
]


MORNING_REPLIES = [
    "সুপ্রভাত! 🌅 আজকের দিনটা সুন্দর হোক।",
    "সুপ্রভাত! ☀️ পানি পান করে দিন শুরু করুন।",
    "শুভ সকাল! আজকের গুরুত্বপূর্ণ কাজগুলো আগে গুছিয়ে নিন।",
]


WORK_REPLIES = [
    "কাজটা একবারে এক ধাপ করে করুন। 💼💪",
    "আজকের জরুরি কাজগুলো আগে শেষ করুন। ✅",
    "কাজের মাঝে ছোট বিরতি নিতে ভুলবেন না। 🙂",
]


STUDY_REPLIES = [
    "পড়ার সময় ফোনটা একটু দূরে রাখুন। 📚📵",
    "অল্প অল্প করে নিয়মিত পড়াই সবচেয়ে কাজে দেয়। 📖",
    "আজকের জন্য একটি ছোট পড়ার লক্ষ্য ঠিক করুন। 🎯📚",
]


SLEEP_REPLIES = [
    "ঘুমের সময় হলে ফোনটা পাশে রেখে বিশ্রাম নিন। 😴🌙",
    "ভালো ঘুম শরীর ও মনের জন্য দরকার। 💤",
    "রাত বেশি জাগবেন না—আগামীকাল ফ্রেশ থাকুন। 🌙",
]


def smart_everyday_reply(
    text
):

    norm = normalize_text(
        text
    )

    rain = any(
        x in norm
        for x in [
            "বৃষ্টি",
            "বৃষ্টির",
            "বৃষ্টি হচ্ছে",
            "rain"
        ]
    )

    heat = any(
        x in norm
        for x in [
            "গরম",
            "গরম লাগ",
            "তাপমাত্রা বেশি",
            "heat",
            "hot"
        ]
    )

    morning = any(
        x in norm
        for x in [
            "সুপ্রভাত",
            "শুভ সকাল",
            "সকাল হয়েছে"
        ]
    )

    study = any(
        x in norm
        for x in [
            "পড়তে বস",
            "পড়াশোনা",
            "স্টাডি",
            "study",
            "পড়ার সময়"
        ]
    )

    work = any(
        x in norm
        for x in [
            "কাজ করতে",
            "কাজের সময়",
            "অফিস",
            "কাজে বস",
            "work"
        ]
    )

    sleep = any(
        x in norm
        for x in [
            "ঘুম",
            "ঘুমাব",
            "ঘুমাতে",
            "ঘুমানোর সময়",
            "sleep"
        ]
    )

    if rain:
        return random.choice(
            RAIN_REPLIES
        )

    if heat:
        return random.choice(
            HEAT_REPLIES
        )

    if morning:
        return random.choice(
            MORNING_REPLIES
        )

    if study:
        return random.choice(
            STUDY_REPLIES
        )

    if work:
        return random.choice(
            WORK_REPLIES
        )

    if sleep:
        return random.choice(
            SLEEP_REPLIES
        )

    return None

# ============================================================================
# Admin Help Intent
# ============================================================================


async def handle_admin_help(
    message,
    context,
    user,
    text
):

    norm = normalize_text(
        text
    )

    help_words = [
        "এডমিন চাই",
        "অ্যাডমিন চাই",
        "admin help",
        "এডমিনের সাথে",
        "সমস্যা হয়েছে",
        "অভিযোগ",
        "admin contact",
        "contact admin"
    ]

    if any(
        w in norm
        for w in help_words
    ):

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 এডমিন @"
                    + ADMIN_USERNAME
                    + "-কে মেসেজ দিন",
                    url=(
                        f"https://t.me/"
                        f"{ADMIN_USERNAME}"
                    )
                )
            ]
        ])

        await message.reply_text(
            f"👑 **এডমিনের সাথে যোগাযোগ:** "
            f"@{ADMIN_USERNAME}",
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )

        await notify_admin_user_help(
            context.bot,
            user,
            text
        )

        return True

    return False

# ============================================================================
# Main Message Processor
# ============================================================================


async def handle_all_messages(
    update,
    context
):

    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    logger.info(
        "MESSAGE RECEIVED | chat_id=%s | "
        "chat_type=%s | user=%s | text=%r",
        chat.id,
        chat.type,
        user.username or user.id,
        message.text,
    )

    save_user(user)
    save_chat(chat)

    # ------------------------------------------------------------
    # Admin media upload
    # ------------------------------------------------------------

    if await handle_admin_media_upload(
        update,
        context
    ):
        return

    if not message.text:
        return

    text = message.text.strip()

    if not text:
        return

    # ------------------------------------------------------------
    # Admin title
    # ------------------------------------------------------------

    if await handle_admin_title_save(
        update,
        context
    ):
        return

    # ------------------------------------------------------------
    # Rate limit
    # ------------------------------------------------------------

    if not check_rate_limit(
        user.id
    ):

        await message.reply_text(
            "⏳ একটু ধীরে মেসেজ করুন, "
            "আমি শুনছি। 🙂"
        )

        return

    norm = normalize_text(
        text
    )

    # ------------------------------------------------------------
    # Admin help
    # ------------------------------------------------------------

    if await handle_admin_help(
        message,
        context,
        user,
        text
    ):
        return

    # ------------------------------------------------------------
    # Weather / prayer FIRST
    # ------------------------------------------------------------

    if any(
        w in norm
        for w in [
            "আবহাওয়া",
            "weather",
            "তাপমাত্রা"
        ]
    ):

        await message.reply_text(
            (
                await get_weather()
            )
            or
            "❌ আবহাওয়া তথ্য পাওয়া যায়নি।"
        )

        return

    if any(
        w in norm
        for w in [
            "নামাজের সময়",
            "নামাজ কখন",
            "আজকের নামাজ",
            "prayer time"
        ]
    ):

        await message.reply_text(
            (
                await get_prayer_times()
            )
            or
            "❌ নামাজের সময় পাওয়া যায়নি।"
        )

        return

    # ------------------------------------------------------------
    # CATEGORY SYSTEM
    #
    # Examples:
    # নাটক
    # নাটক আছে
    # নাটক দেন
    # নাটক চাই
    # শীত
    # শীতের ভিডিও
    # শীতের কি আছে
    # শীতের ভিডিও দেখাও
    # ক্রিকেট আছে?
    # ------------------------------------------------------------

    category_key = detect_category_intent(
        text
    )

    if category_key and is_category_request(
        text
    ):

        category = get_category(
            category_key
        )

        if category:

            await show_category_content(
                message,
                category_key
            )

            return

    # ------------------------------------------------------------
    # Exact content search
    # ------------------------------------------------------------

    is_drama_query = any(
        k in norm
        for k in [
            "নাটক",
            "drama",
            "natok"
        ]
    )

    is_song_query = any(
        k in norm
        for k in [
            "গান",
            "song",
            "গজল",
            "audio",
            "music"
        ]
    )

    is_video_query = any(
        k in norm
        for k in [
            "ভিডিও",
            "video",
            "মুভি",
            "movie"
        ]
    )

    is_content_intent = (
        is_drama_query
        or is_song_query
        or is_video_query
        or any(
            r in norm
            for r in [
                "চাই",
                "দাও",
                "দেন",
                "পাঠাও",
                "পাঠান",
                "লাগবে",
                "দেও"
            ]
        )
    )

    if is_content_intent:

        target_category = None

        if is_drama_query:
            target_category = "natok"

        elif is_song_query:
            target_category = "music"

        clean_query = norm

        remove_words = [
            "আমাকে",
            "একটি",
            "একটা",
            "নাটক",
            "গান",
            "ভিডিও",
            "দাও",
            "দেন",
            "চাই",
            "লাগবে",
            "নতুন",
            "প্লিজ",
            "please",
            "দেও",
            "পাঠাও",
            "পাঠান",
            "আছে",
            "দেখাও",
            "দেখান",
        ]

        for rm in remove_words:

            clean_query = re.sub(
                r"\b"
                + re.escape(rm)
                + r"\b",
                " ",
                clean_query
            )

        clean_query = re.sub(
            r"\s+",
            " ",
            clean_query
        ).strip()

        if clean_query:

            found = search_content(
                clean_query,
                target_category
            )

            if found:

                await deliver_media(
                    update,
                    found
                )

                return

        # Category itself
        if (
            is_drama_query
            and not clean_query
        ):

            await show_category_content(
                message,
                "natok"
            )

            return

        if (
            is_song_query
            and not clean_query
        ):

            await show_category_content(
                message,
                "music"
            )

            return

        if (
            is_drama_query
            or is_song_query
            or is_video_query
        ):

            category_to_show = (
                target_category
                or "other"
            )

            recs = get_contents_by_category(
                category_to_show,
                3
            )

            buttons = []

            for r in recs:

                buttons.append([
                    InlineKeyboardButton(
                        f"🎬 {r['title'][:55]}",
                        callback_data=(
                            f"send_media_{r['id']}"
                        )
                    )
                ])

            buttons.append([
                InlineKeyboardButton(
                    "📂 Category দেখুন",
                    callback_data="usercat_page:0"
                )
            ])

            buttons.append([
                InlineKeyboardButton(
                    "📩 এডমিনকে আপলোডের অনুরোধ",
                    url=(
                        f"https://t.me/"
                        f"{ADMIN_USERNAME}"
                    )
                )
            ])

            rec_text = ""

            if recs:

                rec_text = (
                    "\n\n💡 জনপ্রিয় কন্টেন্ট:\n"
                    + "\n".join(
                        f"• **{r['title']}**"
                        for r in recs
                    )
                )

            await message.reply_text(
                "😔 **কাঙ্ক্ষিত কন্টেন্ট "
                "পাওয়া যায়নি।**"
                + rec_text
                + "\n\n"
                "নামটি ঠিকভাবে লিখে আবার চেষ্টা করুন।",
                reply_markup=InlineKeyboardMarkup(
                    buttons
                ),
                parse_mode=ParseMode.MARKDOWN
            )

            await notify_admin_missing_content(
                context.bot,
                user,
                category_to_show,
                text
            )

            return

    # ------------------------------------------------------------
    # Fast everyday replies
    # ------------------------------------------------------------

    smart_reply = smart_everyday_reply(
        text
    )

    if smart_reply:

        await message.reply_text(
            smart_reply
        )

        return

    # ------------------------------------------------------------
    # AI
    # ------------------------------------------------------------

    save_message(
        chat.id,
        user.id,
        "user",
        text
    )

    await message.reply_chat_action(
        "typing"
    )

    ai_reply = await generate_chatgpt_response(
        chat.id,
        text
    )

    save_message(
        chat.id,
        0,
        "assistant",
        ai_reply
    )

    await message.reply_text(
        ai_reply
    )

# ============================================================================
# Global Error
# ============================================================================


async def global_error_handler(
    update,
    context
):

    logger.error(
        "Exception while handling update: %s",
        context.error
    )

    try:

        tb = "".join(
            traceback.format_exception(
                type(context.error),
                context.error,
                context.error.__traceback__
            )
        )

    except Exception:

        tb = str(
            context.error
        )

    user = (
        update.effective_user
        if isinstance(update, Update)
        else None
    )

    try:

        await send_admin_alert(
            context.bot,
            "⚠️ **[ERROR ALERT]**\n"
            f"User: "
            f"{user.first_name if user else 'Unknown'}\n\n"
            f"`{str(context.error)}`\n\n"
            f"Traceback:\n"
            f"`{tb[-1200:]}`"
        )

    except Exception:
        pass

# ============================================================================
# Startup
# ============================================================================


async def post_init(
    application
):

    # Clear old webhook before polling
    try:

        await application.bot.delete_webhook(
            drop_pending_updates=False
        )

        me = await application.bot.get_me()

        logger.info(
            "BOT CONNECTED | username=@%s | id=%s",
            me.username,
            me.id
        )

    except Exception as e:

        logger.error(
            "Bot startup check failed: %r",
            e
        )

    # Ads status
    if ADSGRAM_ENABLED:

        logger.info(
            "AdsGram ENABLED | block=%s",
            ADSGRAM_NUMERIC_BLOCK_ID
        )

    else:

        logger.warning(
            "AdsGram DISABLED. "
            "Set ADSGRAM_BLOCK_ID and ADSGRAM_TOKEN."
        )

    # Automatic notifications
    if AUTO_MESSAGES_ENABLED:

        application.create_task(
            automatic_notification_loop(
                application
            ),
            name="automatic_notification_loop"
        )

# ============================================================================
# Run Bot
# ============================================================================


def run_bot_once():

    if not BOT_TOKEN:

        print(
            "❌ Error: BOT_TOKEN is missing!"
        )

        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # ------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start_command
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "contact",
            contact_command
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_panel_command
        )
    )

    app.add_handler(
        CommandHandler(
            "categories",
            categories_command
        )
    )

    app.add_handler(
        CommandHandler(
            "addcategory",
            addcategory_command
        )
    )

    app.add_handler(
        CommandHandler(
            "editcategory",
            editcategory_command
        )
    )

    app.add_handler(
        CommandHandler(
            "delcategory",
            delcategory_command
        )
    )

    app.add_handler(
        CommandHandler(
            "list",
            list_command
        )
    )

    app.add_handler(
        CommandHandler(
            "delete",
            delete_command
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats_command
        )
    )

    app.add_handler(
        CommandHandler(
            "auto_on",
            auto_on_command
        )
    )

    app.add_handler(
        CommandHandler(
            "auto_off",
            auto_off_command
        )
    )

    app.add_handler(
        CommandHandler(
            "notify_test",
            notify_test_command
        )
    )

    app.add_handler(
        CommandHandler(
            "trending",
            trending_command
        )
    )

    app.add_handler(
        CommandHandler(
            "weather",
            weather_command
        )
    )

    app.add_handler(
        CommandHandler(
            "prayer",
            prayer_command
        )
    )

    # ------------------------------------------------------------
    # Callback
    # ------------------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            handle_callback_query
        )
    )

    # ------------------------------------------------------------
    # Group/member updates
    # ------------------------------------------------------------

    app.add_handler(
        ChatMemberHandler(
            my_chat_member_handler,
            ChatMemberHandler.MY_CHAT_MEMBER
        )
    )

    # ------------------------------------------------------------
    # Media
    # ------------------------------------------------------------

    app.add_handler(
        MessageHandler(
            (
                filters.VIDEO
                | filters.AUDIO
                | filters.PHOTO
                | filters.Document.ALL
                | filters.ANIMATION
            ),
            handle_all_messages
        )
    )

    # ------------------------------------------------------------
    # Text
    # ------------------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_all_messages
        )
    )

    app.add_error_handler(
        global_error_handler
    )

    # ------------------------------------------------------------
    # Startup information
    # ------------------------------------------------------------

    print(
        "=================================================="
    )

    print(
        "🤖 Telegram Bot Running"
    )

    print(
        f"👑 Admin: @{ADMIN_USERNAME} "
        f"(ID: {ADMIN_IDS[0]})"
    )

    print(
        f"🧠 AI Model: {OPENAI_MODEL}"
    )

    print(
        "📂 Dynamic Category System: ON"
    )

    print(
        "⚡ Fast Intent Replies: ON"
    )

    print(
        "📢 AdsGram: "
        + (
            "ON"
            if ADSGRAM_ENABLED
            else "OFF"
        )
    )

    if ADSGRAM_ENABLED:

        print(
            f"📢 AdsGram Block: "
            f"{ADSGRAM_NUMERIC_BLOCK_ID}"
        )

    print(
        "🔔 Auto notifications: "
        + (
            "ON"
            if AUTO_MESSAGES_ENABLED
            else "OFF"
        )
    )

    print(
        f"📚 Study hours: {STUDY_HOURS}"
    )

    print(
        f"⚽ Sports hours: {SPORTS_HOURS}"
    )

    print(
        f"🌅 Wake hour: {WAKE_HOUR}:00"
    )

    print(
        f"💼 Work hours: {WORK_HOURS}"
    )

    print(
        f"😴 Sleep hour: {SLEEP_HOUR}:00"
    )

    print(
        "=================================================="
    )

    # ------------------------------------------------------------
    # Long polling
    # ------------------------------------------------------------

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False
    )

# ============================================================================
# Main
# ============================================================================


def main():

    """
    Start bot and automatically recover
    from temporary network failures.
    """

    init_db()

    retry_delay = 10

    while True:

        try:

            run_bot_once()

            logger.warning(
                "Bot polling stopped. "
                "Restarting in %s seconds...",
                retry_delay
            )

            time.sleep(
                retry_delay
            )

        except KeyboardInterrupt:

            logger.info(
                "Bot stopped by user."
            )

            break

        except Exception as e:

            logger.error(
                "Bot crashed / network connection failed: %r",
                e
            )

            logger.error(
                "Restarting automatically in %s seconds...",
                retry_delay
            )

            time.sleep(
                retry_delay
            )


if __name__ == "__main__":
    main()
