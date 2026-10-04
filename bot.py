# bot.py
# Telegram AI Assistant + Saved Content Bot
# Python 3.10+
#
# Install:
# pip install -U python-telegram-bot aiohttp openai
#
# Required environment variables:
# BOT_TOKEN=...
# ADMIN_ID=123456789
#
# Optional:
# ADMIN_USERNAME=YourTelegramUsername
# OPENAI_API_KEY=...
# OPENAI_MODEL=gpt-5.6-mini
# DB_PATH=bot.db
#
# ADMIN_USERNAME should NOT include @.
#
# This file keeps the features from the supplied bot:
# AI chat, saved video/audio/photo/document/animation,
# admin upload, list/stats/delete/broadcast, weather, prayer,
# hourly messages, rate limit and SQLite storage.
#
# New behavior:
# - Better intent/content detection for Bangla + Banglish + English.
# - Fast Reply inline buttons.
# - Missing-content suggestions from popular/trending saved content.
# - Admin gets an automatic notification for unknown/error/problem cases.
# - User gets a clickable "Admin" button.
# - Admin uploads media -> bot asks title -> saves successfully.
# - Popular content gets view_count increased when sent.
# - Category-aware suggestions: song/drama/movie/dance/video/photo.
# - AI is only used when fixed/content/weather/prayer handling does not apply.
#
# NOTE:
# Telegram does not let a bot directly open a private chat with an arbitrary
# user unless Telegram permits it. The tg://user?id=... button is the safest
# clickable admin/user contact form supported by Telegram clients.

import asyncio
import logging
import os
import re
import sqlite3
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Optional

import aiohttp

try:
    from openai import AsyncOpenAI
except Exception:
    AsyncOpenAI = None

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8721334265") or 8721334265)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "tomalchowdhury2").strip().lstrip("@")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip()

DB_PATH = os.getenv("DB_PATH", "bot.db").strip()

TZ = timezone(timedelta(hours=6))  # Bangladesh
PRAYER_CITY = os.getenv("PRAYER_CITY", "Bhairab").strip()
PRAYER_COUNTRY = os.getenv("PRAYER_COUNTRY", "Bangladesh").strip()

RATE_LIMIT_SECONDS = 1.5
MAX_HISTORY = 10

