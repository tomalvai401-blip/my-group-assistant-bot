import os
import sqlite3
import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from openai import AsyncOpenAI


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()

ADMIN_ID_RAW = os.getenv("ADMIN_ID", "").strip()
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").strip().lstrip("@")

PRAYER_COUNTRY = os.getenv("PRAYER_COUNTRY", "Bangladesh").strip()
PRAYER_CITY = os.getenv("PRAYER_CITY", "Narsingdi").strip()

TZ = ZoneInfo("Asia/Dhaka")

# OpenAI model
OPENAI_MODEL = "gpt-5.5"

DB_FILE = "bot.db"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN পাওয়া যায়নি।")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY পাওয়া যায়নি।")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except Exception:
    ADMIN_ID = 0


# =========================================================
# OPENAI
# =========================================================

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY
)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_seen INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    chat_type TEXT,
    title TEXT,
    last_seen INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    role TEXT,
    content TEXT,
    created_at INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS contents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT,
    file_id TEXT,
    file_type TEXT,
    created_at INTEGER
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")

db.commit()


# =========================================================
# DATABASE HELPERS
# =========================================================

def db_execute(query, params=()):
    cur = db.cursor()
    cur.execute(query, params)
    db.commit()
    return cur


def save_user(user):
    if not user:
        return

    db_execute(
        """
        INSERT INTO users
        (user_id, username, first_name, last_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name,
            last_seen=excluded.last_seen
        """,
        (
            user.id,
            user.username or "",
            user.first_name or "",
            int(time.time()),
        ),
    )


def save_chat(chat):
    if not chat:
        return

    db_execute(
        """
        INSERT INTO chats
        (chat_id, chat_type, title, last_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET
            title=excluded.title,
            last_seen=excluded.last_seen
        """,
        (
            chat.id,
            chat.type,
            getattr(chat, "title", "") or "",
            int(time.time()),
        ),
    )


def save_message(chat_id, user_id, role, content):
    if not content:
        return

    db_execute(
        """
        INSERT INTO messages
        (chat_id, user_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            user_id,
            role,
            content[:4000],
            int(time.time()),
        ),
    )

    # Keep only recent messages per chat.
    db_execute(
        """
        DELETE FROM messages
        WHERE chat_id = ?
        AND id NOT IN (
            SELECT id
            FROM messages
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT 30
        )
        """,
        (chat_id, chat_id),
    )


def get_history(chat_id, limit=12):
    rows = db_execute(
        """
        SELECT role, content
        FROM messages
        WHERE chat_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (chat_id, limit),
    ).fetchall()

    rows.reverse()
    return rows


# =========================================================
# ADMIN
# =========================================================

def is_admin(update: Update):
    if not update.effective_user:
        return False

    return update.effective_user.id == ADMIN_ID


async def admin_only(update: Update):
    if not is_admin(update):
        if update.message:
            await update.message.reply_text(
                "❌ এই Command শুধুমাত্র Admin ব্যবহার করতে পারবেন।"
            )
        return False

    return True


# =========================================================
# RATE LIMIT
# =========================================================

rate_data = {}


def rate_limited(user_id):
    now = time.time()

    data = rate_data.get(
        user_id,
        []
    )

    data = [
        x for x in data
        if now - x < 5
    ]

    if len(data) >= 7:
        rate_data[user_id] = data
        return True

    data.append(now)
    rate_data[user_id] = data

    return False


# =========================================================
# CONTENT SEARCH
# =========================================================

CONTENT_WORDS = [
    "গান",
    "song",
    "নাটক",
    "drama",
    "মুভি",
    "movie",
    "সিনেমা",
    "ভিডিও",
    "video",
    "ডান্স",
    "dance",
    "ছবি",
    "photo",
]

REQUEST_WORDS = [
    "দাও",
    "দেন",
    "দিবে",
    "চাই",
    "লাগবে",
    "পাঠাও",
    "পাঠিয়ে",
    "send",
    "give",
    "want",
    "please",
]


def is_content_request(text):
    t = text.lower()

    has_content = any(
        word in t
        for word in CONTENT_WORDS
    )

    has_request = any(
        word in t
        for word in REQUEST_WORDS
    )

    return has_content and has_request


