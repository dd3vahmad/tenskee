import json
import logging
import os
import sqlite3
from datetime import datetime
from datetime import time as dt_time
from datetime import timedelta

from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackContext,
    CommandHandler,
    MessageHandler,
    filters,
)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
if TOKEN is None:
    raise ValueError("TELEGRAM_TOKEN is not set")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY is None:
    raise ValueError("GEMINI_API_KEY is not set")

GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
if GROUP_CHAT_ID is None:
    raise ValueError("GROUP_CHAT_ID is not set")

BOT_USERNAME = os.getenv("BOT_USERNAME", "tenskee_bot")

client = genai.Client(api_key=GEMINI_API_KEY)

if os.getenv("RENDER"):
    DB_FILE = "/app/data/class_data.db"
    print(f"[DB] Using Render persistent path: {DB_FILE}")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)
    DB_FILE = os.path.join(DATA_DIR, "class_data.db")
    print(f"[DB] Using local path: {DB_FILE}")

conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT NOT NULL,
    due DATE NOT NULL
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS timetable (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL UNIQUE,
    schedule TEXT NOT NULL
)
"""
)

cursor.execute(
    """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT,                    -- exam, test, quiz, presentation, meeting, etc.
    title TEXT NOT NULL,
    date DATE NOT NULL,
    notes TEXT
)
"""
)
conn.commit()


async def parse_message(text: str) -> dict:
    today_str = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""
You are Tenskee, a magical class group assistant for students.
Output ONLY valid JSON. No explanation. No markdown.
Allowed formats:
{{"action": "add_assignment", "task": "string", "due": "YYYY-MM-DD"}}
{{"action": "add_timetable", "day": "Monday", "schedule": "string"}}
{{"action": "list_assignments"}}
{{"action": "add_event", "type": "exam/test/quiz/presentation/etc or empty", "title": "string", "date": "YYYY-MM-DD", "notes": "string or empty"}}
{{"action": "list_events"}}
{{"action": "unknown"}}
Convert relative dates properly (tomorrow, next Friday, in 2 weeks → absolute YYYY-MM-DD).
Today is {today_str}
Message:
{text}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=300,
            ),
        )
        if not response or not response.text:
            raise ValueError("Empty response from Gemini")
        raw = response.text.strip()
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        return parsed
    except Exception as e:
        logging.error(f"Gemini failed: {str(e)}")
        return {"action": "llm_down", "error": str(e)}


async def start(update: Update, _: CallbackContext):
    user = update.effective_user
    is_group = update.effective_chat.type in ["group", "supergroup"]

    welcome = f"Hello {user.first_name}! ✨ I'm **Tenskee**, your magical class group assistant.\n\n"

    if is_group:
        welcome += (
            "I'm already here — perfect!\n\n"
            "Summon me with: **@tenskee_bot save us**\n\n"
            "Examples:\n"
            "• @tenskee_bot upcoming assignments + events + tomorrow timetable\n"
            "• @tenskee_bot add math quiz due next Friday\n"
            "• @tenskee_bot add exam Data Structures March 10\n"
            "• @tenskee_bot add timetable Monday OOP 9AM, Stats 11AM\n"
            "• @tenskee_bot list assignments\n"
            "• @tenskee_bot list events\n\n"
            "Daily reminders at 6:00 AM with today's due items, events, and timetable.\n\n"
            "Let the magic begin! 🪄"
        )
    else:
        welcome += (
            "I'm built for **Telegram group chats** (class/department groups).\n\n"
            "1. Add me to your group:\n"
            "   Open group → tap name → Add Members → search @tenskee_bot → Add\n\n"
            "2. Summon with:\n"
            "   **@tenskee_bot save us**\n\n"
            "Examples:\n"
            "   • @tenskee_bot add physics midterm due 2026-03-15\n"
            "   • @tenskee_bot add event Group meeting next Tuesday 4PM notes Bring laptop\n"
            "   • @tenskee_bot list events\n\n"
            "I send automatic daily reminders at 6:00 AM.\n\n"
            "Go add me to your group — I'll save your semester! ✨"
        )

    await update.message.reply_text(welcome, parse_mode="Markdown")


async def handle_message(update: Update, _: CallbackContext):
    message_text = update.message.text or ""
    lower_text = message_text.lower()

    mentioned = (
        f"@{BOT_USERNAME.lower()}" in lower_text
        or f"@{BOT_USERNAME.lower().replace('_bot','')}" in lower_text
    )

    if not mentioned:
        return

    cleaned_text = message_text
    for phrase in [
        "Tenskee save us",
        "tenskee save us",
        f"@{BOT_USERNAME} save us",
        f"@{BOT_USERNAME.replace('_bot','')} save us",
        f"@{BOT_USERNAME} Tenskee save us",
        f"@{BOT_USERNAME.replace('_bot','')} Tenskee save us",
    ]:
        cleaned_text = cleaned_text.replace(phrase, "", 1).strip()
        cleaned_text = cleaned_text.replace(phrase.lower(), "", 1).strip()

    cleaned_text = cleaned_text.strip()

    reply_prefix = "Tenskee hears your desperate call… ✨ I bring salvation!\n\n"

    parsed = {"action": "unknown"}
    llm_failed = False

    if cleaned_text:
        parsed = await parse_message(cleaned_text)
        if parsed.get("action") == "llm_down":
            llm_failed = True
            await update.message.reply_text(
                reply_prefix
                + "My mystical mind is currently unreachable (quota exhausted or API issue).\n"
                "But fear not — I can still show you upcoming trials!\n\n"
            )

    if not llm_failed and cleaned_text:
        if parsed["action"] == "add_assignment":
            cursor.execute(
                "INSERT INTO assignments (task, due) VALUES (?, ?)",
                (parsed["task"], parsed["due"]),
            )
            conn.commit()
            await update.message.reply_text(
                reply_prefix
                + f"Assignment sealed: {parsed['task']} due {parsed['due']}"
            )
            return

        elif parsed["action"] == "add_timetable":
            cursor.execute(
                "INSERT OR REPLACE INTO timetable (day, schedule) VALUES (?, ?)",
                (parsed["day"], parsed["schedule"]),
            )
            conn.commit()
            await update.message.reply_text(
                reply_prefix + f"Timetable inscribed for {parsed['day']}"
            )
            return

        elif parsed["action"] == "list_assignments":
            cursor.execute("SELECT task, due FROM assignments ORDER BY due")
            assignments = cursor.fetchall()
            if not assignments:
                await update.message.reply_text(
                    reply_prefix + "No assignments recorded yet."
                )
            else:
                msg = "Assignments:\n" + "\n".join(
                    f"- {task} (due {due})" for task, due in assignments
                )
                await update.message.reply_text(reply_prefix + msg)
            return

        elif parsed["action"] == "add_event":
            cursor.execute(
                "INSERT INTO events (type, title, date, notes) VALUES (?, ?, ?, ?)",
                (
                    parsed.get("type") or None,
                    parsed["title"],
                    parsed["date"],
                    parsed.get("notes") or None,
                ),
            )
            conn.commit()
            type_str = f" ({parsed['type']})" if parsed.get("type") else ""
            notes_str = f" – {parsed['notes']}" if parsed.get("notes") else ""
            await update.message.reply_text(
                reply_prefix
                + f"Event{type_str} added: {parsed['title']} on {parsed['date']}{notes_str}"
            )
            return

        elif parsed["action"] == "list_events":
            today = datetime.now().date()
            cursor.execute(
                """
                SELECT type, title, date, notes FROM events
                WHERE date >= ?
                ORDER BY date
                LIMIT 10
                """,
                (today.strftime("%Y-%m-%d"),),
            )
            events = cursor.fetchall()
            if not events:
                await update.message.reply_text(
                    reply_prefix + "No upcoming events recorded."
                )
            else:
                msg = "Upcoming events:\n"
                for typ, title, date, notes in events:
                    type_str = f"[{typ}] " if typ else ""
                    notes_str = f" – {notes}" if notes else ""
                    msg += f"- {type_str}{title} ({date}){notes_str}\n"
                await update.message.reply_text(reply_prefix + msg)
            return

    today = datetime.now().date()
    upcoming = []

    cursor.execute(
        "SELECT task, due FROM assignments WHERE due >= ? AND due <= date(?, '+7 days') ORDER BY due",
        (today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")),
    )
    for task, due in cursor.fetchall():
        days_left = (datetime.strptime(due, "%Y-%m-%d").date() - today).days
        tag = (
            "TODAY"
            if days_left == 0
            else "Tomorrow" if days_left == 1 else f"In {days_left} days"
        )
        upcoming.append(f"Assignment {tag}: {task}")

    cursor.execute(
        "SELECT type, title, date, notes FROM events WHERE date >= ? AND date <= date(?, '+14 days') ORDER BY date",
        (today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")),
    )
    for typ, title, date, notes in cursor.fetchall():
        days_left = (datetime.strptime(date, "%Y-%m-%d").date() - today).days
        tag = (
            "TODAY"
            if days_left == 0
            else "Tomorrow" if days_left == 1 else f"In {days_left} days"
        )
        type_str = f"[{typ.upper()}] " if typ else ""
        notes_str = f" – {notes}" if notes else ""
        upcoming.append(f"Event {type_str}{tag}: {title}{notes_str}")

    tomorrow_str = (today + timedelta(days=1)).strftime("%A")
    cursor.execute("SELECT schedule FROM timetable WHERE day = ?", (tomorrow_str,))
    sched = cursor.fetchone()
    if sched:
        upcoming.append(f"Tomorrow's classes: {sched[0]}")

    if upcoming:
        response = reply_prefix + "These trials approach:\n" + "\n".join(upcoming)
    else:
        response = reply_prefix + "All is calm… for now. No immediate doom detected."

    await update.message.reply_text(response)


async def send_reminders_job(context: CallbackContext):
    today = datetime.now().date()
    reminders = []

    cursor.execute(
        "SELECT task FROM assignments WHERE due = ?",
        (today.strftime("%Y-%m-%d"),),
    )
    for (task,) in cursor.fetchall():
        reminders.append(f"Due today — brace yourselves: {task}")

    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    cursor.execute("SELECT task FROM assignments WHERE due = ?", (tomorrow_str,))
    for (task,) in cursor.fetchall():
        reminders.append(f"Due tomorrow: {task}")

    cursor.execute(
        "SELECT type, title, notes FROM events WHERE date = ?",
        (today.strftime("%Y-%m-%d"),),
    )
    for typ, title, notes in cursor.fetchall():
        type_str = f"[{typ.upper()}] " if typ else ""
        notes_str = f" – {notes}" if notes else ""
        reminders.append(f"Today: {type_str}{title}{notes_str}")

    cursor.execute(
        "SELECT schedule FROM timetable WHERE day = ?", (today.strftime("%A"),)
    )
    schedule = cursor.fetchone()
    if schedule:
        reminders.append(f"Today's path: {schedule[0]}")

    if reminders:
        try:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text="Tenskee awakens with tidings of fate! ✨\n"
                + "\n".join(reminders),
            )
        except Exception as e:
            logging.error(f"Failed to send daily reminder: {e}")


# Main
logging.basicConfig(level=logging.INFO)

app = ApplicationBuilder().token(TOKEN).build()

# /start command
app.add_handler(CommandHandler("start", start))

# Main message handler
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Daily at 6:00 AM
app.job_queue.run_daily(
    send_reminders_job,
    time=dt_time(6, 0),
)

print("Tenskee is listening...")
app.run_polling()
