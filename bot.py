import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackContext, MessageHandler, filters

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
    try:
        DATA_DIR = "/app/data"
        os.makedirs(DATA_DIR, exist_ok=True)
        DB_FILE = os.path.join(DATA_DIR, "class_data.db")

        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        print(f"Using persistent DB at {DB_FILE}")

    except Exception as e:
        print(f"Persistent disk unavailable ({e}), using in-memory DB")
        conn = sqlite3.connect(":memory:", check_same_thread=False)

else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    os.makedirs(DATA_DIR, exist_ok=True)

    DB_FILE = os.path.join(DATA_DIR, "class_data.db")
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    print(f"Using local DB at {DB_FILE}")

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

conn.commit()


async def parse_message(text: str) -> dict:
    today_str = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""
You are Tenskee, a magical class group assistant.
Output ONLY valid JSON. No explanation. No markdown.
Allowed formats:
{{"action": "add_assignment", "task": "string", "due": "YYYY-MM-DD"}}
{{"action": "add_timetable", "day": "Monday", "schedule": "string"}}
{{"action": "list_assignments"}}
{{"action": "unknown"}}
Convert relative dates properly.
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
                max_output_tokens=200,
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


async def handle_message(update: Update, _: CallbackContext):
    message_text = update.message.text or ""
    lower_text = message_text.lower()

    mentioned = (
        f"@{BOT_USERNAME.lower()}" in lower_text
        or f"@{BOT_USERNAME.lower().replace('_bot','')}" in lower_text
    )

    if not (mentioned):
        return

    # Remove invocation phrases
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

    # Try to parse only if there's extra text after the summon
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
            # Fall through to default reminder block

    # Handle known actions only if LLM succeeded
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
                    reply_prefix + "No mortal burdens recorded yet."
                )
            else:
                msg = "Current burdens:\n" + "\n".join(
                    f"- {task} (due {due})" for task, due in assignments
                )
                await update.message.reply_text(reply_prefix + msg)
            return

    # Default: show upcoming stuff (always works, no LLM needed)
    today = datetime.now().date()
    upcoming = []

    cursor.execute(
        """
        SELECT task, due FROM assignments
        WHERE due >= ? AND due <= date(?, '+7 days')
        ORDER BY due
        """,
        (today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")),
    )
    for task, due in cursor.fetchall():
        days_left = (datetime.strptime(due, "%Y-%m-%d").date() - today).days
        tag = (
            "TODAY"
            if days_left == 0
            else "Tomorrow" if days_left == 1 else f"In {days_left} days"
        )
        upcoming.append(f"{tag}: {task}")

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


# Reminder job
async def send_reminders(context: CallbackContext):

    today = datetime.now().date()

    tomorrow = today + timedelta(days=1)

    cursor.execute(
        "SELECT task, due FROM assignments WHERE due = ? OR due = ?",
        (
            today.strftime("%Y-%m-%d"),
            tomorrow.strftime("%Y-%m-%d"),
        ),
    )

    assignments = cursor.fetchall()

    reminders = []

    for task, due in assignments:

        if due == today.strftime("%Y-%m-%d"):

            reminders.append(f"Due today — brace yourselves: {task}")

        else:

            reminders.append(f"Due tomorrow: {task}")

    cursor.execute(
        "SELECT schedule FROM timetable WHERE day = ?",
        (today.strftime("%A"),),
    )

    schedule = cursor.fetchone()

    if schedule:

        reminders.append(f"Today's path: {schedule[0]}")

    if reminders:

        await context.bot.send_message(
            GROUP_CHAT_ID,
            "Tenskee awakens with tidings of fate! ✨\n" + "\n".join(reminders),
        )


# Boot sequence
logging.basicConfig(level=logging.INFO)

app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message,
    )
)

scheduler = AsyncIOScheduler()

scheduler.add_job(
    send_reminders,
    CronTrigger(hour=8, minute=0),
    args=[app],
)

scheduler.start()

print("Tenskee is listening...")

app.run_polling()
