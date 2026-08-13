import time
import re
from pathlib import Path
from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
)
from config.settings import TELEGRAM_BOT_TOKEN, OWNER_ID, DEFAULT_CHAT_ID, DOWNLOAD_DIR
from database.db import db
from services.moodle_scraper import MoodleScraperService, SessionExpiredException
from services.ai_solver import ai_solver
from services.self_debugger import self_debugger
from services.analytics import grade_analytics
from bot.keyboards import keyboards
from bot.voice_processor import voice_processor
from bot.web_shell import web_shell
from bot.quiet_hours import quiet_hours_mgr
from utils.system_monitor import get_system_stats
from utils.cleaner import storage_cleaner
from utils.logger import logger

class TelegramBotApp:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.app = None

    def build(self):
        if not self.token:
            logger.error("TELEGRAM_BOT_TOKEN is missing!")
            return None

        self.app = ApplicationBuilder().token(self.token).build()

        # Command Handlers
        self.app.add_handler(CommandHandler(["start", "menu"], self.start_cmd))
        self.app.add_handler(CommandHandler(["check", "quet"], self.check_cmd))
        self.app.add_handler(CommandHandler("solve", self.solve_cmd))
        self.app.add_handler(CommandHandler("submit", self.submit_cmd))
        self.app.add_handler(CommandHandler(["remove", "delete"], self.remove_cmd))
        self.app.add_handler(CommandHandler("login", self.login_cmd))
        self.app.add_handler(CommandHandler("whoami", self.whoami_cmd))
        self.app.add_handler(CommandHandler("status", self.status_cmd))
        self.app.add_handler(CommandHandler(["admin", "panel"], self.admin_cmd))
        self.app.add_handler(CommandHandler("bash", self.bash_cmd))

        # Callback & Voice Handlers
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))
        self.app.add_handler(MessageHandler(filters.VOICE, self.voice_cmd_handler))
        self.app.add_handler(MessageHandler(filters.ATTACHMENT, self.file_upload_handler))

        return self.app

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        is_admin = uid == OWNER_ID
        text = (
            "🤖 **HUBT Moodle Automation Framework (AIO)**\n\n"
            "Hệ thống tự động hóa ELit HUBT đa tính năng, bảo mật cao.\n"
            "Vui lòng chọn thao tác từ Menu bên dưới:"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboards.main_menu(uid, is_admin))

    async def check_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        msg = await update.message.reply_text("⏳ **Đang mở Playwright quét lớp học & bài tập hôm nay trên ELit HUBT...**")
        scraper = MoodleScraperService(uid)
        try:
            assignments = await scraper.check_today_classes_and_assignments()
            if not assignments:
                await msg.edit_text("🎉 **Hôm nay không có bài tập mới nào chưa nộp!**")
                return

            await msg.edit_text(f"📋 **Phát hiện `{len(assignments)}` bài tập hôm nay:**")
            for a in assignments:
                aid = a["assignment_id"]
                txt = (
                    f"📌 **Bài tập #{aid}**\n"
                    f"📘 **Môn**: {a['course_name']}\n"
                    f"📝 **Tiêu đề**: {a['title']}\n"
                    f"📊 **Trạng thái**: {a['status']}\n"
                    f"⏳ **Thời gian còn lại**: {a['time_remaining']}\n"
                    f"🔗 [Xem trên ELit]({a['url']})"
                )
                await update.message.reply_text(
                    txt,
                    parse_mode="Markdown",
                    reply_markup=keyboards.assignment_action(aid, a["is_submitted"], uid),
                )
                await db.mark_assignment_seen(aid, a)
        except Exception as e:
            logger.error(f"Check command error: {e}")
            await msg.edit_text(f"❌ **Lỗi khi quét bài tập**: {str(e)}")

    async def solve_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        args = context.args
        aid = args[0] if args else "119340"
        
        status_msg = await msg.reply_text(f"⏳ **AI Gemini đang giải tự động Bài tập #{aid}...**")
        files = list(DOWNLOAD_DIR.glob(f"*{aid}*"))
        file_strs = [str(f) for f in files]
        
        student_info = {"name": "Trần Tuấn Minh", "id": "16T-Tin3"}
        success, out_path, caption = await ai_solver.solve_assignment_file(file_strs, aid, student_info)
        
        if success and out_path.exists():
            with open(out_path, "rb") as f_doc:
                await msg.reply_document(document=InputFile(f_doc, filename=out_path.name), caption=caption)
            await status_msg.delete()
        else:
            await status_msg.edit_text(f"❌ **Giải bài bằng AI thất bại**: {caption}")

    async def submit_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("📤 **Vui lòng gửi file bài làm trực tiếp vào Chat kèm caption `/submit <ID_Bài_Tập>`!**")

    async def file_upload_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        caption = msg.caption or ""
        match = re.search(r"submit\s+(\d+)", caption, re.IGNORECASE)
        if not match:
            return

        aid = match.group(1)
        uid = str(msg.from_user.id)
        doc = msg.document or (msg.photo[-1] if msg.photo else None)
        if not doc:
            return

        status_msg = await msg.reply_text(f"⏳ **Đang tải file và nộp bài tập #{aid}...**")
        file_obj = await context.bot.get_file(doc.file_id)
        local_path = DOWNLOAD_DIR / getattr(doc, "file_name", f"submit_{aid}.pdf")
        await file_obj.download_to_drive(custom_path=local_path)

        scraper = MoodleScraperService(uid)
        success, sub_msg, screenshot_path = await scraper.submit_assignment(aid, [local_path])
        if success:
            await status_msg.edit_text(f"🎉 **NỘP BÀI THÀNH CÔNG CHO BÀI TẬP #{aid}!**\n\n{sub_msg}")
            if screenshot_path and screenshot_path.exists():
                with open(screenshot_path, "rb") as photo_f:
                    await msg.reply_photo(photo=InputFile(photo_f), caption=f"📸 **Xác nhận nộp bài tập #{aid}**")
        else:
            await status_msg.edit_text(f"❌ **NỘP BÀI THẤT BẠI**: {sub_msg}")

    async def remove_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        args = context.args
        if not args:
            await update.message.reply_text("⚠️ Cú pháp: `/remove <ID_Bài_tập>` (Ví dụ: `/remove 119340`)")
            return

        aid = args[0]
        status_msg = await update.message.reply_text(f"⏳ **Đang tiến hành gỡ bài nộp cho Bài tập #{aid}...**")
        scraper = MoodleScraperService(uid)
        success, msg_result, screenshot_path = await scraper.remove_assignment_submission(aid)
        if success:
            await status_msg.edit_text(f"✅ **ĐÃ XÓA BÀI NỘP THÀNH CÔNG!**\n\n{msg_result}")
            if screenshot_path and screenshot_path.exists():
                with open(screenshot_path, "rb") as photo_f:
                    await update.message.reply_photo(photo=InputFile(photo_f), caption=f"📸 Trạng thái gỡ bài #{aid}")
        else:
            await status_msg.edit_text(f"❌ **XÓA BÀI NỘP THẤT BẠI**: {msg_result}")

    async def login_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        msg = update.message
        args = context.args
        await msg.delete() # Security: Delete credentials message immediately

        if len(args) == 2:
            msv, password = args[0], args[1]
            scraper = MoodleScraperService(uid)
            ok, res = await scraper.login(username=msv, password=password)
            if ok:
                await db.save_user(uid, msv=msv, password=password)
            await context.bot.send_message(chat_id=uid, text=res)
        elif len(args) == 1:
            token = args[0]
            scraper = MoodleScraperService(uid)
            ok, res = await scraper.login(token=token)
            if ok:
                await db.save_user(uid, token=token)
            await context.bot.send_message(chat_id=uid, text=res)
        else:
            await context.bot.send_message(
                chat_id=uid,
                text="🔑 Cú pháp: `/login <msv> <mật_khẩu>` hoặc `/login <token_cookie>`"
            )

    async def whoami_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        user_info = await db.get_user(uid)
        if user_info:
            text = (
                f"👤 **TÀI KHOẢN KẾT NỐI**\n\n"
                f"• **Telegram ID**: `{uid}`\n"
                f"• **MSV HUBT**: `{user_info.get('msv', 'N/A')}`\n"
                f"• **Trạng thái Session**: ✅ Đã lưu encrypted session token"
            )
        else:
            text = "⚠️ Bạn chưa đăng nhập tài khoản HUBT trên Bot. Vui lòng dùng lệnh `/login`."
        await update.message.reply_text(text, parse_mode="Markdown")

    async def status_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = get_system_stats()
        text = (
            f"📊 **HỆ THỐNG VPS ORACLE CLOUD MONITOR**\n\n"
            f"• **PID Process**: `{stats['pid']}`\n"
            f"• **Uptime**: `{stats['uptime']}`\n"
            f"• **CPU Usage**: `{stats['cpu_percent']}%`\n"
            f"• **RAM Usage**: `{stats['ram_used_mb']} MB / {stats['ram_total_mb']} MB` (`{stats['ram_percent']}%`)\n"
            f"• **Swap Usage**: `{stats['swap_used_mb']} MB / {stats['swap_total_mb']} MB` (`{stats['swap_percent']}%`)\n"
            f"• **Process RAM**: `{stats['process_ram_mb']} MB` (Target < 300MB)\n"
            f"• **Disk Free**: `{stats['disk_free_gb']} GB` (`{stats['disk_percent']}%` dùng)"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

    async def admin_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        if uid != OWNER_ID:
            await update.message.reply_text("⛔ Quyền truy cập bị từ chối!")
            return
        cleaned = storage_cleaner.purge_temp_files()
        await update.message.reply_text(f"🛠️ **ADMIN DASHBOARD**\n\n✅ Đã tự động dọn dẹp `{cleaned}` file rác/temp khỏi VPS.")

    async def bash_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        args = context.args
        if not args:
            await update.message.reply_text("💻 Cú pháp: `/bash pin <mã_pin>` hoặc `/bash <câu_lệnh>`")
            return

        if args[0].lower() == "pin" and len(args) > 1:
            ok = web_shell.authenticate(uid, args[1])
            if ok:
                await update.message.reply_text("✅ **Xác thực PIN 2FA thành công!** Bạn có thể thực thi lệnh `/bash <câu_lệnh>`.")
            else:
                await update.message.reply_text("❌ Mã PIN 2FA không chính xác!")
            return

        output = await web_shell.execute_cmd(uid, " ".join(args))
        await update.message.reply_text(output, parse_mode="Markdown")

    async def voice_cmd_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        voice = msg.voice
        if voice:
            voice_file = await context.bot.get_file(voice.file_id)
            save_p = DOWNLOAD_DIR / f"voice_{int(time.time())}.ogg"
            await voice_file.download_to_drive(custom_path=save_p)

            reply_text = "🎙️ Đã nhận lệnh giọng nói. Đang thực thi yêu cầu của bạn..."
            reply_ogg = await voice_processor.text_to_speech_ogg(reply_text)
            with open(reply_ogg, "rb") as ogg_f:
                await msg.reply_voice(voice=InputFile(ogg_f))

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data
        clicker_id = str(query.from_user.id)

        if data.startswith("remove_"):
            parts = data.split("_")
            aid = parts[1]
            owner_id = parts[2] if len(parts) > 2 else ""

            if owner_id and clicker_id != owner_id and clicker_id != OWNER_ID:
                await query.answer("⛔ ⚠️ BẠN KHÔNG CÓ QUYỀN! Bài nộp này là của người dùng khác.", show_alert=True)
                return

            await query.answer()
            context.args = [aid]
            await self.remove_cmd(update, context)

        elif data.startswith("ai_solve:"):
            aid = data.split(":")[1]
            await query.answer("⏳ Đang giải tự động bài tập bằng Gemini AI...")
            context.args = [aid]
            await self.solve_cmd(update, context)

bot_app = TelegramBotApp()