client = (
    AsyncOpenAI(api_key=OPENAI_API_KEY)
    if OPENAI_API_KEY and AsyncOpenAI
    else None
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Per-user last message time.
rate_state = {}

# User asks for a content name after bot says it can help.
pending_content = {}

# Admin upload state is stored in context.user_data:
# waiting_media -> waiting_title -> saved.

# =========================================================
# CONTENT / REQUEST WORDS
# =========================================================

CONTENT_WORDS = [
    "video",
    "ভিডিও",
    "ভিডিয়ো",
    "ভিডিওটা",
    "ভিডিওটি",
    "গান",
    "গানটা",
    "গানটি",
    "song",
    "songs",
    "audio",
    "অডিও",
    "নাটক",
    "নাটকটা",
    "নাটকটি",
    "drama",
    "movie",
    "movies",
    "মুভি",
    "সিনেমা",
    "ছবি",
    "ছবিটা",
    "ছবিটি",
    "photo",
    "picture",
    "animation",
    "document",
    "ফাইল",
    "file",
    "ডান্স",
    "dance",
]

REQUEST_WORDS = [
    "দাও",
    "দেন",
    "দিবে",
    "দিবেন",
    "চাই",
    "লাগবে",
    "পাঠাও",
    "পাঠান",
    "send",
    "give",
    "want",
    "please",
    "দেখাও",
    "দেখতে চাই",
    "দেখবো",
    "দেখব",
    "দেখতে",
    "পাবো",
    "পাব",
    "দিতে পারো",
    "দিতে পারবেন",
    "দিতে পারবে",
]

SONG_WORDS = [
    "গান", "song", "songs", "music", "মিউজিক", "অডিও", "audio"
]
DRAMA_WORDS = [
    "নাটক", "drama", "episode", "এপিসোড", "সিরিজ", "series"
]
MOVIE_WORDS = [
    "মুভি", "movie", "movies", "সিনেমা", "film", "ফিল্ম"
]
DANCE_WORDS = [
    "ডান্স", "dance", "নাচ"
]
PHOTO_WORDS = [
    "ছবি", "photo", "picture", "pic", "image", "ফটো"
]
VIDEO_WORDS = [
    "ভিডিও", "video", "clip", "reel", "রিল"
]

# =========================================================
# TEXT HELPERS
# =========================================================

def normalize_text(text: str) -> str:
    if not text:
        return ""
    t = str(text).strip().lower()
    t = t.replace("ё", "е")
    t = re.sub(r"[\u200b-\u200f\ufeff]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def contains_any(text: str, words) -> bool:
    t = normalize_text(text)
    return any(w in t for w in words)


def detect_requested_category(text: str) -> Optional[str]:
    t = normalize_text(text)

    if contains_any(t, SONG_WORDS):
        return "song"
    if contains_any(t, DRAMA_WORDS):
        return "drama"
    if contains_any(t, MOVIE_WORDS):
        return "movie"
    if contains_any(t, DANCE_WORDS):
        return "dance"
    if contains_any(t, PHOTO_WORDS):
        return "photo"
    if contains_any(t, VIDEO_WORDS):
        return "video"

    return None


def is_content_request(text: str) -> bool:
    t = normalize_text(text)

    # Explicit content + request.
    if (
        any(x in t for x in CONTENT_WORDS)
        and any(x in t for x in REQUEST_WORDS)
    ):
        return True

    # Natural short requests such as:
    # "শাকিবের গান", "ওই নাটকটা", "Arijit song"
    if detect_requested_category(t):
        request_like = [
            "চাই", "দাও", "দেন", "পাঠাও", "পাঠান",
            "দেখাও", "দেখতে", "পাবো", "পাব",
            "please", "give", "send", "want",
            "ওই", "এই", "একটা", "একটি",
        ]
        if any(x in t for x in request_like):
            return True

    return False


def extract_content_query(text: str) -> str:
    t = normalize_text(text)

    remove_words = (
        CONTENT_WORDS
        + REQUEST_WORDS
        + [
            "আমাকে", "একটা", "একটি", "আমার",
            "প্লিজ", "please", "টা", "টি", "টাও",
            "দিয়ে", "দিয়ে দাও", "দিয়ে দেন",
            "দিতে", "পারো", "পারেন", "পারবে",
            "কিছু", "একটু", "দেখতে",
            "চাই", "চাচ্ছি",
        ]
    )

    # Longest first so phrases are removed before individual words.
    for word in sorted(set(remove_words), key=len, reverse=True):
        t = re.sub(
            r"(?<!\S)" + re.escape(word) + r"(?!\S)",
            " ",
            t,
        )

    t = re.sub(r"[^\w\u0980-\u09ff\s\-\.]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    return t


def infer_query_without_request_words(text: str) -> str:
    query = extract_content_query(text)
    if query:
        return query

    # If user says only "গান দাও", query is empty. Category search will handle it.
    return ""


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(sql, params=(), fetch=False, fetchone=False):
    with db_connect() as conn:
        cur = conn.execute(sql, params)
        if fetchone:
            return cur.fetchone()
        if fetch:
            return cur.fetchall()
        conn.commit()
        return cur.lastrowid


def init_db():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                updated_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id INTEGER PRIMARY KEY,
                chat_type TEXT,
                title TEXT,
                username TEXT,
                updated_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                user_id INTEGER,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS contents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                media_type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                category TEXT DEFAULT 'other',
                added_by INTEGER,
                view_count INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Safe migration for old databases.
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(contents)").fetchall()
        }

        if "view_count" not in cols:
            conn.execute(
                "ALTER TABLE contents ADD COLUMN view_count INTEGER DEFAULT 0"
            )

        if "category" not in cols:
            conn.execute(
                "ALTER TABLE contents ADD COLUMN category TEXT DEFAULT 'other'"
            )

        if "added_by" not in cols:
            conn.execute(
                "ALTER TABLE contents ADD COLUMN added_by INTEGER"
            )

        if "created_at" not in cols:
            conn.execute(
                "ALTER TABLE contents ADD COLUMN created_at TEXT"
            )

        conn.commit()


def now_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def save_user(user):
    if not user:
        return

    db_execute("""
        INSERT INTO users (
            user_id, username, first_name, last_name, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            updated_at=excluded.updated_at
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
        user.last_name or "",
        now_str(),
    ))


def save_chat(chat):
    if not chat:
        return

    title = (
        getattr(chat, "title", None)
        or getattr(chat, "first_name", None)
        or ""
    )

    username = getattr(chat, "username", None) or ""

    db_execute("""
        INSERT INTO chats (
            chat_id, chat_type, title, username, updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            chat_type=excluded.chat_type,
            title=excluded.title,
            username=excluded.username,
            updated_at=excluded.updated_at
    """, (
        chat.id,
        chat.type,
        title,
        username,
        now_str(),
    ))


def save_message(chat_id, user_id, role, content):
    db_execute("""
        INSERT INTO messages (
            chat_id, user_id, role, content, created_at
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        chat_id,
        user_id,
        role,
        content,
        now_str(),
    ))


def get_history(chat_id, limit=10):
    rows = db_execute("""
        SELECT role, content
        FROM messages
        WHERE chat_id=?
        ORDER BY id DESC
        LIMIT ?
    """, (chat_id, limit), fetch=True)

    rows = list(reversed(rows))

    # OpenAI roles must be user/assistant.
    return [
        {
            "role": row["role"],
            "content": row["content"],
        }
        for row in rows
        if row["role"] in ("user", "assistant")
    ]


def get_state(key):
    row = db_execute(
        "SELECT value FROM bot_state WHERE key=?",
        (key,),
        fetchone=True,
    )
    return row["value"] if row else None


def set_state(key, value):
    db_execute("""
        INSERT INTO bot_state(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))


# =========================================================
# ADMIN / USER CONTACT
# =========================================================

def is_admin(user_id: int) -> bool:
    return bool(ADMIN_ID and user_id == ADMIN_ID)


async def admin_only(update: Update) -> bool:
    user = update.effective_user
    if user and is_admin(user.id):
        return True

    msg = update.effective_message
    if msg:
        await msg.reply_text("⛔ এই command শুধু Admin-এর জন্য।")

    return False


def admin_url() -> Optional[str]:
    if ADMIN_USERNAME:
        return f"https://t.me/{ADMIN_USERNAME}"
    if ADMIN_ID:
        return f"tg://user?id={ADMIN_ID}"
    return None


def admin_keyboard():
    url = admin_url()

    if not url:
        return None

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Admin-কে Message করুন", url=url)]
    ])


def user_contact_url(user_id: int) -> str:
    return f"tg://user?id={user_id}"


async def notify_admin(
    context: ContextTypes.DEFAULT_TYPE,
    reason: str,
    update: Optional[Update] = None,
    error: Optional[Exception] = None,
):
    if not ADMIN_ID:
        logger.warning("ADMIN_ID is not configured; cannot notify admin.")
        return

    lines = [
        "🚨 BOT ADMIN ALERT",
        "",
        f"📌 Reason: {reason}",
    ]

    user = update.effective_user if update else None
    chat = update.effective_chat if update else None
    msg = update.effective_message if update else None

    if user:
        display_name = " ".join(
            x for x in [user.first_name, user.last_name]
            if x
        ).strip() or "Unknown"

        username = f"@{user.username}" if user.username else "No username"

        lines.extend([
            "",
            f"👤 User: {display_name}",
            f"🆔 User ID: {user.id}",
            f"🔗 Username: {username}",
        ])

    if chat:
        lines.extend([
            f"💬 Chat ID: {chat.id}",
            f"📦 Chat type: {chat.type}",
        ])

    if msg and msg.text:
        lines.extend([
            "",
            "📝 Message:",
            msg.text[:1500],
        ])

    if error:
        lines.extend([
            "",
            "❌ Error:",
            repr(error)[:2000],
        ])

    keyboard = None
    if user:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👤 User-কে Message",
                    url=user_contact_url(user.id),
                )
            ]
        ])

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="\n".join(lines)[:4000],
            reply_markup=keyboard,
        )
    except Exception:
        logger.exception("Failed to notify admin")


# =========================================================
# CONTENT SEARCH / TRENDING
# =========================================================

def detect_category(title: str) -> str:
    t = normalize_text(title)

    if contains_any(t, SONG_WORDS):
        return "song"
    if contains_any(t, DRAMA_WORDS):
        return "drama"
    if contains_any(t, MOVIE_WORDS):
        return "movie"
    if contains_any(t, DANCE_WORDS):
        return "dance"
    if contains_any(t, PHOTO_WORDS):
        return "photo"
    if contains_any(t, VIDEO_WORDS):
        return "video"

    return "other"


def search_content(query: str, category: Optional[str] = None):
    query = normalize_text(query)

    # Exact-ish title search first.
    if query:
        if category:
            row = db_execute("""
                SELECT *
                FROM contents
                WHERE lower(title) LIKE ?
                  AND category=?
                ORDER BY view_count DESC, id DESC
                LIMIT 1
            """, (f"%{query}%", category), fetchone=True)
        else:
            row = db_execute("""
                SELECT *
                FROM contents
                WHERE lower(title) LIKE ?
                ORDER BY view_count DESC, id DESC
                LIMIT 1
            """, (f"%{query}%",), fetchone=True)

        if row:
            return row

    # Word-based fallback.
    words = [
        x for x in query.split()
        if len(x) >= 2
    ]

    if words:
        conditions = []
        params = []

        for word in words[:8]:
            conditions.append("lower(title) LIKE ?")
            params.append(f"%{word}%")

        category_sql = ""
        if category:
            category_sql = " AND category=?"
            params.append(category)

        row = db_execute(
            f"""
                SELECT *
                FROM contents
                WHERE ({" OR ".join(conditions)})
                {category_sql}
                ORDER BY view_count DESC, id DESC
                LIMIT 1
            """,
            tuple(params),
            fetchone=True,
        )

        if row:
            return row

    # If user asked only "গান দাও", return popular item of category.
    if category:
        return db_execute("""
            SELECT *
            FROM contents
            WHERE category=?
            ORDER BY view_count DESC, id DESC
            LIMIT 1
        """, (category,), fetchone=True)

    return None


def get_popular(category: Optional[str] = None, limit=5):
    if category:
        return db_execute("""
            SELECT *
            FROM contents
            WHERE category=?
            ORDER BY view_count DESC, id DESC
            LIMIT ?
        """, (category, limit), fetch=True)

    return db_execute("""
        SELECT *
        FROM contents
        ORDER BY view_count DESC, id DESC
        LIMIT ?
    """, (limit,), fetch=True)


def get_trending(category: Optional[str] = None, limit=5):
    # Trending = recent content, with view count as the secondary ranking.
    if category:
        return db_execute("""
            SELECT *
            FROM contents
            WHERE category=?
            ORDER BY id DESC, view_count DESC
            LIMIT ?
        """, (category, limit), fetch=True)

    return db_execute("""
        SELECT *
        FROM contents
        ORDER BY id DESC, view_count DESC
        LIMIT ?
    """, (limit,), fetch=True)


def increment_view(content_id: int):
    db_execute("""
        UPDATE contents
        SET view_count=COALESCE(view_count, 0)+1
        WHERE id=?
    """, (content_id,))


def content_label(category: Optional[str]) -> str:
    return {
        "song": "গান",
        "drama": "নাটক",
        "movie": "মুভি",
        "dance": "ডান্স ভিডিও",
        "video": "ভিডিও",
        "photo": "ছবি",
        "other": "কনটেন্ট",
        None: "কনটেন্ট",
    }.get(category, "কনটেন্ট")


# =========================================================
# FAST REPLY / SUGGESTIONS
# =========================================================

def suggestion_keyboard(category: Optional[str] = None):
    rows = []

    if category:
        rows.append([
            InlineKeyboardButton(
                f"🔥 জনপ্রিয় {content_label(category)}",
                callback_data=f"popular:{category}",
            ),
            InlineKeyboardButton(
                "📈 ট্রেন্ডিং",
                callback_data=f"trending:{category}",
            ),
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                "🔥 জনপ্রিয়",
                callback_data="popular:all",
            ),
            InlineKeyboardButton(
                "📈 ট্রেন্ডিং",
                callback_data="trending:all",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            "🎵 গান",
            callback_data="popular:song",
        ),
        InlineKeyboardButton(
            "🎬 নাটক",
            callback_data="popular:drama",
        ),
    ])

    admin = admin_url()
    if admin:
        rows.append([
            InlineKeyboardButton(
                "👑 Admin",
                url=admin,
            )
        ])

    return InlineKeyboardMarkup(rows)


def format_suggestion_list(rows, heading: str) -> str:
    if not rows:
        return ""

    lines = [heading, ""]

    for i, row in enumerate(rows, 1):
        views = int(row["view_count"] or 0)
        lines.append(
            f"{i}. {row['title']}  👁️ {views}"
        )

    return "\n".join(lines)


async def send_suggestions(
    update: Update,
    category: Optional[str],
    missing_query: str,
):
    message = update.effective_message
    label = content_label(category)

    popular = get_popular(category, 3)

    if category == "drama":
        if popular:
            text = (
                f"দুঃখিত, **{missing_query or 'এই'}** নাটকটি এখনো আমার "
                "saved content-এ নেই।\n\n"
                "আপনি চাইলে নিচের বর্তমান/জনপ্রিয় নাটকগুলো দেখতে পারেন:"
            )
        else:
            text = (
                f"দুঃখিত, **{missing_query or 'এই'}** নাটকটি এখনো নেই।\n\n"
                "নতুন নাটক যোগ হলে এখানে পাওয়া যাবে।"
            )

    elif category == "song":
        if popular:
            text = (
                f"দুঃখিত, **{missing_query or 'এই'}** গানটি এখনো saved নেই।\n\n"
                "চাইলে আমাদের জনপ্রিয় গানগুলোর একটি দিতে পারি:"
            )
        else:
            text = (
                f"দুঃখিত, **{missing_query or 'এই'}** গানটি এখনো saved নেই।"
            )

    else:
        if popular:
            text = (
                f"দুঃখিত, **{missing_query or 'এই'} {label}** এখনো "
                "saved content-এ নেই।\n\n"
                f"চাইলে জনপ্রিয় {label} থেকে একটি দিতে পারি:"
            )
        else:
            text = (
                f"দুঃখিত, **{missing_query or 'এই'} {label}** এখনো নেই।"
            )

    await message.reply_text(
        text,
        reply_markup=suggestion_keyboard(category),
    )


# =========================================================
# SEND SAVED CONTENT
# =========================================================

async def send_saved_content(
    update: Update,
    row,
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
):
    message = update.effective_message

    try:
        await message.reply_text(
            f"🎬 {row['title']}\n\n⏳ পাঠানো হচ্ছে..."
        )

        media_type = row["media_type"]
        file_id = row["file_id"]

        if media_type == "video":
            await message.reply_video(
                video=file_id,
                supports_streaming=True,
            )

        elif media_type == "audio":
            await message.reply_audio(
                audio=file_id,
            )

        elif media_type == "photo":
            await message.reply_photo(
                photo=file_id,
            )

        elif media_type == "animation":
            await message.reply_animation(
                animation=file_id,
            )

        else:
            await message.reply_document(
                document=file_id,
            )

        increment_view(row["id"])

        # Fast follow-up instead of unnecessary long text.
        await message.reply_text(
            "⚡ আরও কিছু লাগলে নিচের অপশন ব্যবহার করুন।",
            reply_markup=suggestion_keyboard(row["category"]),
        )

        return True

    except Exception as e:
        logger.exception("CONTENT ERROR")

        await message.reply_text(
            "❌ Content পাঠাতে সমস্যা হয়েছে।"
        )

        if context:
            await notify_admin(
                context,
                "Saved content send failed",
                update,
                e,
            )

        return False


# =========================================================
# PENDING CONTENT
# =========================================================

def set_pending(chat_id, user_id, category=None, original_query=""):
    pending_content[chat_id] = {
        "user_id": user_id,
        "category": category,
        "original_query": original_query,
        "time": time.time(),
    }


def pending_exists(chat_id, user_id):
    data = pending_content.get(chat_id)

    if not data:
        return False

    if data["user_id"] != user_id:
        return False

    if time.time() - data["time"] > 600:
        pending_content.pop(chat_id, None)
        return False

    return True


def clear_pending(chat_id):
    pending_content.pop(chat_id, None)


# =========================================================
# RATE LIMIT
# =========================================================

def check_rate_limit(user_id: int) -> bool:
    now = time.monotonic()
    last = rate_state.get(user_id, 0)

    if now - last < RATE_LIMIT_SECONDS:
        return False

    rate_state[user_id] = now
    return True


# =========================================================
# OPENAI
# =========================================================

SYSTEM_PROMPT = """
তুমি একটি Telegram group assistant।

তোমার প্রধান নিয়ম:
1. ব্যবহারকারীর কথার উদ্দেশ্য বুঝে সরাসরি উত্তর দাও।
2. বাংলা হলে স্বাভাবিক বাংলায় উত্তর দাও।
3. Banglish হলে সহজ বাংলা/Banglish-এ উত্তর দাও।
4. English হলে English-এ উত্তর দিতে পারো।
5. অকারণে "আচ্ছা", "ঠিক আছে", "আরও বলুন", "আমি শুনছি" বলবে না।
6. ব্যবহারকারী গান/নাটক/মুভি/ভিডিও/ছবি চাইলে saved-content system আগে থেকেই সেটা handle করে। তুমি নিজের কাছে media আছে বলে দাবি করবে না।
7. কোনো তথ্য নিশ্চিত না হলে বানিয়ে বলবে না।
8. উত্তর ছোট, পরিষ্কার, বন্ধুসুলভ এবং helpful রাখবে।
9. ব্যবহারকারী রাগ করলে শান্তভাবে উত্তর দেবে।
10. Admin বা human help দরকার হলে বলবে যে Admin-এর সাথে যোগাযোগ করা যাবে; কিন্তু saved content না থাকা অবস্থায় মিথ্যা promise করবে না।
"""


async def ai_understand_message(chat_id: int, user_text: str) -> dict:
    """Understand the user's meaning before routing the message.

    One small Responses API call decides whether this is normal chat,
    content request, weather, prayer, help/admin, etc.  For content requests
    it can also pick the closest saved content by ID when possible.
    """
    if not client:
        return {
            "intent": "unknown",
            "category": None,
            "query": "",
            "content_id": None,
            "reply": "",
        }

    history = get_history(chat_id, 8)
    catalog_rows = db_execute("""
        SELECT id, title, category
        FROM contents
        ORDER BY view_count DESC, id DESC
        LIMIT 60
    """, fetch=True)

    catalog = [
        {
            "id": int(row["id"]),
            "title": row["title"],
            "category": row["category"],
        }
        for row in catalog_rows
    ]

    prompt = {
        "task": "Understand the user's message and choose the correct bot action.",
        "user_message": user_text,
        "recent_conversation": history,
        "saved_content_catalog": catalog,
        "rules": [
            "Understand Bangla, Banglish and English naturally; do not rely on keywords.",
            "If the user asks for any saved media/content, use intent content_request.",
            "For content_request, infer category and the meaningful search query.",
            "If a saved_content_catalog item clearly matches the user's request, return its numeric content_id.",
            "Do not claim media exists unless content_id is selected or the database search later finds it.",
            "If the user is simply chatting, answer like a helpful ChatGPT-style assistant in the user's language.",
            "If the user asks about weather, use intent weather.",
            "If the user asks about prayer/namaz times, use intent prayer.",
            "If the user asks for admin/human help, use intent admin_help.",
            "If a request is unclear, use intent clarify and write one short clarification question.",
            "Return JSON only; no markdown and no extra text.",
        ],
        "json_format": {
            "intent": "chat | content_request | weather | prayer | admin_help | clarify | unknown",
            "category": "song | drama | movie | dance | video | photo | audio | document | animation | other | null",
            "query": "short meaningful search phrase or empty string",
            "content_id": "number or null",
            "reply": "short natural-language reply for chat/admin_help/clarify/unknown; empty for content_request/weather/prayer",
        },
    }

    try:
        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "You are the intent router for a Telegram assistant. "
                "Be accurate, concise, and return valid JSON only."
            ),
            input=[{
                "role": "user",
                "content": __import__("json").dumps(prompt, ensure_ascii=False),
            }],
            max_output_tokens=350,
        )
        raw = (getattr(response, "output_text", "") or "").strip()
        if not raw:
            raise ValueError("Empty intent response")

        # Be tolerant if the model accidentally wraps JSON in ```json ... ```.
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
        data = __import__("json").loads(raw)

        if not isinstance(data, dict):
            raise ValueError("Intent response is not an object")

        intent = str(data.get("intent") or "unknown").strip().lower()
        allowed = {
            "chat", "content_request", "weather", "prayer",
            "admin_help", "clarify", "unknown",
        }
        if intent not in allowed:
            intent = "unknown"

        category = data.get("category")
        if category is not None:
            category = str(category).strip().lower()

        content_id = data.get("content_id")
        try:
            content_id = int(content_id) if content_id is not None else None
        except Exception:
            content_id = None

        return {
            "intent": intent,
            "category": category,
            "query": str(data.get("query") or "").strip(),
            "content_id": content_id,
            "reply": str(data.get("reply") or "").strip(),
        }

    except Exception:
        logger.exception("AI INTENT ROUTER ERROR")
        raise


async def ai_reply(chat_id: int, user_text: str) -> str:
    if not client:
        return (
            "দুঃখিত, AI service এখন সেটআপ করা নেই। "
            "আপনি চাইলে Admin-এর সাথে যোগাযোগ করতে পারেন।"
        )

    history = get_history(chat_id, MAX_HISTORY)

    messages = []

    for item in history:
        messages.append({
            "role": item["role"],
            "content": item["content"],
        })

    if not messages or not (
        messages[-1]["role"] == "user"
        and messages[-1]["content"] == user_text
    ):
        messages.append({
            "role": "user",
            "content": user_text,
        })

    try:
        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_PROMPT,
            input=messages,
            max_output_tokens=500,
        )

        answer = getattr(response, "output_text", "") or ""

        if not answer.strip():
            return "দুঃখিত, এখন উত্তর তৈরি করতে পারছি না।"

        return answer.strip()

    except Exception as e:
        logger.exception("OPENAI ERROR")
        raise e


# =========================================================
# WEATHER
# =========================================================

async def get_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=24.1344"
        "&longitude=90.7860"
        "&current=temperature_2m,"
        "relative_humidity_2m,"
        "weather_code,"
        "wind_speed_10m"
    )

    try:
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()

        current = data.get("current", {})

        return (
            f"🌤️ {PRAYER_CITY} Weather\n\n"
            f"{weather_description(current.get('weather_code', 0))}\n"
            f"🌡️ তাপমাত্রা: {current.get('temperature_2m', '?')}°C\n"
            f"💧 আর্দ্রতা: {current.get('relative_humidity_2m', '?')}%\n"
            f"💨 বাতাস: {current.get('wind_speed_10m', '?')} km/h"
        )

    except Exception:
        logger.exception("WEATHER ERROR")
        return None


def weather_description(code):
    try:
        code = int(code or 0)
    except Exception:
        code = 0

    if code == 0:
        return "☀️ পরিষ্কার"
    if code in (1, 2, 3):
        return "⛅ আংশিক মেঘলা"
    if code in (45, 48):
        return "🌫️ কুয়াশা"
    if code in (51, 53, 55, 56, 57):
        return "🌦️ গুঁড়ি গুঁড়ি বৃষ্টি"
    if code in (61, 63, 65, 66, 67):
        return "🌧️ বৃষ্টি"
    if code in (80, 81, 82):
        return "🌧️ বৃষ্টির ঝাপটা"
    if code in (95, 96, 99):
        return "⛈️ বজ্রসহ বৃষ্টি"

    return "🌤️ আবহাওয়া পরিবর্তনশীল"


# =========================================================
# PRAYER
# =========================================================

async def get_prayer_times():
    url = (
        "https://api.aladhan.com/v1/timingsByCity"
        f"?city={PRAYER_CITY}"
        f"&country={PRAYER_COUNTRY}"
        "&method=1"
    )

    try:
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.json()

        timings = data["data"]["timings"]

        return (
            f"🕌 {PRAYER_CITY} নামাজের সময়\n\n"
            f"🌅 ফজর: {timings.get('Fajr', '-')}\n"
            f"☀️ সূর্যোদয়: {timings.get('Sunrise', '-')}\n"
            f"🕛 যোহর: {timings.get('Dhuhr', '-')}\n"
            f"🌇 আসর: {timings.get('Asr', '-')}\n"
            f"🌆 মাগরিব: {timings.get('Maghrib', '-')}\n"
            f"🌙 এশা: {timings.get('Isha', '-')}"
        )

    except Exception:
        logger.exception("PRAYER ERROR")
        return None


# =========================================================
# FIXED REPLIES
# =========================================================

def fixed_reply(text: str) -> Optional[str]:
    t = normalize_text(text)

    greetings = [
        "হাই", "হ্যালো", "hello", "hi", "hey",
        "সালাম", "আসসালামু আলাইকুম",
    ]

    if any(x in t for x in greetings):
        return (
            "👋 হ্যালো! আমি আছি।\n"
            "আপনি বাংলা, Banglish বা English-এ কথা বলতে পারেন।"
        )

    if t in ("ধন্যবাদ", "thanks", "thank you", "থ্যাংকস"):
        return "❤️ স্বাগতম! আরও কিছু লাগলে বলুন।"

    if t in ("কে তুমি", "তুমি কে", "who are you"):
        return (
            "🤖 আমি আপনার Telegram AI Assistant। "
            "প্রশ্নের উত্তর দিতে এবং saved content খুঁজে দিতে পারি।"
        )

    return None


# =========================================================
# ADMIN COMMANDS
# =========================================================

async def start_command(update, context):
    await update.effective_message.reply_text(
        "👋 Welcome!\n\n"
        "আমি আপনার Telegram AI Assistant।\n"
        "বাংলা, Banglish অথবা English-এ কথা বলতে পারেন।\n\n"
        "🎬 গান/ভিডিও/নাটক চাইলে নামসহ বলুন।"
    )


async def admin_command(update, context):
    if not await admin_only(update):
        return

    await update.effective_message.reply_text(
        "👑 Admin Panel\n\n"
        "/addsong - Content যোগ করুন\n"
        "/list - Saved content\n"
        "/stats - Statistics\n"
        "/delete ID - Content delete\n"
        "/broadcast TEXT - Broadcast\n"
        "/admintest - Admin test"
    )


async def admintest_command(update, context):
    if not await admin_only(update):
        return

    await update.effective_message.reply_text(
        "✅ Admin verification successful."
    )


async def addsong_command(update, context):
    if not await admin_only(update):
        return

    context.user_data["waiting_media"] = True
    context.user_data.pop("pending_media", None)
    context.user_data["waiting_title"] = False

    await update.effective_message.reply_text(
        "📥 এখন Video / Audio / Photo / Document / Animation পাঠান।\n\n"
        "Media পাওয়ার পর আমি Title চাইব।"
    )


async def list_command(update, context):
    if not await admin_only(update):
        return

    rows = db_execute("""
        SELECT id, title, media_type, category, view_count
        FROM contents
        ORDER BY id DESC
        LIMIT 50
    """, fetch=True)

    if not rows:
        await update.effective_message.reply_text(
            "📭 এখনো কোনো saved content নেই।"
        )
        return

    lines = ["📚 Saved Content", ""]

    for row in rows:
        lines.append(
            f"ID: {row['id']}\n"
            f"🎬 {row['title']}\n"
            f"📁 {row['media_type']}\n"
            f"🏷️ {row['category']}\n"
            f"👁️ Views: {row['view_count'] or 0}\n"
        )

    await update.effective_message.reply_text(
        "\n".join(lines)[:4000]
    )


async def stats_command(update, context):
    if not await admin_only(update):
        return

    users = db_execute(
        "SELECT COUNT(*) c FROM users",
        fetchone=True,
    )["c"]

    chats = db_execute(
        "SELECT COUNT(*) c FROM chats",
        fetchone=True,
    )["c"]

    contents = db_execute(
        "SELECT COUNT(*) c FROM contents",
        fetchone=True,
    )["c"]

    messages = db_execute(
        "SELECT COUNT(*) c FROM messages",
        fetchone=True,
    )["c"]

    await update.effective_message.reply_text(
        "📊 Bot Statistics\n\n"
        f"👤 Users: {users}\n"
        f"💬 Chats: {chats}\n"
        f"🎬 Contents: {contents}\n"
        f"💭 Messages: {messages}"
    )


async def delete_command(update, context):
    if not await admin_only(update):
        return

    if not context.args:
        await update.effective_message.reply_text(
            "ব্যবহার করুন:\n/delete ID"
        )
        return

    try:
        content_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(
            "❌ ID number হতে হবে।"
        )
        return

    row = db_execute(
        "SELECT title FROM contents WHERE id=?",
        (content_id,),
        fetchone=True,
    )

    if not row:
        await update.effective_message.reply_text(
            "❌ এই ID পাওয়া যায়নি।"
        )
        return

    db_execute(
        "DELETE FROM contents WHERE id=?",
        (content_id,),
    )

    await update.effective_message.reply_text(
        f"✅ Deleted:\n{row['title']}"
    )


async def broadcast_command(update, context):
    if not await admin_only(update):
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.effective_message.reply_text(
            "ব্যবহার করুন:\n/broadcast আপনার message"
        )
        return

    rows = db_execute(
        "SELECT chat_id FROM chats",
        fetch=True,
    )

    success = 0
    failed = 0

    for row in rows:
        try:
            await context.bot.send_message(
                chat_id=row["chat_id"],
                text=text,
            )
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.warning("BROADCAST ERROR: %r", e)
            failed += 1

    await update.effective_message.reply_text(
        "📢 Broadcast শেষ।\n\n"
        f"✅ Sent: {success}\n"
        f"❌ Failed: {failed}"
    )


async def weather_command(update, context):
    result = await get_weather()

    await update.effective_message.reply_text(
        result or "❌ Weather data পাওয়া যাচ্ছে না।"
    )


async def prayer_command(update, context):
    result = await get_prayer_times()

    await update.effective_message.reply_text(
        result or "❌ নামাজের সময় পাওয়া যাচ্ছে না।"
    )


# =========================================================
# ADMIN MEDIA / TITLE
# =========================================================

async def handle_admin_media(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return False

    if not context.user_data.get("waiting_media"):
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

    context.user_data["waiting_media"] = False
    context.user_data["waiting_title"] = True

    await message.reply_text(
        "✅ Media পেয়েছি।\n\n"
        "এখন Content-এর Title লিখুন।"
    )

    return True


async def handle_admin_title(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not is_admin(user.id):
        return False

    if not context.user_data.get("waiting_title"):
        return False

    title = (message.text or "").strip()

    if not title:
        await message.reply_text(
            "❌ Title খালি রাখা যাবে না।"
        )
        return True

    pending = context.user_data.get("pending_media")

    if not pending:
        context.user_data["waiting_title"] = False
        return False

    category = detect_category(title)

    content_id = db_execute("""
        INSERT INTO contents (
            title,
            media_type,
            file_id,
            category,
            added_by,
            view_count,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 0, ?)
    """, (
        title,
        pending["media_type"],
        pending["file_id"],
        category,
        user.id,
        now_str(),
    ))

    context.user_data.pop("pending_media", None)
    context.user_data["waiting_title"] = False

    await message.reply_text(
        "✅ Content সফলভাবে Saved হয়েছে!\n\n"
        f"🆔 ID: {content_id}\n"
        f"🎬 Title: {title}\n"
        f"📁 Type: {pending['media_type']}\n"
        f"🏷️ Category: {category}\n\n"
        "⚡ এখন User নাম লিখে চাইলে Bot সরাসরি পাঠাবে।"
    )

    return True


# =========================================================
# CALLBACK / FAST REPLY
# =========================================================

async def callback_handler(update: Update, context):
    query = update.callback_query

    try:
        await query.answer()
    except Exception:
        pass

    data = query.data or ""

    if ":" not in data:
        return

    action, category = data.split(":", 1)

    if category == "all":
        category = None

    if action in ("popular", "trending"):
        rows = (
            get_popular(category, 5)
            if action == "popular"
            else get_trending(category, 5)
        )

        if not rows:
            await query.message.reply_text(
                f"📭 এখনো কোনো {content_label(category)} saved নেই।"
            )
            return

        heading = (
            f"🔥 জনপ্রিয় {content_label(category)}:"
            if action == "popular"
            else f"📈 ট্রেন্ডিং {content_label(category)}:"
        )

        buttons = []
        for row in rows:
            buttons.append([
                InlineKeyboardButton(
                    f"▶️ {row['title']}",
                    callback_data=f"send:{row['id']}",
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🔄 আবার দেখুন",
                callback_data=f"{action}:{category or 'all'}",
            )
        ])

        await query.message.reply_text(
            heading,
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if action == "send":
        try:
            content_id = int(category)
        except ValueError:
            return

        row = db_execute(
            "SELECT * FROM contents WHERE id=?",
            (content_id,),
            fetchone=True,
        )
        if not row:
            await query.message.reply_text("❌ এই content আর পাওয়া যাচ্ছে না।")
            return

        # callback updates need a lightweight Update-compatible path; the
        # original message belongs to the same chat, so reply methods work.
        try:
            media_type = row["media_type"]
            file_id = row["file_id"]
            if media_type == "video":
                await query.message.reply_video(video=file_id, supports_streaming=True)
            elif media_type == "audio":
                await query.message.reply_audio(audio=file_id)
            elif media_type == "photo":
                await query.message.reply_photo(photo=file_id)
            elif media_type == "animation":
                await query.message.reply_animation(animation=file_id)
            else:
                await query.message.reply_document(document=file_id)
            increment_view(row["id"])
        except Exception as e:
            await query.message.reply_text("❌ Content পাঠাতে সমস্যা হয়েছে।")
            await notify_admin(context, "Fast-reply content send failed", update, e)
        return


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

async def handle_message(update, context):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    save_user(user)
    save_chat(chat)

    # Admin media upload/title flow always has priority.
    if await handle_admin_media(update, context):
        return

    if message.text and await handle_admin_title(update, context):
        return

    if not message.text:
        return

    text = message.text.strip()
    if not text:
        return

    if not check_rate_limit(user.id):
        await message.reply_text("⏳ একটু ধীরে বলুন 🙂")
        return

    normalized = normalize_text(text)

    # Fast deterministic commands/replies stay fast and do not waste an AI call.
    fixed = fixed_reply(text)
    if fixed:
        save_message(chat.id, user.id, "user", text)
        save_message(chat.id, 0, "assistant", fixed)
        await message.reply_text(fixed)
        return

    # Pending content selection: user can simply type another title/name.
    if pending_exists(chat.id, user.id):
        pending = pending_content.get(chat.id, {})
        category = pending.get("category")
        row = search_content(text, category=category)
        if row:
            clear_pending(chat.id)
            await send_saved_content(update, row, context)
            return

    # Save the user message before AI so the router sees conversation context.
    save_message(chat.id, user.id, "user", text)

    # -----------------------------------------------------
    # AI-FIRST NATURAL LANGUAGE ROUTER
    # -----------------------------------------------------
    try:
        intent = await ai_understand_message(chat.id, text)
        action = intent.get("intent", "unknown")
        category = intent.get("category")
        query_text = intent.get("query", "").strip()
        selected_id = intent.get("content_id")

        # Weather/prayer can be expressed naturally; no keyword requirement.
        if action == "weather":
            result = await get_weather()
            reply = result or "❌ Weather data পাওয়া যাচ্ছে না।"
            save_message(chat.id, 0, "assistant", reply)
            await message.reply_text(reply)
            return

        if action == "prayer":
            result = await get_prayer_times()
            reply = result or "❌ নামাজের সময় পাওয়া যাচ্ছে না।"
            save_message(chat.id, 0, "assistant", reply)
            await message.reply_text(reply)
            return

        # Content requests are routed to the saved-media database.
        if action == "content_request":
            row = None

            if selected_id:
                row = db_execute(
                    "SELECT * FROM contents WHERE id=?",
                    (selected_id,),
                    fetchone=True,
                )
                # Never send a model-selected item if its category conflicts
                # strongly with the request.
                if row and category and row["category"] != category:
                    row = None

            if not row:
                row = search_content(query_text, category=category)

            # If AI extracted no useful query, fall back to the original text.
            if not row and text:
                row = search_content(
                    extract_content_query(text),
                    category=category or detect_requested_category(text),
                )

            if row:
                clear_pending(chat.id)
                await send_saved_content(update, row, context)
                return

            set_pending(
                chat.id,
                user.id,
                category=category,
                original_query=query_text or extract_content_query(text),
            )

            await send_suggestions(
                update,
                category,
                query_text or extract_content_query(text),
            )

            # Admin learns what users are asking for but the bot cannot find.
            await notify_admin(
                context,
                "AI understood a content request, but saved content was not found",
                update,
            )
            return

        # Admin/human support gets a direct clickable Admin button.
        if action == "admin_help":
            reply = intent.get("reply") or (
                "অবশ্যই। আপনার সমস্যাটা লিখে দিন, আর দরকার হলে সরাসরি Admin-এর সাথে যোগাযোগ করতে পারেন।"
            )
            save_message(chat.id, 0, "assistant", reply)
            await message.reply_text(
                reply,
                reply_markup=admin_keyboard(),
            )
            return

        # AI clarification question.
        if action == "clarify":
            reply = intent.get("reply") or "আপনি ঠিক কোনটা চান—একটু পরিষ্কার করে বলবেন? 🙂"
            save_message(chat.id, 0, "assistant", reply)
            await message.reply_text(reply)
            return

        # Normal ChatGPT-like conversation.
        reply = intent.get("reply", "").strip()
        if not reply:
            reply = await ai_reply(chat.id, text)

        save_message(chat.id, 0, "assistant", reply)
        await message.reply_text(reply)
        return

    except Exception as e:
        logger.exception("AI-FIRST HANDLER ERROR")

        # If AI routing fails, preserve the old deterministic content/weather
        # behavior instead of leaving the user without an answer.
        try:
            if is_content_request(text):
                category = detect_requested_category(text)
                query_text = infer_query_without_request_words(text)
                row = search_content(query_text, category=category)
                if row:
                    await send_saved_content(update, row, context)
                    return
                await send_suggestions(update, category, query_text)
                await notify_admin(context, "AI router failed during content request", update, e)
                return

            if any(x in normalized for x in ["আবহাওয়া", "weather", "বৃষ্টি", "তাপমাত্রা", "temperature"]):
                result = await get_weather()
                await message.reply_text(result or "❌ Weather data পাওয়া যাচ্ছে না।")
                await notify_admin(context, "AI router failed; weather fallback used", update, e)
                return

            if any(x in normalized for x in ["নামাজ", "ওয়াক্ত", "prayer time"]):
                result = await get_prayer_times()
                await message.reply_text(result or "❌ নামাজের সময় পাওয়া যাচ্ছে না।")
                await notify_admin(context, "AI router failed; prayer fallback used", update, e)
                return

            answer = await ai_reply(chat.id, text)
            save_message(chat.id, 0, "assistant", answer)
            await message.reply_text(answer)
            await notify_admin(context, "AI intent router failed; chat fallback used", update, e)

        except Exception as fallback_error:
            logger.exception("AI FALLBACK ERROR")
            await message.reply_text(
                "😔 দুঃখিত, এখন উত্তর দিতে সমস্যা হচ্ছে।\n"
                "চাইলে Admin-এর সাথে সরাসরি যোগাযোগ করতে পারেন।",
                reply_markup=admin_keyboard(),
            )
            await notify_admin(context, "AI and fallback response both failed", update, fallback_error)


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    logger.error(
        "TELEGRAM ERROR: %r",
        context.error,
    )

    try:
        await notify_admin(
            context,
            "Unhandled Telegram bot error",
            update,
            context.error,
        )
    except Exception:
        logger.exception("Could not send error alert to admin")


# =========================================================
# HOURLY MESSAGES
# =========================================================

SPECIAL_MESSAGES = {
    0: (
        "🌙 শুভ রাত্রি সবাইকে! 😴\n"
        "দিনের কাজ শেষ করে এখন একটু বিশ্রাম নিন।"
    ),
    7: (
        "🌅 শুভ সকাল সবাইকে! ☀️\n"
        "নতুন দিনের শুরু হোক সুন্দরভাবে। ❤️"
    ),
    8: (
        "☀️ সকাল ৮টা!\n"
        "আজকের দিনটা ভালো কিছু দিয়ে শুরু হোক। 😊"
    ),
    9: (
        "🌞 সকাল ৯টা!\n"
        "নিজের কাজগুলো সুন্দরভাবে এগিয়ে নিন। 💪"
    ),
    10: (
        "☀️ সকাল ১০টা!\n"
        "ব্যস্ত দিনের মাঝেও একটু পানি পান করতে ভুলবেন না। 💧"
    ),
    12: (
        "🌤️ শুভ দুপুর!\n"
        "দুপুরের খাবার খেয়ে একটু বিশ্রাম নিন। 😊"
    ),
    16: (
        "🌇 বিকেল ৪টা!\n"
        "দিনের কাজ কেমন চলছে সবাই? 🙂"
    ),
    18: (
        "🌆 শুভ সন্ধ্যা সবাইকে! ❤️\n"
        "দিনটা সুন্দরভাবে শেষ হোক।"
    ),
    19: (
        "📚 Study Time!\n"
        "যারা পড়াশোনা করছেন, মনোযোগ দিয়ে পড়ুন। 💪📖"
    ),
    22: (
        "🌙 রাত ১০টা!\n"
        "অনেক রাত হয়েছে—সময়মতো ঘুমানোর চেষ্টা করুন। 😴"
    ),
}

GENERIC_HOURS = {
    11: "🕐 এখন সময় ১১:০০ বাজে",
    13: "🕐 এখন সময় ১:০০ বাজে",
    14: "🕐 এখন সময় ২:০০ বাজে",
    15: "🕐 এখন সময় ৩:০০ বাজে",
    17: "🕐 এখন সময় ৫:০০ বাজে",
    20: "🕐 এখন সময় ৮:০০ বাজে",
    21: "🕐 এখন সময় ৯:০০ বাজে",
    23: "🕐 এখন সময় ১১:০০ বাজে",
}


async def hourly_loop(application):
    while True:
        try:
            now = datetime.now(TZ)
            hour = now.hour
            minute = now.minute

            if minute <= 1:
                key = now.strftime("%Y-%m-%d-%H")
                last = get_state("last_auto_hour")

                if last != key:
                    text = (
                        SPECIAL_MESSAGES.get(hour)
                        or GENERIC_HOURS.get(hour)
                    )

                    if text:
                        rows = db_execute(
                            "SELECT chat_id FROM chats",
                            fetch=True,
                        )

                        for row in rows:
                            try:
                                await application.bot.send_message(
                                    chat_id=row["chat_id"],
                                    text=text,
                                )
                                await asyncio.sleep(0.05)
                            except Exception as e:
                                logger.warning(
                                    "AUTO ERROR: %r",
                                    e,
                                )

                        set_state(
                            "last_auto_hour",
                            key,
                        )

        except Exception:
            logger.exception("HOURLY ERROR")

        await asyncio.sleep(20)


# =========================================================
# STARTUP
# =========================================================

async def post_init(application):
    init_db()

    application.create_task(
        hourly_loop(application)
    )

    logger.info("================================")
    logger.info("BOT STARTED SUCCESSFULLY")
    logger.info("TIMEZONE: %s", TZ)
    logger.info("MODEL: %s", OPENAI_MODEL)
    logger.info("ADMIN_ID: %s", ADMIN_ID)
    logger.info("ADMIN_USERNAME: @%s", ADMIN_USERNAME)
    logger.info("================================")


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN সেট করা হয়নি। Environment variable-এ BOT_TOKEN দিন।"
        )

    if not ADMIN_ID:
        raise RuntimeError(
            "ADMIN_ID সেট করা হয়নি। আপনার Telegram numeric user ID দিন।"
        )

    if not OPENAI_API_KEY:
        logger.warning(
            "OPENAI_API_KEY নেই। AI chat fallback mode-এ চলবে।"
        )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler("start", start_command)
    )
    app.add_handler(
        CommandHandler("admin", admin_command)
    )
    app.add_handler(
        CommandHandler("admintest", admintest_command)
    )
    app.add_handler(
        CommandHandler("addsong", addsong_command)
    )
    app.add_handler(
        CommandHandler("addcontent", addsong_command)
    )
    app.add_handler(
        CommandHandler("list", list_command)
    )
    app.add_handler(
        CommandHandler("stats", stats_command)
    )
    app.add_handler(
        CommandHandler("delete", delete_command)
    )
    app.add_handler(
        CommandHandler("broadcast", broadcast_command)
    )
    app.add_handler(
        CommandHandler("weather", weather_command)
    )
    app.add_handler(
        CommandHandler("prayer", prayer_command)
    )

    # Fast Reply buttons
    app.add_handler(
        CallbackQueryHandler(callback_handler)
    )

    # Text
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    # Media
    app.add_handler(
        MessageHandler(
            (
                filters.VIDEO
                | filters.AUDIO
                | filters.PHOTO
                | filters.Document.ALL
                | filters.ANIMATION
            ),
            handle_message,
        )
    )

    app.add_error_handler(error_handler)

    logger.info("Starting Telegram bot...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