def detect_category(text):
    t = text.lower()

    if "গান" in t or "song" in t:
        return "song"

    if "নাটক" in t or "drama" in t:
        return "drama"

    if (
        "মুভি" in t
        or "movie" in t
        or "সিনেমা" in t
    ):
        return "movie"

    if "ভিডিও" in t or "video" in t:
        return "video"

    if "ডান্স" in t or "dance" in t:
        return "dance"

    if "ছবি" in t or "photo" in t:
        return "photo"

    return "other"


def search_content(query):
    query = query.strip()

    if not query:
        return None

    rows = db_execute(
        """
        SELECT id, title, category, file_id, file_type
        FROM contents
        WHERE title LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"%{query}%",),
    ).fetchall()

    if rows:
        return rows[0]

    # Word-by-word fallback
    words = query.split()

    for word in words:
        if len(word) < 2:
            continue

        rows = db_execute(
            """
            SELECT id, title, category, file_id, file_type
            FROM contents
            WHERE title LIKE ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (f"%{word}%",),
        ).fetchall()

        if rows:
            return rows[0]

    return None


async def send_saved_content(message, item):
    if not item:
        return False

    content_id, title, category, file_id, file_type = item

    try:
        caption = f"🎬 {title}"

        if file_type == "photo":
            await message.reply_photo(
                photo=file_id,
                caption=caption,
            )

        elif file_type == "video":
            await message.reply_video(
                video=file_id,
                caption=caption,
            )

        elif file_type == "audio":
            await message.reply_audio(
                audio=file_id,
                caption=caption,
            )

        elif file_type == "document":
            await message.reply_document(
                document=file_id,
                caption=caption,
            )

        else:
            await message.reply_text(
                f"🎬 {title}\n\n{file_id}"
            )

        await message.reply_text(
            "আর কিছু লাগলে জানাবেন, আমরা আছি আপনার সাথে! 🤝"
        )

        return True

    except Exception:
        return False


# =========================================================
# OPENAI AI
# =========================================================

SYSTEM_PROMPT = """
তুমি একটি Telegram group assistant bot।

তোমার প্রধান কাজ হলো স্বাভাবিক, সংক্ষিপ্ত এবং প্রাসঙ্গিকভাবে উত্তর দেওয়া।

নিয়ম:

1. ব্যবহারকারীর বর্তমান message এবং সাম্প্রতিক conversation context দেখে উত্তর দেবে।
2. বাংলা হলে বাংলায় উত্তর দেবে।
3. Banglish হলে Banglish/সহজ বাংলায় উত্তর দিতে পারো।
4. English হলে English-এ উত্তর দিতে পারো।
5. ব্যবহারকারী যা জিজ্ঞেস করেনি তা নিয়ে অযথা বড় উত্তর দেবে না।
6. কোনো তথ্য নিশ্চিত না হলে বানিয়ে তথ্য তৈরি করবে না।
7. নিজের থেকে fake link, fake download link, fake file বা fake source তৈরি করবে না।
8. গান/নাটক/মুভি/ভিডিও পাওয়ার দাবি করবে না যদি database থেকে content পাওয়া না যায়।
9. Content delivery সফল হলে program নিজে আলাদা closing message পাঠাবে; তুমি সেই closing message লিখবে না।
10. সাধারণ কথোপকথনে কোনো content-delivery closing message ব্যবহার করবে না।
11. ব্যবহারকারী শুধু "হ্যাঁ", "না", "ওটা", "আগেরটা", "দাও" বললে সাম্প্রতিক context দেখে অর্থ বোঝার চেষ্টা করবে।
12. উত্তর স্বাভাবিক ও বন্ধুত্বপূর্ণ হবে।
13. একই কথা বারবার বলবে না।
14. প্রয়োজন ছাড়া emoji ব্যবহার করবে না।
15. রাজনৈতিক বিষয় এলে নিরপেক্ষ ও তথ্যভিত্তিক থাকবে।
"""


