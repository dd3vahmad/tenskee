# Tenskee – Magical Class Group Assistant

**Tenskee** is a lightweight Telegram/WhatsApp bot that helps class groups stay organized.  
It remembers assignments, due dates, and weekly timetables — and gently reminds everyone when things are approaching.

Current date reference: February 2026

## How It Works

1. **Summon the bot** using the magical incantation  
   Mention the bot **and** include the phrase:  
   `save us`  
   Example:  
   `@tenskee_bot save us`

2. **What happens when summoned**  
   - Shows assignments due **today**, **tomorrow**, or in the next **7 days**  
   - Shows tomorrow's timetable (if previously added)  
   - If the AI is temporarily unavailable → still shows the upcoming info

3. **Supported commands** (add after the summon phrase)

   | Command example                                      | What it does                              |
   |------------------------------------------------------|-------------------------------------------|
   | `add math quiz due 2026-02-25`                       | Add assignment / test                     |
   | `add physics assignment due next Friday`             | Relative dates also work                  |
   | `add timetable Monday OOP 9AM, Stats 11AM`           | Add or update Monday's schedule           |
   | `add timetable Tuesday free day`                     | Any day of the week                       |
   | `list assignments`                                   | Show all saved tasks sorted by due date   |

   Full example:  
   `@tenskee_bot add group project due next Wednesday`

4. **Automatic daily reminder**  
   Every day at **8:00 AM** the bot sends:  
   - Today's due assignments  
   - Today's timetable (if set)

## Setup (Local or Render)

### Prerequisites
- Python 3.10+
- Telegram bot token (create via @BotFather)
- Google Gemini API key (free tier at aistudio.google.com)

### Environment Variables

Create `.env` file (or set in Render dashboard):

```env
TELEGRAM_TOKEN=111*****************
GEMINI_API_KEY=AIzaS*****************
GROUP_CHAT_ID=-103***************    # negative number for groups
BOT_USERNAME=tenskee_bot             # your bot's username without @
```

### Local Run

```bash
# 1. Clone & enter folder
git clone git@github.com:dd3vahmad/tenskee.git
cd tenskee

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python bot.py

# 5. If the command above fails due to an SQLite error
> Create a class_data.db in data/ and try again.
```

### Deploy on Render (free tier)

1. Push code to GitHub
2. New → Web Service → connect repo
3. Settings:
   - Runtime: Python
   - Build: `pip install -r requirements.txt`
   - Start: `python bot.py`
   - Plan: Free
4. Add **Persistent Disk**:
   - Name: `data`
   - Mount path: `/app/data`
   - Size: 1 GB
5. Add the four environment variables (from above)
6. Deploy → bot should be online 24/7

### Troubleshooting

- Bot silent? → Check logs for `[TRIGGER]` lines  
  Must have `@botname` in all commands that apply to the bot.
- Gemini errors? → Free tier quota may be exhausted → bot falls back to showing upcoming items anyway

Enjoy — and may Tenskee save your grades! ✨

Made with love by a student, for students.
