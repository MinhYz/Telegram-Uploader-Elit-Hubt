# 🤖 ELit HUBT Telegram Bot Automation (Multi-Account & AI-Powered)

Full-stack automated workflow integration linking **ELit HUBT** (Moodle LMS at `https://elit.hubt.edu.vn`) with a **Telegram Bot** using **Playwright**, **python-telegram-bot**, and **Google Gemini AI API**.

---

## 🌟 Key Features

1. **🔐 Multi-Account & Token Session Persistence (`/login`)**:
   - Secure `/login <msv> <password>` or `/login <token>` command that **immediately deletes** incoming credential/token messages from Telegram chat for security.
   - Per-user isolated storage state and token management (`MoodleSession`).
   - Automatic background session recovery & auto-relogin when sessions expire.

2. **👑 Owner & Admin Control Panel (`/admin` or `/panel`)**:
   - Owner Telegram User ID: System privileges & admin management (`/addadmin`, `/deladmin`, `/adminlist`).
   - Server Host Status Monitoring: CPU, RAM, OS specs, Process PID, Uptime, disk cache usage.
   - 1-Click Cache Cleaner: Clears temp files and downloads instantly.
   - **Terminal Shell Execution (`/exec <command>`)**: Execute shell commands directly on server host.
   - **Broadcast Notifications (`/broadcast <message>`)**: Send alert messages to all registered users.

3. **🔘 Telegram Native Menu App Button**:
   - Automatic registration of Bot Commands and Chat Menu Button directly in Telegram UI.

4. **🔍 Today's Class & Assignment Scan (`/check`)**:
   - Navigates Portal (`local/portal/index.php`) and active courses.
   - Scans for unsubmitted assignment modules (`mod/assign/view.php?id=...`).
   - Downloads attached homework files (PDF, DOCX, XLSX) into Telegram chat.

5. **📤 Submission Flow via Telegram File Reply (`/submit`)**:
   - Send file with caption `/submit <Assignment_ID>` or reply to assignment alert.
   - Automated file upload on Moodle with visual confirmation screenshot returned to Telegram.

6. **💡 AI-Assisted Solution Helper (`/solve`)**:
   - Integrated with Google Gemini API (`google-genai`).
   - Command `/solve <Assignment_ID>` automatically solves assignment PDFs/DOCX files and generates ready-to-submit `.xlsx` with official formulas + detailed solution `.docx`.

7. **⏰ Background Scheduler & Auto Notifications**:
   - Built-in `JobQueue` background scanner running every 30 minutes.
   - Instant Telegram alerts for newly posted unsubmitted assignments.

---

## 📁 Project Structure

```text
Upload to elit/
├── config.py           # Environment variables, URLs, file paths, rotating file logger
├── session_manager.py  # UserStore, AdminStore, Playwright session & token manager
├── elit_scraper.py     # Playwright headless LMS automation (login, scan, download, upload)
├── ai_helper.py        # AI-Assisted Solution Helper (Excel formula engine & Gemini API)
├── scheduler_db.py     # Local state tracker (submitted_jobs.json) to avoid duplicate alerts
├── bot.py              # Main Telegram Bot (Commands, Admin Panel, JobQueue, Menu button)
├── requirements.txt    # Python dependencies
├── .env.example        # Template for environment configuration
├── .gitignore          # Git exclusion rules for secrets, sessions, logs, and temp files
└── README.md           # Setup & execution instructions
```

---

## 🚀 Quick Setup & Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Edit `.env` and fill in your credentials:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
DEFAULT_CHAT_ID=your_chat_id
GEMINI_API_KEY=your_gemini_api_key
OWNER_ID=5158297014
CHECK_INTERVAL_MINUTES=30
HEADLESS=true
```

### 3. Run the Bot
```bash
python3 bot.py
```

---

## 🕹 Command Cheat-Sheet

| Command | Description |
|---|---|
| `/start` | Start bot and open interactive main menu |
| `/help` | Detailed guide and command list |
| `/whoami` | View current user profile, MSV, and session status |
| `/login <msv> <pass>` | Log into ELit HUBT (or `/login <token>`) |
| `/check` | Scan active classes and unsubmitted assignments |
| `/solve <id>` | AI auto-solve assignment and generate `.xlsx` + `.docx` |
| `/submit <id>` | Submit file to ELit HUBT LMS |
| `/remove <id>` | Remove uploaded submission from LMS |
| `/admin` | Open Admin Control Panel Dashboard |
| `/exec <cmd>` | Execute terminal shell command on server host (Admin) |
| `/broadcast <text>`| Send broadcast message to all users (Admin) |
| `/status` | View bot uptime, storage usage, and system stats |
| `/logout` | Safely log out and clear user session |