async def ai_reply(chat_id, user_text):
    history = get_history(chat_id, 12)

    input_messages = []

    for role, content in history:
        if role == "assistant":
            input_messages.append(
                {
                    "role": "assistant",
                    "content": content,
                }
            )
        else:
            input_messages.append(
                {
                    "role": "user",
                    "content": content,
                }
            )

    input_messages.append(
        {
            "role": "user",
            "content": user_text,
        }
    )

    try:
        response = await client.responses.create(
            model=OPENAI_MODEL,
            instructions=SYSTEM_PROMPT,
            input=input_messages,
            max_output_tokens=500,
            temperature=0.2,
        )

        answer = (response.output_text or "").strip()

        if not answer:
            return (
                "দুঃখিত, এই মুহূর্তে ঠিকভাবে উত্তর দিতে পারছি না।"
            )

        return answer

    except Exception as e:
        print("OPENAI ERROR:", repr(e))

        return (
            "দুঃখিত, এই মুহূর্তে AI-এর সাথে সংযোগ করা যাচ্ছে না। "
            "একটু পরে আবার চেষ্টা করুন।"
        )


# =========================================================
# /START
# =========================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome!\n\n"
        "আমি আপনার Telegram assistant bot।\n"
        "যা জানতে চান বা বলতে চান, লিখুন।"
    )


# =========================================================
# /ADMIN
# =========================================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    await update.message.reply_text(
        "👑 Admin Panel\n\n"
        "/addsong — গান/ভিডিও/ফাইল save\n"
        "/list — saved content list\n"
        "/stats — bot statistics\n"
        "/delete ID — content delete\n"
        "/broadcast TEXT — broadcast\n"
        "/admintest — admin test"
    )


# =========================================================
# /ADMINTEST
# =========================================================

async def admin_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    await update.message.reply_text(
        "👑 Admin Test সফল হয়েছে।"
    )


# =========================================================
# /ADDDSONG
# =========================================================

async def add_song_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    context.user_data["waiting_media"] = True

    await update.message.reply_text(
        "📥 এখন গান/ভিডিও/অডিও/ছবি/ফাইল পাঠান।"
    )


# =========================================================
# MEDIA SAVE
# =========================================================

def get_media_info(message):
    if message.video:
        return (
            message.video.file_id,
            "video",
        )

    if message.audio:
        return (
            message.audio.file_id,
            "audio",
        )

    if message.photo:
        return (
            message.photo[-1].file_id,
            "photo",
        )

    if message.document:
        return (
            message.document.file_id,
            "document",
        )

    return None


async def handle_admin_media(update, context):
    if not is_admin(update):
        return False

    if not context.user_data.get("waiting_media"):
        return False

    info = get_media_info(update.message)

    if not info:
        return False

    file_id, file_type = info

    context.user_data["pending_file_id"] = file_id
    context.user_data["pending_file_type"] = file_type

    context.user_data["waiting_media"] = False
    context.user_data["waiting_title"] = True

    await update.message.reply_text(
        "✅ Media পেয়েছি।\n\n"
        "এখন content-এর নাম লিখুন।"
    )

    return True


