import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

import google.generativeai as genai
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackContext, MessageHandler, filters

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
BOT_USERNAME = os.getenv("BOT_USERNAME", "tenskee_bot")

genai.configure(api_key=GEMINI_API_KEY)

# SQLite DB Setup
DB_FILE = "/app/data/class_data.db"  # Render persistent disk mount path

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
conn.commit()


# LLM Parser with Gemini
async def parse_message(text: str) -> dict:
    model = genai.GenerativeModel("gemini-2.5-flash")  # or 'gemini-2.5-flash-lite'

    today_str = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""
    You are Tenskee, a magical class group assistant. Parse the user's message and output ONLY valid JSON:
    - {{"action": "add_assignment", "task": "string", "due": "YYYY-MM-DD"}}
    - {{"action": "add_timetable", "day": "Monday", "schedule": "string like 'Math 9AM, Physics 11AM'"}}
    - {{"action": "list_assignments"}}
    - {{"action": "unknown"}}
    
    Convert relative dates (e.g. "next Friday", "tomorrow") to absolute YYYY-MM-DD. Today is {today_str}.
    Message: {text}
    """

    response = model.generate_content(prompt)
    try:
        cleaned = (
            response.text.strip().removeprefix("```json").removesuffix("```").strip()
        )
        return json.loads(cleaned)
    except Exception as e:
        logging.error(f"Parse error: {e}")
        return {"action": "unknown"}


# Handle incoming messages - Trigger on "Tenskee save us" incantation + mention
async def handle_message(update: Update, context: CallbackContext):
    message_text = update.message.text or ""
    lower_text = message_text.lower()

    # Check if bot is mentioned
    mentioned = (
        f"@{BOT_USERNAME.lower()}" in lower_text
        or f'@{BOT_USERNAME.lower().replace("_bot", "")}' in lower_text
    )

    # Check for the incantation
    incantation_detected = "tenskee save us" in lower_text

    if not (mentioned and incantation_detected):
        return  # Silent unless properly summoned

    # Remove the invocation phrase so we can still detect if there's extra command text
    cleaned_text = message_text
    for phrase in [
        "Tenskee save us",
        "tenskee save us",
        f"@{BOT_USERNAME} save us",
        f"@{BOT_USERNAME.replace('_bot', '')} save us",
        f"@{BOT_USERNAME} Tenskee save us",
        f"@{BOT_USERNAME.replace('_bot', '')} Tenskee save us",
    ]:
        cleaned_text = (
            cleaned_text.replace(phrase, "", 1)
            .strip()
            .replace(phrase.lower(), "", 1)
            .strip()
        )

    cleaned_text = cleaned_text.strip()

    reply_prefix = "Tenskee hears your desperate call… ✨ I bring salvation!\n\n"

    # If there's additional text after the incantation → try to parse it as command
    if cleaned_text:
        parsed = await parse_message(cleaned_text)

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

        # If parsed something unknown → fall through to default "save us" response

    # Default "save us" behavior: show upcoming stuff
    today = datetime.now().date()
    upcoming = []

    # Assignments due in next 7 days
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
        if days_left == 0:
            upcoming.append(f"**TODAY**: {task}")
        elif days_left == 1:
            upcoming.append(f"**Tomorrow**: {task}")
        else:
            upcoming.append(f"In {days_left} days: {task}")

    # Tomorrow's timetable
    tomorrow = (today + timedelta(days=1)).strftime("%A")
    cursor.execute("SELECT schedule FROM timetable WHERE day = ?", (tomorrow,))
    sched = cursor.fetchone()
    if sched:
        upcoming.append(f"**Tomorrow's classes**: {sched[0]}")

    if upcoming:
        response = reply_prefix + "These trials approach:\n" + "\n".join(upcoming)
    else:
        response = reply_prefix + "All is calm… for now. No immediate doom detected."

    await update.message.reply_text(response)


# Reminder job (daily at 8 AM)
async def send_reminders(context: CallbackContext):
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)

    cursor.execute(
        "SELECT task, due FROM assignments WHERE due = ? OR due = ?",
        (today.strftime("%Y-%m-%d"), tomorrow.strftime("%Y-%m-%d")),
    )
    assignments = cursor.fetchall()
    reminders = []
    for task, due in assignments:
        if datetime.strptime(due, "%Y-%m-%d").date() == today:
            reminders.append(f"Due today — brace yourselves: {task}")
        else:
            reminders.append(f"Due tomorrow: {task}")

    day = today.strftime("%A")
    cursor.execute("SELECT schedule FROM timetable WHERE day = ?", (day,))
    schedule = cursor.fetchone()
    if schedule:
        reminders.append(f"Today's path: {schedule[0]}")

    if reminders:
        await context.bot.send_message(
            GROUP_CHAT_ID,
            "Tenskee awakens with tidings of fate! ✨\n" + "\n".join(reminders),
        )


# Main
logging.basicConfig(level=logging.INFO)
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

scheduler = AsyncIOScheduler()
scheduler.add_job(send_reminders, CronTrigger(hour=8, minute=0), args=[app])
scheduler.start()

print("Tenskee is listening...")
app.run_polling()
