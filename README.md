# 🤖 HUBT Moodle Automation Framework (AIO) v2.0

Full-stack, enterprise-grade, microservice-style automated workflow framework linking **ELit HUBT** (Moodle LMS at `https://elit.hubt.edu.vn`) with **Telegram Bot API**, **Playwright Stealth**, and **Google Gemini AI API**.

Designed specifically for low-resource cloud instances (e.g. Oracle Cloud AMD 1 vCPU, 1GB RAM + 4GB Swap).

---

## 📁 Clean & Modular Project Architecture

```text
Upload to elit/
├── config/             # System settings & Pydantic environment configuration (.env)
├── core/               # Low-RAM Browser Context Pool, Stealth Anti-Bot, DOM Engine, Session Vault
├── database/           # Async SQLite engine (aiosqlite) & AES-256 Fernet data encryption
├── services/           # Moodle Scraper, AI Solver, Self-Debugger, Adaptive Scheduler, Analytics, Cloud Sync
├── bot/                # Telegram Bot handlers, Dynamic Keyboards, Voice (Edge-TTS), Web Shell, Quiet Hours
├── utils/              # Standardized HUBT Cover Generator (DOCX/PDF), Cleaner, System Monitor, Git Patcher
├── legacy/             # Legacy single-file scripts archived for reference
├── data/               # Persistent SQLite database storage
├── downloads/          # Assignment downloads & generated solution files
├── screenshots/        # Visual proof submission screenshots
├── logs/               # Loguru structured JSON & rotating log files
├── Dockerfile          # Multi-stage lightweight container setup
├── docker-compose.yml  # Resource-capped Docker Compose config (512M RAM limit)
├── requirements.txt    # Python dependencies
└── main.py             # Unified Application Entry Point
```

---

## 🚀 Quick Setup & Execution

### 1. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Fill in your secrets:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
DEFAULT_CHAT_ID=your_chat_id
GEMINI_API_KEY=your_gemini_key
OWNER_ID=5158297014
```

### 2. Run via Docker Compose (Recommended for VPS)
```bash
docker compose up -d --build
```

### 3. Run Locally (Python 3.11+)
```bash
pip install -r requirements.txt
playwright install chromium
PYTHONPATH=. python3 main.py
```

---

## 🕹 Command Cheat-Sheet

| Command | Description |
|---|---|
| `/start` | Open interactive main menu dashboard |
| `/tkb <lớp>` | Tra cứu thời khóa biểu HUBT từ itc.hubt.edu.vn (VD: `/tkb th30.10`) |
| `/check` | Scan active classes & list unsubmitted assignments |
| `/solve <id>` | AI auto-solve assignment & generate Word/Excel solutions |
| `/submit <id>` | Nộp bài tập kèm file đính kèm |
| `/remove <id>` | Gỡ bài nộp trên Moodle (Chỉ chính chủ bài nộp mới thực hiện được) |
| `/status` | Live VPS CPU %, RAM %, Swap %, Disk space & Uptime stats |
| `/login` | Đăng nhập tài khoản MSV/Token cá nhân bảo mật |
| `/bash pin <pin>` | Remote Terminal Web Shell (Xác thực PIN 2FA) |