async def handle_admin_title(update, context):
    if not is_admin(update):
        return False

    if not context.user_data.get("waiting_title"):
        return False

    title = update.message.text.strip()

    if not title:
        await update.message.reply_text(
            "❌ নাম খালি রাখা যাবে না।"
        )
        return True

    file_id = context.user_data.get("pending_file_id")
    file_type = context.user_data.get("pending_file_type")

    if not file_id:
        context.user_data.clear()

        await update.message.reply_text(
            "❌ Media data পাওয়া যায়নি। আবার /addsong দিন।"
        )

        return True

    category = detect_category(title)

    db_execute(
        """
        INSERT INTO contents
        (title, category, file_id, file_type, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            title,
            category,
            file_id,
            file_type,
            int(time.time()),
        ),
    )

    context.user_data.clear()

    await update.message.reply_text(
        f"✅ Content save হয়েছে!\n\n"
        f"📌 নাম: {title}\n"
        f"📂 category: {category}"
    )

    return True


# =========================================================
# /LIST
# =========================================================

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    rows = db_execute(
        """
        SELECT id, title, category
        FROM contents
        ORDER BY id DESC
        LIMIT 50
        """
    ).fetchall()

    if not rows:
        await update.message.reply_text(
            "📭 এখনো কোনো content save করা হয়নি।"
        )
        return

    lines = ["📚 Saved Content:\n"]

    for item_id, title, category in rows:
        lines.append(
            f"ID: {item_id} | {title} | {category}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# =========================================================
# /DELETE
# =========================================================

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    if not context.args:
        await update.message.reply_text(
            "ব্যবহার করুন:\n/delete ID"
        )
        return

    try:
        content_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ ID অবশ্যই সংখ্যা হতে হবে।"
        )
        return

    cur = db_execute(
        "DELETE FROM contents WHERE id = ?",
        (content_id,),
    )

    if cur.rowcount == 0:
        await update.message.reply_text(
            "❌ এই ID-এর কোনো content পাওয়া যায়নি।"
        )
        return

    await update.message.reply_text(
        "✅ Content delete হয়েছে।"
    )


# =========================================================
# /STATS
# =========================================================

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    users = db_execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    chats = db_execute(
        "SELECT COUNT(*) FROM chats"
    ).fetchone()[0]

    contents = db_execute(
        "SELECT COUNT(*) FROM contents"
    ).fetchone()[0]

    messages = db_execute(
        "SELECT COUNT(*) FROM messages"
    ).fetchone()[0]

    await update.message.reply_text(
        "📊 Bot Statistics\n\n"
        f"👤 Users: {users}\n"
        f"💬 Chats: {chats}\n"
        f"📦 Contents: {contents}\n"
        f"📝 Messages: {messages}"
    )


# =========================================================
# /BROADCAST
# =========================================================

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "ব্যবহার করুন:\n/broadcast আপনার message"
        )
        return

    rows = db_execute(
        "SELECT chat_id FROM chats"
    ).fetchall()

    sent = 0
    failed = 0

    for (chat_id,) in rows:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
            )
            sent += 1

            await asyncio.sleep(0.05)

        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 Broadcast শেষ।\n\n"
        f"✅ Sent: {sent}\n"
        f"❌ Failed: {failed}"
    )


# =========================================================
# WEATHER
# =========================================================

async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import aiohttp

    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=24.1344"
        "&longitude=90.7860"
        "&current=temperature_2m,weather_code"
        "&timezone=Asia%2FDhaka"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                data = await response.json()

        current = data.get("current", {})

        temperature = current.get(
            "temperature_2m",
            "?"
        )

        weather_code = current.get(
            "weather_code",
            "?"
        )

        await update.message.reply_text(
            f"🌤️ {PRAYER_CITY}\n\n"
            f"🌡️ Temperature: {temperature}°C\n"
            f"☁️ Weather code: {weather_code}"
        )

    except Exception:
        await update.message.reply_text(
            "❌ Weather information এখন পাওয়া যাচ্ছে না।"
        )


# =========================================================
# PRAYER
# =========================================================

async def prayer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import aiohttp

    url = (
        "https://api.aladhan.com/v1/timingsByCity"
        f"?city={PRAYER_CITY}"
        f"&country={PRAYER_COUNTRY}"
        "&method=1"
    )

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                data = await response.json()

        timings = data["data"]["timings"]

        await update.message.reply_text(
            "🕌 আজকের নামাজের সময়\n\n"
            f"ফজর: {timings.get('Fajr', '-')}\n"
            f"যোহর: {timings.get('Dhuhr', '-')}\n"
            f"আসর: {timings.get('Asr', '-')}\n"
            f"মাগরিব: {timings.get('Maghrib', '-')}\n"
            f"এশা: {timings.get('Isha', '-')}"
        )

    except Exception:
        await update.message.reply_text(
            "❌ নামাজের সময় এখন পাওয়া যাচ্ছে না।"
        )


# =========================================================
# HOURLY MESSAGES
# =========================================================

SPECIAL_MESSAGES = {
    0: "🌙 শুভ রাত্রি। ভালোভাবে ঘুমান।",
    7: "🌅 শুভ সকাল! নতুন দিনটি সুন্দর হোক।",
    8: "☀️ সকাল ভালো কাটুক। আজকের দিনটি সুন্দর হোক।",
    9: "🌞 সকালটা ভালোভাবে শুরু করুন।",
    10: "☀️ সকাল ১০টা। নিজের কাজগুলো সুন্দরভাবে এগিয়ে নিন।",
    12: "🌤️ শুভ দুপুর! দুপুরটা ভালো কাটুক।",
    16: "🌇 বিকেলটা সুন্দর কাটুক।",
    18: "🌆 শুভ সন্ধ্যা! সবাই ভালো থাকুন।",
    19: "📚 Study Time! একটু পড়াশোনার সময় দিন।",
    22: "🌙 রাত হয়েছে। সময়মতো বিশ্রাম নিন।",
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
    print("Hourly loop started.")

    while True:
        try:
            now = datetime.now(TZ)

            if now.minute <= 1:
                hour_key = now.strftime("%Y-%m-%d-%H")

                previous = db_execute(
                    "SELECT value FROM bot_state WHERE key = 'last_auto_hour'"
                ).fetchone()

                previous_value = previous[0] if previous else ""

                if previous_value != hour_key:

                    if now.hour in SPECIAL_MESSAGES:
                        message = SPECIAL_MESSAGES[now.hour]

                    elif now.hour in GENERIC_HOURS:
                        message = GENERIC_HOURS[now.hour]

                    else:
                        message = None

                    if message:
                        chats = db_execute(
                            "SELECT chat_id FROM chats"
                        ).fetchall()

                        for (chat_id,) in chats:
                            try:
                                await application.bot.send_message(
                                    chat_id=chat_id,
                                    text=message,
                                )
                                await asyncio.sleep(0.05)

                            except Exception as e:
                                print(
                                    "AUTO MESSAGE ERROR:",
                                    repr(e)
                                )

                        db_execute(
                            """
                            INSERT INTO bot_state
                            (key, value)
                            VALUES ('last_auto_hour', ?)
                            ON CONFLICT(key)
                            DO UPDATE SET value=excluded.value
                            """,
                            (hour_key,),
                        )

            await asyncio.sleep(20)

        except Exception as e:
            print(
                "HOURLY LOOP ERROR:",
                repr(e)
            )

            await asyncio.sleep(20)


# =========================================================
# MAIN MESSAGE HANDLER
# =========================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    chat = update.effective_chat

    save_user(user)
    save_chat(chat)

    # Admin media saving
    if await handle_admin_media(update, context):
        return

    # Admin title
    if update.message.text:
        if await handle_admin_title(update, context):
            return

    # Only text below
    text = update.message.text

    if not text:
        return

    text = text.strip()

    if not text:
        return

    # Rate limit
    if user and rate_limited(user.id):
        await update.message.reply_text(
            "⏳ একটু ধীরে বলুন, আমি শুনছি। 🙂"
        )
        return

    # Content request
    if is_content_request(text):

        await update.message.reply_text(
            "👋 Welcome!"
        )

        await update.message.reply_text(
            "⏳ একটু অপেক্ষা করুন, দিচ্ছি..."
        )

        # Try full text first
        item = search_content(text)

        # If not found, use words
        if not item:
            for word in text.split():
                if len(word) >= 2:
                    item = search_content(word)

                    if item:
                        break

        if item:
            await send_saved_content(
                update.message,
                item
            )
            return

        await update.message.reply_text(
            "❌ এই নামে কোনো saved content এখনো পাওয়া যায়নি।\n\n"
            "যেটা চান তার নাম লিখুন, আমি আবার খুঁজে দেখব।"
        )

        return

    # Save user message before AI
    save_message(
        chat.id,
        user.id,
        "user",
        text
    )

    answer = await ai_reply(
        chat.id,
        text
    )

    save_message(
        chat.id,
        0,
        "assistant",
        answer
    )

    await update.message.reply_text(
        answer
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    print(
        "BOT ERROR:",
        repr(context.error)
    )


# =========================================================
# POST INIT
# =========================================================

async def post_init(application):
    application.create_task(
        hourly_loop(application)
    )

    print("Bot started successfully.")


# =========================================================
# MAIN
# =========================================================

def main():

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler("start", start_command)
    )

    application.add_handler(
        CommandHandler("admin", admin_command)
    )

    application.add_handler(
        CommandHandler("admintest", admin_test)
    )

    application.add_handler(
        CommandHandler("addsong", add_song_command)
    )

    application.add_handler(
        CommandHandler("list", list_command)
    )

    application.add_handler(
        CommandHandler("stats", stats_command)
    )

    application.add_handler(
        CommandHandler("delete", delete_command)
    )

    application.add_handler(
        CommandHandler("broadcast", broadcast_command)
    )

    application.add_handler(
        CommandHandler("weather", weather_command)
    )

    application.add_handler(
        CommandHandler("prayer", prayer_command)
    )

    # Normal messages
    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_message
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("Starting Telegram bot...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
