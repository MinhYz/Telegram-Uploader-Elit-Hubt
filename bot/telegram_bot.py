import time
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
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
from services.schedule_service import schedule_service
from bot.keyboards import keyboards
from bot.voice_processor import voice_processor
from bot.web_shell import web_shell
from bot.quiet_hours import quiet_hours_mgr
from utils.system_monitor import get_system_stats, get_neofetch_output, run_speedtest
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
        self.app.add_handler(CommandHandler(["help", "huongdan"], self.help_cmd))
        self.app.add_handler(CommandHandler(["check", "quet"], self.check_cmd))
        self.app.add_handler(CommandHandler(["tkb", "thoikhoabieu", "lichhoc"], self.tkb_cmd))
        self.app.add_handler(CommandHandler("solve", self.solve_cmd))
        self.app.add_handler(CommandHandler(["submit", "nopbai", "nop"], self.submit_cmd))
        self.app.add_handler(CommandHandler(["remove", "delete"], self.remove_cmd))
        self.app.add_handler(CommandHandler("login", self.login_cmd))
        self.app.add_handler(CommandHandler("whoami", self.whoami_cmd))
        self.app.add_handler(CommandHandler("status", self.status_cmd))
        self.app.add_handler(CommandHandler(["neofetch", "sysinfo"], self.neofetch_cmd))
        self.app.add_handler(CommandHandler("speedtest", self.speedtest_cmd))
        self.app.add_handler(CommandHandler("addadmin", self.add_admin_cmd))
        self.app.add_handler(CommandHandler("deladmin", self.del_admin_cmd))
        self.app.add_handler(CommandHandler("adminlist", self.admin_list_cmd))
        self.app.add_handler(CommandHandler(["admin", "panel"], self.admin_cmd))
        self.app.add_handler(CommandHandler("bash", self.bash_cmd))

        # Callback, Voice, Text & Attachment Handlers
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))
        self.app.add_handler(MessageHandler(filters.VOICE, self.voice_cmd_handler))
        self.app.add_handler(MessageHandler(filters.ATTACHMENT, self.file_upload_handler))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.text_message_handler))

        # Global Error Handler
        self.app.add_error_handler(self.global_error_handler)

        return self.app

    async def global_error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Global Error Handler caught exception: {context.error}", exc_info=context.error)
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    f"❌ **ĐÃ XẢY RA LỖI HỆ THỐNG**: `{str(context.error)[:300]}`",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        is_admin = await db.is_admin(uid, OWNER_ID)
        text = (
            "📖 **BẢNG HƯỚNG DẪN SỬ DỤNG ELIT HUBT BOT**\n\n"
            "🔍 **Quét & Theo Dõi Bài Tập**:\n"
            "• `/check` hoặc `/quet`: Quét danh sách bài tập chưa nộp hôm nay.\n"
            "• `/status`: Kiểm tra trạng thái Server VPS, RAM, CPU.\n"
            "• `/neofetch`: Xem tổng quan hệ thống OS & Phần cứng.\n"
            "• `/speedtest`: Đo tốc độ mạng VPS thực tế.\n\n"
            "📅 **Thời Khóa Biểu & Lịch Học**:\n"
            "• `/tkb <tên_lớp>` hoặc `/thoikhoabieu <tên_lớp>`: Tra cứu TKB HUBT (VD: `/tkb th30.10`).\n\n"
            "💡 **Giải Bài Tập Bằng AI**:\n"
            "• `/solve <assignment_id>`: Tự động giải bài tập bằng Gemini AI.\n\n"
            "📤 **Nộp bài & Quản lý Bài Nộp**:\n"
            "• `/submit <assignment_id>`: Nộp file bài làm lên ELit HUBT.\n"
            "• `/remove <assignment_id>`: Gỡ bài nộp trên Moodle.\n\n"
            "👤 **Tài Khoản & Đăng Nhập**:\n"
            "• `/login <msv> <mật_khẩu>`: Đăng nhập tài khoản MSV HUBT.\n"
            "• `/whoami`: Xem tài khoản HUBT đang kết nối với bạn.\n"
        )
        if is_admin:
            text += (
                "\n🛠️ **Lệnh Quản Trị Admin**:\n"
                "• `/admin`: Mở Dashboard Admin & Dọn dẹp rác VPS.\n"
                "• `/addadmin <user_id>` (hoặc reply): Thêm quyền Admin.\n"
                "• `/deladmin <user_id>` (hoặc reply): Gỡ quyền Admin.\n"
                "• `/adminlist`: Xem danh sách Owner & Admin hiện tại.\n"
                "• `/bash pin <pin>` hoặc `/bash <câu_lệnh>`: Remote Terminal Web Shell.\n"
            )
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text(text, parse_mode="Markdown", reply_markup=keyboards.main_menu(uid, is_admin))

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        is_admin = await db.is_admin(uid, OWNER_ID)
        text = (
            "🤖 **HUBT Moodle Automation Framework (AIO)**\n\n"
            "Hệ thống tự động hóa ELit HUBT đa tính năng, bảo mật cao.\n"
            "Vui lòng chọn thao tác từ Menu bên dưới:"
        )
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboards.main_menu(uid, is_admin))

    def _format_assignment_card(self, a: dict) -> str:
        aid = a.get("assignment_id", "N/A")
        is_open = a.get("is_open", True)
        is_submitted = a.get("is_submitted", False)
        opens_at = a.get("opens_at", "").strip()
        due_date = a.get("due_date", "").strip()
        time_rem = a.get("time_remaining", "").strip()

        if not is_open:
            status_text = "🔒 **Trạng thái**: ⏳ **Chưa mở** (Chưa tới thời gian nộp bài)"
        elif is_submitted:
            status_text = "📊 **Trạng thái**: ✅ **Đã nộp**"
        else:
            status_text = "📊 **Trạng thái**: ⚠️ **Chưa nộp**"

        lines = [
            f"📌 **Bài tập #{aid}**",
            f"📘 **Môn**: {a.get('course_name', 'Môn học')}",
            f"📝 **Tiêu đề**: {a.get('title', 'Bài tập')}",
            status_text,
        ]
        if opens_at:
            if not is_open:
                lines.append(f"🔓 **Thời gian mở (Opens)**: `{opens_at}`")
            else:
                lines.append(f"🔓 **Đã mở lúc**: `{opens_at}`")
        if due_date:
            lines.append(f"⏰ **Thời gian hết hạn (Due)**: `{due_date}`")
        if time_rem:
            lines.append(f"⏳ **Thời gian còn lại**: {time_rem}")
        if a.get("url"):
            lines.append(f"🔗 [Xem trên ELit]({a['url']})")

        return "\n".join(lines)

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
                txt = self._format_assignment_card(a)
                await update.message.reply_text(
                    txt,
                    parse_mode="Markdown",
                    reply_markup=keyboards.assignment_action(
                        aid, a.get("is_submitted", False), uid, is_open=a.get("is_open", True)
                    ),
                )
                await db.mark_assignment_seen(aid, a)
        except Exception as e:
            logger.error(f"Check command error: {e}")
            await msg.edit_text(f"❌ **Lỗi khi quét bài tập**: {str(e)}")

    async def tkb_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        args = context.args
        query = " ".join(args).strip() if args else ""

        if not query:
            text = (
                "📅 **TRA CỨU THỜI KHÓA BIỂU HUBT**\n\n"
                "Hệ thống tự động tra cứu từ cổng `https://itc.hubt.edu.vn/thoikhoabieu/`\n\n"
                "👉 **Cú pháp**: `/tkb <tên_khóa/ngành/lớp>`\n"
                "*(Ví dụ: `/tkb th30.10` hoặc `/tkb th30` hoặc `/tkb CNTT`)*\n\n"
                "💡 Hoặc chọn nhanh các lớp mẫu bên dưới:"
            )
            await msg.reply_text(text, parse_mode="Markdown", reply_markup=keyboards.schedule_menu())
            return

        status_msg = await msg.reply_text(f"⏳ **Đang tra cứu thời khóa biểu cho `{query.upper()}`...**", parse_mode="Markdown")
        try:
            result = await schedule_service.fetch_schedule(query)
            messages = schedule_service.format_schedule_messages(result)
            
            if not result.get("success"):
                await status_msg.edit_text(messages[0], parse_mode="Markdown", reply_markup=keyboards.schedule_menu())
                return

            await status_msg.delete()
            for idx, message_chunk in enumerate(messages):
                is_last = (idx == len(messages) - 1)
                reply_markup = keyboards.schedule_result_menu(query) if is_last else None
                await msg.reply_text(
                    message_chunk,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Error in tkb_cmd: {e}", exc_info=True)
            await status_msg.edit_text(f"❌ **Lỗi khi tra cứu thời khóa biểu**: {str(e)}", reply_markup=keyboards.schedule_menu())

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

    async def _handle_submission_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE, direct_aid: Optional[str] = None):
        msg = update.effective_message
        if not msg:
            return

        uid = str(update.effective_user.id)
        reply_msg = msg.reply_to_message
        text_content = f"{msg.text or ''} {msg.caption or ''}".strip()

        # 1. Determine assignment ID
        aid = direct_aid
        if not aid and context.args:
            aid = context.args[0]

        if not aid:
            match_cmd = re.search(r"(?:/)?(?:submit|nopbai|nop)\s*[:=]?\s*(\d+)", text_content, re.IGNORECASE)
            if match_cmd:
                aid = match_cmd.group(1)

        if not aid and reply_msg:
            replied_text = f"{reply_msg.text or ''} {reply_msg.caption or ''}".strip()
            match_reply = (
                re.search(r"BÀI TẬP #(\d+)", replied_text, re.IGNORECASE)
                or re.search(r"Assignment #(\d+)", replied_text, re.IGNORECASE)
                or re.search(r"submit\s+(\d+)", replied_text, re.IGNORECASE)
                or re.search(r"\b(\d{5,7})\b", replied_text)
            )
            if match_reply:
                aid = match_reply.group(1)
            elif reply_msg.document and getattr(reply_msg.document, "file_name", None):
                match_fn = re.search(r"\b(\d{5,7})\b", reply_msg.document.file_name)
                if match_fn:
                    aid = match_fn.group(1)

        if not aid:
            match_any_id = re.search(r"\b(\d{5,7})\b", text_content)
            if match_any_id:
                aid = match_any_id.group(1)

        # 2. Extract Document / Photo attachments from current message OR reply message
        docs_to_submit = []

        # From current message
        if msg.document:
            docs_to_submit.append(msg.document)
        elif msg.photo:
            docs_to_submit.append(msg.photo[-1])

        # From replied message
        if reply_msg:
            if reply_msg.document and reply_msg.document not in docs_to_submit:
                docs_to_submit.append(reply_msg.document)
            elif reply_msg.photo and reply_msg.photo[-1] not in docs_to_submit:
                docs_to_submit.append(reply_msg.photo[-1])

        if not docs_to_submit:
            if aid:
                await msg.reply_text(
                    f"⚠️ **Chưa tìm thấy file bài làm để nộp cho Bài tập #{aid}!**\n\n"
                    f"👉 **Cách 1**: Gửi file bài làm kèm caption: `/submit {aid}`\n"
                    f"👉 **Cách 2**: **Reply trực tiếp vào tin nhắn chứa file** bài làm với lệnh: `/submit {aid}`",
                    parse_mode="Markdown"
                )
            else:
                await msg.reply_text(
                    "📤 **HƯỚNG DẪN NỘP BÀI LÊN ELIT HUBT**:\n\n"
                    "1️⃣ **Cách 1**: Gửi file bài làm (`.pdf`, `.docx`, `.xlsx`, `.zip`) kèm caption: `/submit <ID_Bài_Tập>`\n"
                    "2️⃣ **Cách 2**: **Reply tin nhắn chứa file** với lệnh: `/submit <ID_Bài_Tập>` (Ví dụ: `/submit 119340`)\n"
                    "3️⃣ **Cách 3**: **Gửi file reply vào tin nhắn thông báo bài tập**",
                    parse_mode="Markdown"
                )
            return

        if not aid:
            await msg.reply_text(
                "⚠️ **Không tìm thấy ID bài tập!**\n\n"
                "Vui lòng chỉ định ID bài tập (Ví dụ: `/submit 119340` hoặc reply tin nhắn bài tập).",
                parse_mode="Markdown"
            )
            return

        # 3. Download files and submit
        status_msg = await msg.reply_text(f"⏳ **Đang tải `{len(docs_to_submit)}` file và tiến hành nộp bài tập #{aid} lên ELit HUBT...**", parse_mode="Markdown")

        saved_paths = []
        for doc in docs_to_submit:
            try:
                file_obj = await context.bot.get_file(doc.file_id)
                fname = getattr(doc, "file_name", None) or f"submit_{aid}_{int(time.time())}.pdf"
                local_path = DOWNLOAD_DIR / fname
                await file_obj.download_to_drive(custom_path=local_path)
                saved_paths.append(local_path)
            except Exception as ex_dl:
                logger.error(f"Error downloading user attachment: {ex_dl}")

        if not saved_paths:
            await status_msg.edit_text("❌ **Lỗi**: Không thể tải file bài làm về máy chủ để nộp.")
            return

        scraper = MoodleScraperService(uid)
        success, sub_msg, screenshot_path = await scraper.submit_assignment(aid, saved_paths)
        if success:
            await status_msg.edit_text(f"🎉 **NỘP BÀI THÀNH CÔNG CHO BÀI TẬP #{aid}!**\n\n{sub_msg}")
            if screenshot_path and screenshot_path.exists():
                with open(screenshot_path, "rb") as photo_f:
                    await msg.reply_photo(photo=InputFile(photo_f), caption=f"📸 **Xác nhận nộp bài tập #{aid}**")
        else:
            await status_msg.edit_text(f"❌ **NỘP BÀI THẤT BẠI**: {sub_msg}")

    async def submit_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_submission_flow(update, context)

    async def file_upload_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._handle_submission_flow(update, context)

    async def text_message_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        if not msg or not msg.text:
            return

        text = msg.text.strip()
        # If user typed 'submit ...' or 'nopbai ...' or replied to a message
        if re.search(r"^(?:/)?(?:submit|nopbai|nop)\b", text, re.IGNORECASE):
            await self._handle_submission_flow(update, context)
        elif msg.reply_to_message and (msg.reply_to_message.document or msg.reply_to_message.photo):
            # If user replied to a file with just an ID like '119340'
            if re.match(r"^\d{5,7}$", text):
                await self._handle_submission_flow(update, context, direct_aid=text)

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
        chat_id = msg.chat_id if msg else update.effective_chat.id

        # Security: Try deleting raw credentials message
        try:
            if msg:
                await msg.delete()
        except Exception:
            pass

        if len(args) == 2:
            msv, password = args[0], args[1]
            status_msg = await context.bot.send_message(chat_id=chat_id, text=f"⏳ **Đang tiến hành đăng nhập tài khoản MSV `{msv}` lên ELit HUBT...**", parse_mode="Markdown")
            scraper = MoodleScraperService(uid)
            ok, res = await scraper.login(username=msv, password=password)
            if ok:
                await db.save_user(uid, msv=msv, password=password)
            await status_msg.edit_text(res, parse_mode="Markdown")
        elif len(args) == 1:
            token = args[0]
            status_msg = await context.bot.send_message(chat_id=chat_id, text="⏳ **Đang tiến hành xác thực bằng Token Session Cookie...**", parse_mode="Markdown")
            scraper = MoodleScraperService(uid)
            ok, res = await scraper.login(token=token)
            if ok:
                await db.save_user(uid, token=token)
            await status_msg.edit_text(res, parse_mode="Markdown")
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="🔑 Cú pháp đăng nhập:\n• `/login <msv> <mật_khẩu>`\n• `/login <token_cookie>`",
                parse_mode="Markdown"
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
        if not await db.is_admin(uid, OWNER_ID):
            await update.message.reply_text("⛔ Quyền truy cập bị từ chối!")
            return
        cleaned = storage_cleaner.purge_temp_files()
        await update.message.reply_text(f"🛠️ **ADMIN DASHBOARD**\n\n✅ Đã tự động dọn dẹp `{cleaned}` file rác/temp khỏi VPS.", reply_markup=keyboards.admin_menu())

    async def neofetch_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        output = await get_neofetch_output()
        await msg.reply_text(output, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

    async def speedtest_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        status_msg = await msg.reply_text("⚡ **Đang đo tốc độ băng thông VPS...**", parse_mode="Markdown")
        output = await run_speedtest()
        await status_msg.edit_text(output, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

    async def add_admin_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        uid = str(update.effective_user.id)
        if not await db.is_admin(uid, OWNER_ID):
            await msg.reply_text("⛔ Quyền truy cập bị từ chối!")
            return

        target_id = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            target_id = str(msg.reply_to_message.from_user.id)
        elif context.args:
            target_id = context.args[0]

        if not target_id:
            await msg.reply_text("⚠️ **Cú pháp**: `/addadmin <user_id>` hoặc **reply tin nhắn** của người cần thêm Admin.")
            return

        await db.add_admin(target_id, added_by=uid)
        await msg.reply_text(f"✅ **Đã cấp quyền Admin thành công cho User ID**: `{target_id}`", parse_mode="Markdown")

    async def del_admin_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        uid = str(update.effective_user.id)
        if not await db.is_admin(uid, OWNER_ID):
            await msg.reply_text("⛔ Quyền truy cập bị từ chối!")
            return

        target_id = None
        if msg.reply_to_message and msg.reply_to_message.from_user:
            target_id = str(msg.reply_to_message.from_user.id)
        elif context.args:
            target_id = context.args[0]

        if not target_id:
            await msg.reply_text("⚠️ **Cú pháp**: `/deladmin <user_id>` hoặc **reply tin nhắn** của Admin cần gỡ quyền.")
            return

        if target_id == OWNER_ID:
            await msg.reply_text("❌ Không thể gỡ quyền Admin của hệ thống Owner!")
            return

        ok = await db.remove_admin(target_id)
        if ok:
            await msg.reply_text(f"✅ **Đã gỡ quyền Admin thành công cho User ID**: `{target_id}`", parse_mode="Markdown")
        else:
            await msg.reply_text(f"⚠️ User ID `{target_id}` hiện không nằm trong danh sách Admin.")

    async def admin_list_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        uid = str(update.effective_user.id)
        if not await db.is_admin(uid, OWNER_ID):
            await msg.reply_text("⛔ Quyền truy cập bị từ chối!")
            return

        admins = await db.get_all_admins()
        admin_strs = [f"• `{a}`" for a in admins]
        text = (
            f"👑 **DANH SÁCH OWNER & ADMIN HỆ THỐNG**\n\n"
            f"• **Owner System**: `{OWNER_ID}`\n"
            f"• **Danh sách Admin (`{len(admins)}`)**:\n"
            + ("\n".join(admin_strs) if admin_strs else "*(Chưa có Admin bổ sung)*")
        )
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

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
        is_admin = await db.is_admin(clicker_id, OWNER_ID)

        if data == "btn_main_menu":
            await query.answer()
            text = (
                "🤖 **HUBT Moodle Automation Framework (AIO)**\n\n"
                "Hệ thống tự động hóa ELit HUBT đa tính năng, bảo mật cao.\n"
                "Vui lòng chọn thao tác từ Menu bên dưới:"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.main_menu(clicker_id, is_admin))

        elif data == "btn_neofetch":
            await query.answer("🐧 Đang lấy thông tin Neofetch...")
            output = await get_neofetch_output()
            await query.edit_message_text(output, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

        elif data == "btn_speedtest":
            await query.answer("⚡ Đang kiểm tra tốc độ...")
            await query.edit_message_text("⚡ **Đang đo tốc độ mạng VPS...**", parse_mode="Markdown")
            output = await run_speedtest()
            await query.edit_message_text(output, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

        elif data == "btn_admin_list":
            if not is_admin:
                await query.answer("⛔ Quyền truy cập bị từ chối!", show_alert=True)
                return
            await query.answer()
            admins = await db.get_all_admins()
            admin_strs = [f"• `{a}`" for a in admins]
            text = (
                f"👑 **DANH SÁCH OWNER & ADMIN HỆ THỐNG**\n\n"
                f"• **Owner System**: `{OWNER_ID}`\n"
                f"• **Danh sách Admin (`{len(admins)}`)**:\n"
                + ("\n".join(admin_strs) if admin_strs else "*(Chưa có Admin bổ sung)*")
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

        elif data == "btn_check":
            await query.answer("🔍 Đang quét bài tập...")
            await query.edit_message_text("⏳ **Đang mở Playwright quét lớp học & bài tập hôm nay trên ELit HUBT...**", parse_mode="Markdown")
            scraper = MoodleScraperService(clicker_id)
            try:
                assignments = await scraper.check_today_classes_and_assignments()
                if not assignments:
                    await query.edit_message_text("🎉 **Hôm nay không có bài tập mới nào chưa nộp!**", reply_markup=keyboards.back_to_menu())
                    return

                await query.message.reply_text(f"📋 **Phát hiện `{len(assignments)}` bài tập hôm nay:**")
                for a in assignments:
                    aid = a["assignment_id"]
                    txt = self._format_assignment_card(a)
                    await query.message.reply_text(
                        txt,
                        parse_mode="Markdown",
                        reply_markup=keyboards.assignment_action(
                            aid, a.get("is_submitted", False), clicker_id, is_open=a.get("is_open", True)
                        ),
                    )
                    await db.mark_assignment_seen(aid, a)
            except Exception as e:
                logger.error(f"Check command error: {e}")
                await query.edit_message_text(f"❌ **Lỗi khi quét bài tập**: {str(e)}", reply_markup=keyboards.back_to_menu())

        elif data == "btn_status":
            await query.answer()
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
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.status_menu())

        elif data == "btn_solve_help":
            await query.answer()
            text = (
                "💡 **GIẢI BÀI TẬP TỰ ĐỘNG BẰNG AI GEMINI**\n\n"
                "Hệ thống sẽ tự đọc đề bài PDF/Word và xuất file bài làm chuẩn công thức HUBT.\n\n"
                "👉 **Cú pháp**: `/solve <ID_Bài_Tập>`\n"
                "*(Ví dụ: `/solve 119340` hoặc reply lệnh `/solve` vào tin nhắn bài tập)*"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

        elif data == "btn_tkb_menu":
            await query.answer()
            text = (
                "📅 **TRA CỨU THỜI KHÓA BIỂU HUBT**\n\n"
                "Tra cứu thời khóa biểu trực tuyến từ Cổng ITC HUBT.\n\n"
                "👉 **Cách dùng**: Nhập lệnh `/tkb <tên_lớp>` trong khung chat.\n"
                "*(Ví dụ: `/tkb th30.10`)*\n\n"
                "💡 Hoặc bấm vào lớp gợi ý bên dưới để tra cứu ngay:"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.schedule_menu())

        elif data.startswith("btn_tkb_quick:"):
            target_class = data.split(":", 1)[1]
            await query.answer(f"🔍 Đang tra cứu {target_class.upper()}...")
            status_msg = await query.message.reply_text(f"⏳ **Đang tra cứu thời khóa biểu cho `{target_class.upper()}`...**", parse_mode="Markdown")
            try:
                result = await schedule_service.fetch_schedule(target_class)
                messages = schedule_service.format_schedule_messages(result)
                if not result.get("success"):
                    await status_msg.edit_text(messages[0], parse_mode="Markdown", reply_markup=keyboards.schedule_menu())
                    return
                await status_msg.delete()
                for idx, message_chunk in enumerate(messages):
                    is_last = (idx == len(messages) - 1)
                    reply_markup = keyboards.schedule_result_menu(target_class) if is_last else None
                    await query.message.reply_text(
                        message_chunk,
                        parse_mode="Markdown",
                        disable_web_page_preview=True,
                        reply_markup=reply_markup
                    )
            except Exception as e:
                logger.error(f"Error in btn_tkb_quick: {e}", exc_info=True)
                await status_msg.edit_text(f"❌ **Lỗi khi tra cứu thời khóa biểu**: {str(e)}", reply_markup=keyboards.schedule_menu())

        elif data == "btn_whoami":
            await query.answer()
            user_info = await db.get_user(clicker_id)
            if user_info:
                text = (
                    f"👤 **THÔNG TIN TÀI KHOẢN KẾT NỐI**\n\n"
                    f"• **Telegram ID**: `{clicker_id}`\n"
                    f"• **MSV HUBT**: `{user_info.get('msv', 'N/A')}`\n"
                    f"• **Trạng thái Session**: ✅ Đã lưu encrypted session token"
                )
            else:
                text = (
                    "⚠️ **BẠN CHƯA ĐĂNG NHẬP TÀI KHOẢN HUBT**\n\n"
                    "Vui lòng gửi lệnh trong ô Chat:\n`/login <msv> <mật_khẩu>` hoặc `/login <token_cookie>`"
                )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

        elif data == "btn_admin_panel":
            if not is_admin:
                await query.answer("⛔ ⚠️ BẠN KHÔNG CÓ QUYỀN TRUY CẬP ADMIN DASHBOARD!", show_alert=True)
                return
            await query.answer()
            text = (
                f"🛠️ **ADMIN DASHBOARD CONTROL PANEL**\n\n"
                f"• **Owner Telegram ID**: `{OWNER_ID}`\n"
                f"• **Quyền hạn**: System Privileges / Server Host\n"
                f"• **Thêm Admin**: `/addadmin <id>` (hoặc reply)\n"
                f"• **Gỡ Admin**: `/deladmin <id>` (hoặc reply)\n"
                f"• **Danh sách Admin**: `/adminlist`\n"
                f"• **Lệnh Terminal**: `/bash pin <pin>` hoặc `/bash <câu_lệnh>`\n\n"
                f"Nhấn nút bên dưới để dọn dẹp rác bộ nhớ VPS ngay lập tức:"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.admin_menu())

        elif data == "btn_purge_cache":
            if not is_admin:
                await query.answer("⛔ Quyền truy cập bị từ chối!", show_alert=True)
                return
            cleaned = storage_cleaner.purge_temp_files()
            await query.answer(f"✅ Đã dọn dẹp {cleaned} file rác khỏi VPS!", show_alert=True)

        elif data == "btn_bash_help":
            await query.answer()
            text = (
                "💻 **REMOTE TERMINAL WEB SHELL (/bash)**\n\n"
                "Cho phép thực thi câu lệnh Terminal trực tiếp trên VPS (Bảo vệ bằng PIN 2FA).\n\n"
                "👉 **Xác thực 2FA**: `/bash pin <mã_pin>`\n"
                "👉 **Thực thi lệnh**: `/bash <câu_lệnh>` (Ví dụ: `/bash ls -la`)"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

        elif data.startswith("submit_help:"):
            aid = data.split(":")[1]
            await query.answer()
            text = (
                f"📤 **HƯỚNG DẪN NỘP BÀI CHO BÀI TẬP #{aid}**\n\n"
                f"Vui lòng gửi file bài làm trực tiếp vào Chat này kèm caption: `/submit {aid}`"
            )
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboards.back_to_menu())

        elif data.startswith("remove_"):
            parts = data.split("_")
            aid = parts[1]
            owner_id = parts[2] if len(parts) > 2 else ""

            if owner_id and clicker_id != owner_id and clicker_id != OWNER_ID:
                await query.answer("⛔ ⚠️ BẠN KHÔNG CÓ QUYỀN! Bài nộp này là của người dùng khác.", show_alert=True)
                return

            await query.answer()
            context.args = [aid]
            dummy_update = Update(update.update_id, message=query.message)
            await self.remove_cmd(dummy_update, context)

        elif data.startswith("unopened_info:"):
            aid = data.split(":")[1]
            await query.answer(
                f"⏳ Bài tập #{aid} hiện chưa tới thời gian mở nộp bài. Vui lòng quay lại nộp khi đến giờ mở!",
                show_alert=True
            )

        elif data.startswith("download_materials:"):
            aid = data.split(":")[1]
            await query.answer("⏳ Đang tải file đề bài...")
            status_msg = await query.message.reply_text(f"⏳ **Đang trích xuất file đề bài đính kèm cho Bài tập #{aid}...**")
            scraper = MoodleScraperService(clicker_id)
            try:
                files = await scraper.download_assignment_materials(aid)
                if not files:
                    await status_msg.edit_text(f"⚠️ Không tìm thấy file đề bài đính kèm trên hệ thống cho Bài tập #{aid}.")
                else:
                    await status_msg.edit_text(f"✅ Đã tải thành công `{len(files)}` file đề bài:")
                    for fpath in files:
                        if fpath.exists():
                            with open(fpath, "rb") as f_doc:
                                await query.message.reply_document(
                                    document=InputFile(f_doc, filename=fpath.name),
                                    caption=f"📎 **File đề bài đính kèm**: `{fpath.name}` (Bài tập #{aid})",
                                    parse_mode="Markdown",
                                )
            except Exception as e:
                logger.error(f"Error downloading materials: {e}")
                await status_msg.edit_text(f"❌ Lỗi khi tải file đề bài: {str(e)}")

        elif data.startswith("ai_solve:"):
            aid = data.split(":")[1]
            await query.answer("⏳ Đang giải tự động bài tập bằng Gemini AI...")
            context.args = [aid]
            dummy_update = Update(update.update_id, message=query.message)
            await self.solve_cmd(dummy_update, context)

bot_app = TelegramBotApp()
