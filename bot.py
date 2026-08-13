import asyncio
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, BotCommand, MenuButtonCommands
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from config import (
    TELEGRAM_BOT_TOKEN,
    DEFAULT_CHAT_ID,
    CHECK_INTERVAL_MINUTES,
    SESSION_FILE,
    DOWNLOAD_DIR,
    SCREENSHOT_DIR,
    LOG_FILE,
    OWNER_ID,
    logger,
)
from session_manager import SessionManager, UserStore, AdminStore
from scheduler_db import StateTracker
from elit_scraper import ElitScraper, SessionExpiredException
import ai_helper
from ai_helper import generate_solution_draft, solve_assignment_file

# Global state
BOT_START_TIME = datetime.now()
user_store = UserStore()
admin_store = AdminStore()
state_db = StateTracker()


def get_user_scraper(user_id: str = None) -> tuple[ElitScraper, SessionManager]:
    """Returns an ElitScraper instance and SessionManager scoped to a specific Telegram user."""
    user_id_str = str(user_id) if user_id else "default"
    mgr = SessionManager(user_id=user_id_str)
    return ElitScraper(session_manager=mgr), mgr


async def ensure_user_session(user_id: str) -> tuple[bool, ElitScraper]:
    """
    Ensures an active session for user_id.
    If session is expired BUT credentials or token exist in UserStore, performs automatic background recovery.
    """
    user_id_str = str(user_id)
    scr, mgr = get_user_scraper(user_id_str)

    if mgr.has_session():
        return True, scr

    # Try auto-recovery using saved token or credentials
    user_info = user_store.get_user(user_id_str)
    if user_info:
        token = user_info.get("token")
        if token:
            if mgr.create_session_from_token(token):
                if mgr.has_session():
                    return True, scr

        msv = user_info.get("msv")
        password = user_info.get("password")
        if msv and password:
            logger.info(f"Auto-relogging user {user_id_str} (MSV: {msv})...")
            res = await scr.login(msv, password)
            success = res[0]
            new_token = res[2] if len(res) > 2 else ""
            if success:
                user_store.save_user(
                    user_id=user_id_str,
                    msv=msv,
                    password=password,
                    chat_id=user_info.get("chat_id"),
                    username=user_info.get("username"),
                    token=new_token,
                )
                return True, scr

    # Fallback to default session.json
    default_mgr = SessionManager()
    if default_mgr.has_session():
        return True, ElitScraper(session_manager=default_mgr)

    return False, scr


# Helper: Build Main Menu Keyboard
def get_main_menu_keyboard(user_id: str = None) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🔄 Kiểm tra bài mới (/check)", callback_data="menu_check"),
            InlineKeyboardButton("❓ Hướng dẫn (/help)", callback_data="menu_help"),
        ],
        [
            InlineKeyboardButton("👤 Tài khoản (/whoami)", callback_data="menu_whoami"),
            InlineKeyboardButton("📊 Trạng thái (/status)", callback_data="menu_status"),
        ],
        [
            InlineKeyboardButton("⚙️ Bật/Tắt Auto Check", callback_data="menu_toggle_autocheck"),
            InlineKeyboardButton("🔑 Đăng nhập (/login)", callback_data="menu_login_help"),
        ],
    ]
    if user_id and admin_store.is_admin(str(user_id)):
        keyboard.append([
            InlineKeyboardButton("🛠️ Admin Panel (/admin)", callback_data="menu_admin_panel")
        ])
    return InlineKeyboardMarkup(keyboard)


# Helper: Build Admin Menu Keyboard
def get_admin_menu_keyboard(user_id: str) -> InlineKeyboardMarkup:
    is_owner = admin_store.is_owner(user_id)
    keyboard = [
        [
            InlineKeyboardButton("🖥️ Status Server Host", callback_data="admin_server_status"),
            InlineKeyboardButton("🧹 Dọn Dẹp Cache (Clear)", callback_data="admin_clear_cache"),
        ],
        [
            InlineKeyboardButton("👥 Quản Lý User & Accounts", callback_data="admin_user_list"),
            InlineKeyboardButton("📢 Broadcast Tin Nhắn", callback_data="admin_broadcast_help"),
        ],
        [
            InlineKeyboardButton("⚙️ Toggle Auto Check", callback_data="menu_toggle_autocheck"),
            InlineKeyboardButton("💻 Shell Terminal (/exec)", callback_data="admin_exec_help"),
        ],
    ]
    if is_owner:
        keyboard.append([
            InlineKeyboardButton("👑 Quản Lý Admin (/adminlist)", callback_data="admin_list_roles"),
        ])
    keyboard.append([
        InlineKeyboardButton("🔙 Trở về Menu chính", callback_data="menu_start"),
    ])
    return InlineKeyboardMarkup(keyboard)


# Command: /start & /menu
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    welcome_text = (
        "🤖 **HỆ THỐNG BOT TỰ ĐỘNG HÓA ELIT HUBT LMS**\n\n"
        "Chào mừng bạn! Bot hỗ trợ kết nối hệ thống LMS ELit HUBT với Telegram (Hỗ trợ Nhiều Tài Khoản):\n"
        "• 🔐 **Đăng nhập**: `/login <msv> <matkhau>`\n"
        "• 👤 **Tài khoản**: `/whoami` hoặc `/account`\n"
        "• 🔍 **Quét bài tập**: `/check`\n"
        "• 💡 **AI Giải bài tập**: `/solve <ID>`\n"
        "• 📤 **Nộp bài tập**: `/submit <ID>`\n"
        "• ❓ **Hướng dẫn sử dụng**: `/help` hoặc `/huongdan`\n"
    )
    if admin_store.is_admin(user_id):
        welcome_text += "\n🛠️ **Bạn là ADMIN/OWNER**: Dùng `/admin` để mở Control Panel."

    msg = update.effective_message
    if msg:
        await msg.reply_text(
            welcome_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(user_id)
        )


# Command: /help & /huongdan
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = str(update.effective_user.id)
    help_text = (
        "📖 **BẢNG HƯỚNG DẪN VÀ DANH SÁCH LỆNH BOT ELIT HUBT**\n\n"
        "🔐 **Quản lý Tài khoản (Hỗ trợ Nhiều Tài Khoản)**:\n"
        "• `/login <msv> <matkhau>`: Đăng nhập tài khoản HUBT LMS riêng cho bạn (Tự động xóa tin nhắn chứa mật khẩu để bảo mật).\n"
        "• `/whoami` hoặc `/account`: Xem thông tin tài khoản HUBT đang kết nối với bạn.\n"
        "• `/logout`: Đăng xuất và xóa session/dữ liệu tài khoản của bạn.\n\n"
        "🔍 **Quét & Theo dõi Bài tập**:\n"
        "• `/check`: Quét danh sách môn học & liệt kê toàn bộ bài tập chưa nộp hôm nay.\n"
        "• `/status`: Kiểm tra thời gian chạy, trạng thái JobQueue và dung lượng bộ nhớ.\n\n"
        "💡 **Giải Bài Tập Bằng AI**:\n"
        "• `/solve <assignment_id>`: Giải tự động bài tập bằng AI (tự động xuất file Word giải PDF + file Excel nạp công thức chuẩn).\n\n"
        "📤 **Nộp bài & Quản lý Bài Nộp**:\n"
        "• `/submit <assignment_id>`: Nộp file đính kèm trực tiếp lên Moodle LMS.\n"
        "• `/remove <assignment_id>`: Xóa bài nộp đã tải lên LMS.\n\n"
    )
    if admin_store.is_admin(user_id):
        help_text += (
            "🛠️ **Lệnh dành cho Admin / Owner**:\n"
            "• `/admin` hoặc `/panel`: Mở Dashboard Control Panel Quản trị Server Host.\n"
            "• `/exec <câu_lệnh>`: Thực thi câu lệnh Terminal Shell trực tiếp trên Server.\n"
            "• `/broadcast <nội_dung>`: Gửi tin nhắn thông báo tới tất cả người dùng.\n"
            "• `/addadmin <id>` | `/deladmin <id>`: Thêm/Xóa quyền Admin.\n"
            "• `/adminlist`: Xem danh sách Owner & Admin hiện tại.\n\n"
        )
    help_text += (
        "⚙️ **Tính năng đặc biệt**:\n"
        "- **Multi-Account**: Mỗi người dùng Telegram có thể đăng nhập tài khoản MSV riêng độc lập.\n"
        "- **Auto-Relogin**: Tự động gia hạn session khi hết hạn trong background job mà không bị gián đoạn."
    )
    if msg:
        await msg.reply_text(
            help_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(user_id)
        )


# Command: /whoami & /account
async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    user_id = str(user.id)
    user_info = user_store.get_user(user_id)
    scr, mgr = get_user_scraper(user_id)
    has_sess = mgr.has_session()

    if user_info:
        msv = user_info.get("msv", "N/A")
        updated_at = user_info.get("updated_at", "N/A")
        role_str = "👑 OWNER" if admin_store.is_owner(user_id) else ("⭐ ADMIN" if admin_store.is_admin(user_id) else "👤 Sinh viên")
        text = (
            f"👤 **THÔNG TIN TÀI KHOẢN ELIT HUBT CỦA BẠN**\n\n"
            f"• 🆔 **Telegram ID**: `{user_id}` (@{user.username or user.first_name})\n"
            f"• 🎖️ **Vai trò**: {role_str}\n"
            f"• 🎓 **Mã Sinh Viên (MSV)**: `{msv}`\n"
            f"• 🔑 **Trạng thái Session**: {'✅ Đang hoạt động' if has_sess else '⚠️ Đã hết hạn (Tự động gia hạn khi dùng)'}\n"
            f"• 🕒 **Cập nhật gần nhất**: `{updated_at}`\n\n"
            f"Dùng `/logout` nếu bạn muốn đăng xuất tài khoản này."
        )
    else:
        text = (
            f"⚠️ **Bạn chưa đăng nhập tài khoản ELit HUBT nào!**\n\n"
            f"Dùng lệnh: `/login <Mã_Sinh_Viên> <Mật_Khẩu>` để đăng nhập."
        )

    if msg:
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard(user_id))


# Command: /admin or /panel (Admin Control Panel)
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = str(update.effective_user.id)

    if not admin_store.is_admin(user_id):
        if msg:
            await msg.reply_text("⛔ **BẠN KHÔNG CÓ QUYỀN QUẢN TRỊ (ADMIN)!**\nChỉ Owner (ID: `5158297014`) và Admins mới có thể mở Control Panel.", parse_mode="Markdown")
        return

    is_owner = admin_store.is_owner(user_id)
    role_str = "👑 **OWNER** (Chủ sở hữu hệ thống)" if is_owner else "⭐ **ADMIN** (Quản trị viên)"

    uptime = str(datetime.now() - BOT_START_TIME).split(".")[0]
    users_dict = user_store.load_users()
    total_users = len(users_dict)
    total_admins = len(admin_store.load_admins())

    import platform
    sys_info = f"{platform.system()} {platform.release()} ({platform.machine()})"
    
    total_bytes = sum(f.stat().st_size for f in DOWNLOAD_DIR.glob("*") if f.is_file())
    total_bytes += sum(f.stat().st_size for f in SCREENSHOT_DIR.glob("*") if f.is_file())
    mb_used = round(total_bytes / (1024 * 1024), 2)

    panel_text = (
        f"🛠️ **DASHBOARD QUẢN TRỊ SERVER (ADMIN CONTROL PANEL)**\n\n"
        f"• 👤 **Vai trò của bạn**: {role_str}\n"
        f"• 🆔 **Telegram User ID**: `{user_id}`\n"
        f"• 💻 **Hệ điều hành Host**: `{sys_info}`\n"
        f"• ⏱ **Thời gian chạy Bot (Uptime)**: `{uptime}`\n"
        f"• 👥 **Tài khoản sinh viên đã lưu**: `{total_users}` MSV accounts (`{total_admins}` Admins)\n"
        f"• 💾 **Dung lượng Cache tạm**: `{mb_used} MB`\n"
        f"• ⚙️ **Auto Check Job**: {'✅ Đang hoạt động' if state_db.is_auto_check_enabled() else '❌ Đã tắt'}\n\n"
        f"👇 **Chọn thao tác quản trị từ menu điều khiển bên dưới:**"
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            panel_text, parse_mode="Markdown", reply_markup=get_admin_menu_keyboard(user_id)
        )
    elif msg:
        await msg.reply_text(
            panel_text, parse_mode="Markdown", reply_markup=get_admin_menu_keyboard(user_id)
        )


# Command: /exec <command> (Run shell command on server host)
async def exec_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = str(update.effective_user.id)

    if not admin_store.is_admin(user_id):
        if msg:
            await msg.reply_text("⛔ **BẠN KHÔNG CÓ QUYỀN THỰC THI SHELL!**", parse_mode="Markdown")
        return

    if not context.args:
        if msg:
            await msg.reply_text("⚠️ **Cú pháp**: `/exec <câu_lệnh_shell>` (Ví dụ: `/exec df -h` hoặc `/exec uptime`)", parse_mode="Markdown")
        return

    cmd_str = " ".join(context.args)
    status_msg = await msg.reply_text(f"💻 **Đang thực thi lệnh shell**: `{cmd_str}`...", parse_mode="Markdown")

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        out_text = stdout.decode("utf-8", errors="ignore").strip()
        err_text = stderr.decode("utf-8", errors="ignore").strip()

        result_lines = [
            f"💻 **KẾT QUẢ THỰC THI SHELL** (`exit_code={proc.returncode}`)\n",
            f"📥 **Lệnh**: `{cmd_str}`\n"
        ]
        if out_text:
            result_lines.append(f"```text\n{out_text[:3500]}\n```")
        if err_text:
            result_lines.append(f"⚠️ **Stderr**:\n```text\n{err_text[:1000]}\n```")

        await status_msg.edit_text("\n".join(result_lines), parse_mode="Markdown")
    except Exception as ex:
        await status_msg.edit_text(f"❌ **Lỗi thực thi shell**: {ex}", parse_mode="Markdown")


# Command: /addadmin <id> (Owner only)
async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = str(update.effective_user.id)

    if not admin_store.is_owner(user_id):
        if msg:
            await msg.reply_text("⛔ **Chỉ OWNER (ID: `5158297014`) mới có quyền thêm Admin mới!**", parse_mode="Markdown")
        return

    if not context.args:
        if msg:
            await msg.reply_text("⚠️ **Cú pháp**: `/addadmin <telegram_user_id>`", parse_mode="Markdown")
        return

    target_id = context.args[0].strip()
    if admin_store.add_admin(target_id):
        await msg.reply_text(f"✅ **Đã thêm User ID `{target_id}` làm ADMIN thành công!**", parse_mode="Markdown")
    else:
        await msg.reply_text(f"❌ Thất bại khi thêm Admin ID `{target_id}`.", parse_mode="Markdown")


# Command: /deladmin <id> (Owner only)
async def del_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = str(update.effective_user.id)

    if not admin_store.is_owner(user_id):
        if msg:
            await msg.reply_text("⛔ **Chỉ OWNER mới có quyền xóa Admin!**", parse_mode="Markdown")
        return

    if not context.args:
        if msg:
            await msg.reply_text("⚠️ **Cú pháp**: `/deladmin <telegram_user_id>`", parse_mode="Markdown")
        return

    target_id = context.args[0].strip()
    if admin_store.remove_admin(target_id):
        await msg.reply_text(f"✅ **Đã xóa Admin User ID `{target_id}` thành công!**", parse_mode="Markdown")
    else:
        await msg.reply_text(f"❌ Không thể xóa Admin ID `{target_id}` (Owner không thể bị xóa).", parse_mode="Markdown")


# Command: /adminlist
async def admin_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = str(update.effective_user.id)

    if not admin_store.is_admin(user_id):
        if msg:
            await msg.reply_text("⛔ **BẠN KHÔNG CÓ QUYỀN VÀO TRANG NÀY!**", parse_mode="Markdown")
        return

    admins = admin_store.load_admins()
    lines = ["👑 **DANH SÁCH OWNER & ADMINS HỆ THỐNG**\n"]
    for a_id in admins:
        role = "👑 Owner (Chủ sở hữu)" if a_id == admin_store.owner_id else "⭐ Admin"
        lines.append(f"• Telegram User ID: `{a_id}` ({role})")

    await msg.reply_text("\n".join(lines), parse_mode="Markdown")


# Command: /broadcast <message>
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user_id = str(update.effective_user.id)

    if not admin_store.is_admin(user_id):
        if msg:
            await msg.reply_text("⛔ **BẠN KHÔNG CÓ QUYỀN BROADCAST!**", parse_mode="Markdown")
        return

    if not context.args:
        if msg:
            await msg.reply_text("⚠️ **Cú pháp**: `/broadcast <nội_dung_thông_báo>`", parse_mode="Markdown")
        return

    broadcast_text = "📢 **THÔNG BÁO TỪ QUẢN TRỊ VIÊN BOT ELIT HUBT**\n\n" + " ".join(context.args)
    users = user_store.load_users()

    sent_count = 0
    fail_count = 0
    status_msg = await msg.reply_text(f"⏳ Đang gửi thông báo tới `{len(users)}` người dùng...", parse_mode="Markdown")

    for uid, udata in users.items():
        chat_id = udata.get("chat_id") or uid
        try:
            await context.bot.send_message(chat_id=chat_id, text=broadcast_text, parse_mode="Markdown")
            sent_count += 1
        except Exception as ex:
            fail_count += 1
            logger.warning(f"Could not send broadcast to chat {chat_id}: {ex}")

    await status_msg.edit_text(
        f"✅ **ĐÃ GỬI BROADCAST HOÀN TẤT!**\n\n"
        f"• Gửi thành công: `{sent_count}` chat\n"
        f"• Thất bại/Khóa bot: `{fail_count}` chat",
        parse_mode="Markdown",
    )


# Command: /login <msv> <pass> OR /login <token>
async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    user = update.effective_user
    user_id = str(user.id)
    username = user.username or user.first_name or user_id

    # Security: Delete user message containing credentials/tokens immediately
    try:
        await msg.delete()
        logger.info(f"Deleted user login message for security in chat {chat_id}")
    except Exception as e:
        logger.warning(f"Could not delete login message: {e}")

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "⚠️ **Cú pháp chưa đúng!**\n"
                "• Đăng nhập bằng MSV & Mật khẩu: `/login <Mã_Sinh_Viên> <Mật_Khẩu>`\n"
                "• Đăng nhập bằng Token Session: `/login <MoodleSession_Token>`"
            ),
            parse_mode="Markdown",
        )
        return

    scr, mgr = get_user_scraper(user_id)

    # Option A: Single argument -> Direct MoodleSession Token Login
    if len(context.args) == 1:
        token_input = context.args[0].strip()
        status_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔑 **Đang khởi tạo Session từ Token `{token_input[:8]}...`...**",
            parse_mode="Markdown",
        )
        if mgr.create_session_from_token(token_input):
            existing_user = user_store.get_user(user_id) or {}
            user_store.save_user(
                user_id=user_id,
                msv=existing_user.get("msv", "TokenUser"),
                password="",
                chat_id=chat_id,
                username=username,
                token=token_input,
            )
            await status_msg.edit_text(
                f"✅ **ĐÃ NẠP TOKEN SESSION THÀNH CÔNG!**\n\n"
                f"• **Telegram User**: @{username} (`{user_id}`)\n"
                f"• **Token Session**: `{token_input[:8]}...{token_input[-6:]}`\n"
                f"• Session cookies & Token đã lưu trữ an toàn cho bạn!\n"
                f"Bây giờ bạn có thể dùng `/check` để kiểm tra bài tập!",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard(user_id),
            )
        else:
            await status_msg.edit_text("❌ Không thể nạp Session từ Token này. Vui lòng kiểm tra lại.", parse_mode="Markdown")
        return

    # Option B: Two arguments -> MSV & Password Full Login
    msv = context.args[0]
    password = context.args[1]

    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔒 **Đang đăng nhập vào ELit HUBT LMS cho MSV `{msv}`...**\n*(Tin nhắn chứa mật khẩu đã được xóa an toàn)*",
        parse_mode="Markdown",
    )

    res = await scr.login(msv, password)
    success = res[0]
    result_msg = res[1]
    token = res[2] if len(res) > 2 else ""

    if success:
        user_store.save_user(user_id=user_id, msv=msv, password=password, chat_id=chat_id, username=username)
        await status_msg.edit_text(
            f"✅ **ĐĂNG NHẬP THÀNH CÔNG!**\n\n"
            f"• **Telegram User**: @{username} (`{user_id}`)\n"
            f"• **MSV**: `{msv}`\n"
            f"• Session cookies đã lưu an toàn cho tài khoản của bạn.\n"
            f"Bây giờ bạn có thể dùng `/check` để xem bài tập!",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(),
        )
    else:
        await status_msg.edit_text(
            f"❌ **ĐĂNG NHẬP THẤT BẠI**\n\n{result_msg}\n\nVui lòng thử lại với lệnh `/login <msv> <pass>`.",
            parse_mode="Markdown",
        )


# Command: /check
async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = str(update.effective_user.id)
    status_msg = await context.bot.send_message(
        chat_id=chat_id,
        text="🔍 **Đang quét lịch học và bài tập chưa nộp hôm nay...**\n*(Vui lòng chờ trong giây lát)*",
        parse_mode="Markdown",
    )

    try:
        has_sess, scr = await ensure_user_session(user_id)
        if not has_sess:
            await status_msg.edit_text(
                "⚠️ **Chưa đăng nhập tài khoản ELit HUBT!**\nVui lòng gửi lệnh `/login <msv> <matkhau>` để tiếp tục.",
                parse_mode="Markdown",
            )
            return

        assignments = await scr.check_today_classes_and_assignments()
        state_db.update_last_check()

        unsubmitted = [a for a in assignments if not a.get("is_submitted")]

        if not assignments:
            await status_msg.edit_text(
                "✅ **Hiện tại không tìm thấy bài tập nào trong các lớp học đang diễn ra.**",
                parse_mode="Markdown",
                reply_markup=get_main_menu_keyboard(),
            )
            return

        await status_msg.edit_text(
            f"📊 **KẾT QUẢ QUÉT LMS ELIT HUBT**\n"
            f"• Tổng số bài tập tìm thấy: `{len(assignments)}`\n"
            f"• Số bài tập CHƯA NỘP: `{len(unsubmitted)}`\n",
            parse_mode="Markdown",
        )

        for assign in assignments:
            assign_id = assign["assignment_id"]
            state_db.mark_assignment_seen(assign_id, assign)

            status_icon = "✅ Đã nộp" if assign["is_submitted"] else "❌ Chưa nộp"
            status_desc = assign.get("status", "")
            status_line = f"{status_icon} (`{status_desc}`)" if status_desc else status_icon

            lines = [
                f"📌 **BÀI TẬP #{assign_id}**",
                f"📘 **Môn học**: {assign['course_name']}",
                f"📝 **Tiêu đề**: {assign['title']}",
                f"📊 **Trạng thái bài nộp**: {status_line}",
            ]
            if assign.get("grading_status"):
                lines.append(f"💯 **Trạng thái chấm điểm**: {assign['grading_status']}")
            if assign.get("time_remaining"):
                lines.append(f"⏳ **Thời gian còn lại**: {assign['time_remaining']}")
            if assign.get("last_modified"):
                lines.append(f"🕒 **Chỉnh sửa lần cuối**: {assign['last_modified']}")

            lines.append(f"🔗 [Mở bài tập trên ELit]({assign['url']})\n")
            lines.append(f"📄 **Yêu cầu bài tập**:\n{assign['description'][:500]}\n")

            message_text = "\n".join(lines)

            # Action buttons
            button_row = []
            if not assign["is_submitted"] and assign.get("attached_links"):
                button_row.append(
                    InlineKeyboardButton("📥 Tải đề bài", callback_data=f"download_materials:{assign_id}")
                )
            button_row.append(
                InlineKeyboardButton("💡 Gợi ý AI", callback_data=f"ai_solve:{assign_id}")
            )
            if assign["is_submitted"]:
                button_row.append(
                    InlineKeyboardButton("🗑️ Xóa bài đã nộp", callback_data=f"remove_{assign_id}")
                )
            else:
                button_row.append(
                    InlineKeyboardButton("📤 Nộp bài", callback_data=f"submit_help:{assign_id}")
                )

            buttons = [button_row]

            await context.bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
                reply_markup=InlineKeyboardMarkup(buttons),
            )

    except SessionExpiredException:
        await status_msg.edit_text(
            "⚠️ **Session đăng nhập đã hết hạn hoặc chưa khởi tạo!**\n"
            "Vui lòng gửi lại lệnh `/login <msv> <matkhau>` để tiếp tục.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error executing /check: {e}")
        await status_msg.edit_text(
            f"❌ **Xảy ra lỗi khi quét dữ liệu**: {str(e)}", parse_mode="Markdown"
        )


# Command: /solve [assignment_id]
async def solve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    chat_id = update.effective_chat.id
    assign_id = None

    if context.args:
        assign_id = context.args[0]
    elif msg and msg.reply_to_message:
        match = re.search(r"BÀI TẬP #(\d+)", msg.reply_to_message.text or msg.reply_to_message.caption or "")
        if match:
            assign_id = match.group(1)

    if not assign_id:
        if msg:
            await msg.reply_text(
                "⚠️ Vui lòng cung cấp Assignment ID! Ví dụ: `/solve 12345` hoặc reply tin nhắn bài tập.",
                parse_mode="Markdown",
            )
        return

    logger.info(f"🤖 [AI ASSISTANT] Triggered solve_assignment_file for Assignment #{assign_id}")

    status_msg = await msg.reply_text(
        "⏳ **AI đang đọc đề bài, thực thi công thức và tạo file bài làm...**",
        parse_mode="Markdown",
    )

    # Automatically download assignment material files from Moodle if not fetched yet
    material_files = []
    try:
        material_files = await scraper.download_assignment_materials(assign_id)
    except Exception as ex:
        logger.warning(f"Note downloading materials for #{assign_id}: {ex}")

    attached_files = list(set(list(DOWNLOAD_DIR.glob(f"Assign_{assign_id}_*")) + list(DOWNLOAD_DIR.glob(f"*{assign_id}*")) + material_files))
    attached_file_strs = [str(f) for f in attached_files]

    student_info = {"name": "Trần Tuấn Minh", "id": "16T-Tin3"}

    # Execute Universal Multi-Format AI Solver workflow
    success, out_path_or_err, summary_caption = await ai_helper.solve_assignment_file(
        file_paths=attached_file_strs, assignment_id=assign_id, student_info=student_info
    )

    if not success or not out_path_or_err:
        await status_msg.edit_text(f"❌ **Lỗi khi AI tự động giải bài tập**: {out_path_or_err}", parse_mode="Markdown")
        return

    out_file = Path(out_path_or_err)
    submit_btn = InlineKeyboardMarkup([[InlineKeyboardButton("📤 Nộp file bài làm này lên ELit ngay", callback_data=f"auto_submit_completed:{assign_id}")]])

    # Send generated ready-to-submit .xlsx / .docx file
    if out_file.exists():
        with open(out_file, "rb") as f:
            try:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(f, filename=out_file.name),
                    caption=summary_caption,
                    parse_mode="Markdown",
                    reply_markup=submit_btn,
                )
            except Exception as ex:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(f, filename=out_file.name),
                    caption=f"✨ ĐÃ GIẢI XONG BÀI TẬP #{assign_id}\n📎 File bài làm dạng {out_file.suffix} đã được tạo tự động sẵn sàng nộp bài!",
                    parse_mode=None,
                    reply_markup=submit_btn,
                )

    # ALSO check and send accompanying PDF Word solution document if generated
    pdf_word_solution = DOWNLOAD_DIR / f"Loi_Giai_Chi_Tiet_PDF_Assignment_{assign_id}.docx"
    if pdf_word_solution.exists():
        try:
            with open(pdf_word_solution, "rb") as f_doc:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=InputFile(f_doc, filename=pdf_word_solution.name),
                    caption=f"📄 **FILE LỜI GIẢI CHI TIẾT ĐỀ BÀI PDF (#`{assign_id}`)**\n\nFile Word đính kèm chứa toàn bộ bài giải lý thuyết, các bước tính toán và hướng dẫn cho file PDF đề bài!",
                    parse_mode="Markdown",
                )
        except Exception as ex_word:
            logger.warning(f"Error sending PDF Word solution file: {ex_word}")

    try:
        await status_msg.delete()
    except Exception:
        pass

    logger.info(f"🎉 [AI ASSISTANT] Successfully executed end-to-end AI file solver for Assignment #{assign_id}")

    logger.info(f"🎉 [AI ASSISTANT] Delivered all solution text & files for Assignment #{assign_id}")


# Command: /status
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = str(datetime.now() - BOT_START_TIME).split(".")[0]
    has_session = session_mgr.has_session()
    session_str = "✅ Hợp lệ (session.json)" if has_session else "❌ Chưa đăng nhập / Hết hạn"

    # Calculate storage size
    total_download_files = len(list(DOWNLOAD_DIR.glob("*")))
    total_screenshots = len(list(SCREENSHOT_DIR.glob("*")))
    
    total_bytes = sum(f.stat().st_size for f in DOWNLOAD_DIR.glob("*") if f.is_file())
    total_bytes += sum(f.stat().st_size for f in SCREENSHOT_DIR.glob("*") if f.is_file())
    mb_used = round(total_bytes / (1024 * 1024), 2)

    auto_check_status = "✅ Bật" if state_db.is_auto_check_enabled() else "❌ Tắt"
    last_check = state_db.get_last_check() or "Chưa kiểm tra"

    text = (
        f"📊 **TRẠNG THÁI HỆ THỐNG BOT ELIT HUBT**\n\n"
        f"• ⏱ **Thời gian hoạt động**: `{uptime}`\n"
        f"• 🔑 **Trạng thái Session**: {session_str}\n"
        f"• ⚙️ **Auto Check Cronjob**: {auto_check_status} (mỗi {CHECK_INTERVAL_MINUTES} phút)\n"
        f"• 🕒 **Lần quét gần nhất**: `{last_check}`\n"
        f"• 📚 **Số bài tập đã ghi nhận**: `{state_db.get_seen_count()}`\n"
        f"• 💾 **Dung lượng lưu trữ tạm**: `{mb_used} MB` ({total_download_files} file đính kèm, {total_screenshots} ảnh chụp)\n"
    )

    await update.message.reply_text(
        text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard()
    )


# Command: /logout
async def logout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    session_mgr.clear_session()
    
    # Clean up downloads and screenshots
    for f in DOWNLOAD_DIR.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass
    for f in SCREENSHOT_DIR.glob("*"):
        try:
            f.unlink()
        except Exception:
            pass

    await update.message.reply_text(
        "🔒 **Đã đăng xuất thành công!**\nSession file và các dữ liệu tải tạm đã được xóa sạch.",
        parse_mode="Markdown",
    )


# Helper: Process submission once all files are collected
async def process_submission(bot, chat_id, documents, caption, reply_msg, msg):
    # Extract target assignment ID
    assign_id = None

    # Strategy 1: Explicit /submit <id> or submit <id>
    match_cmd = re.search(r"(?:/)?submit\s+(\d+)", caption, re.IGNORECASE)
    if match_cmd:
        assign_id = match_cmd.group(1)

    # Strategy 2: Look for 5 to 7 digit assignment ID in caption (e.g. 119340)
    if not assign_id:
        match_id = re.search(r"\b(\d{5,7})\b", caption)
        if match_id:
            assign_id = match_id.group(1)

    # Strategy 3: Check replied message for assignment ID
    if not assign_id and reply_msg:
        replied_text = (reply_msg.text or "") + " " + (reply_msg.caption or "")
        match_reply = (
            re.search(r"BÀI TẬP #(\d+)", replied_text)
            or re.search(r"Assignment #(\d+)", replied_text)
            or re.search(r"\b(\d{5,7})\b", replied_text)
        )
        if match_reply:
            assign_id = match_reply.group(1)

    if not assign_id:
        await msg.reply_text(
            "⚠️ **Chưa xác định được ID bài tập cần nộp!**\n"
            "Vui lòng gửi file kèm caption: `/submit <ID_Bài_Tập>` (ví dụ: `/submit 119340`) hoặc **reply trực tiếp** vào tin nhắn bài tập của Bot.",
            parse_mode="Markdown",
        )
        return

    # Create submission folder preserving original filenames
    sub_dir = DOWNLOAD_DIR / f"sub_{assign_id}_{int(time.time())}"
    sub_dir.mkdir(parents=True, exist_ok=True)

    status_msg = await msg.reply_text(
        f"⏳ **Đang tải {len(documents)} file xuống server và chuẩn bị nộp cho Bài tập #{assign_id}...**",
        parse_mode="Markdown",
    )

    try:
        local_file_paths = []
        file_names = []
        for doc in documents:
            file_obj = await bot.get_file(doc.file_id)
            original_name = getattr(doc, "file_name", f"submission_{assign_id}.pdf")
            local_path = sub_dir / original_name
            await file_obj.download_to_drive(custom_path=local_path)
            local_file_paths.append(str(local_path))
            file_names.append(original_name)
            logger.info(f"Downloaded user document to {local_path}")

        file_list_str = "\n".join([f"• `{name}`" for name in file_names])

        await status_msg.edit_text(
            f"🌐 **Đang mở Moodle để nộp {len(local_file_paths)} file cho Bài tập #{assign_id}...**\n\n{file_list_str}",
            parse_mode="Markdown",
        )

        # Execute submission workflow in Playwright
        success, sub_msg, screenshot_path = await scraper.submit_assignment(
            assignment_id=assign_id, file_paths=local_file_paths
        )

        if success:
            remove_button = InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ Xóa bài làm đã nộp", callback_data=f"remove_{assign_id}")]])
            await status_msg.edit_text(
                f"🎉 **NỘP BÀI TẬP #{assign_id} THÀNH CÔNG!**\n\n"
                f"• **Số lượng file**: `{len(local_file_paths)}`\n"
                f"• **Danh sách file**:\n{file_list_str}\n\n"
                f"• **Chi tiết**: {sub_msg}",
                parse_mode="Markdown",
                reply_markup=remove_button,
            )

            if screenshot_path and screenshot_path.exists():
                with open(screenshot_path, "rb") as f:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=InputFile(f),
                        caption=f"📸 **Xác nhận trạng thái nộp {len(local_file_paths)} file lên ELit HUBT cho Bài tập #{assign_id}**",
                        reply_markup=remove_button,
                    )
        else:
            await status_msg.edit_text(
                f"❌ **NỘP BÀI THẤT BẠI**\n\n{sub_msg}", parse_mode="Markdown"
            )

    except SessionExpiredException:
        await status_msg.edit_text(
            "⚠️ **Session hết hạn trong quá trình nộp bài!** Vui lòng gửi `/login <msv> <matkhau>` để cập nhật cookie.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Error handling file upload submission: {e}")
        await status_msg.edit_text(
            f"❌ **Lỗi trong quá trình nộp bài**: {str(e)}", parse_mode="Markdown"
        )


# Global Media Group Collector for Multi-file Submissions
MEDIA_GROUPS = {}
RECENT_MEDIA_GROUPS = {}


# Document & File Upload Listener (For assignment submission)
async def file_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    # Check for document or photo
    document = msg.document
    if not document and msg.photo:
        document = msg.photo[-1]

    if not document:
        return

    media_group_id = msg.media_group_id

    if media_group_id:
        if media_group_id not in MEDIA_GROUPS:
            MEDIA_GROUPS[media_group_id] = {
                "docs": [],
                "captions": [],
                "reply_msgs": [],
                "msg": msg,
                "task": None,
            }

        if media_group_id not in RECENT_MEDIA_GROUPS:
            RECENT_MEDIA_GROUPS[media_group_id] = []

        doc_uids = [d.file_unique_id for d in MEDIA_GROUPS[media_group_id]["docs"] if hasattr(d, "file_unique_id")]
        if not hasattr(document, "file_unique_id") or document.file_unique_id not in doc_uids:
            MEDIA_GROUPS[media_group_id]["docs"].append(document)

        rec_uids = [d.file_unique_id for d in RECENT_MEDIA_GROUPS[media_group_id] if hasattr(d, "file_unique_id")]
        if not hasattr(document, "file_unique_id") or document.file_unique_id not in rec_uids:
            RECENT_MEDIA_GROUPS[media_group_id].append(document)

        if msg.caption:
            MEDIA_GROUPS[media_group_id]["captions"].append(msg.caption)
        if msg.reply_to_message:
            MEDIA_GROUPS[media_group_id]["reply_msgs"].append(msg.reply_to_message)

        # Cancel existing timer task for this media group so we wait 1.5s AFTER the last item arrives
        prev_task = MEDIA_GROUPS[media_group_id]["task"]
        if prev_task and not prev_task.done():
            prev_task.cancel()

        async def delayed_process(mg_id):
            try:
                await asyncio.sleep(1.5)
                data = MEDIA_GROUPS.pop(mg_id, None)
                if data:
                    await process_submission(
                        bot=context.bot,
                        chat_id=data["msg"].chat_id,
                        documents=data["docs"],
                        caption=" ".join(data["captions"]),
                        reply_msg=data["reply_msgs"][0] if data["reply_msgs"] else None,
                        msg=data["msg"],
                    )
            except asyncio.CancelledError:
                pass
            except Exception as ex:
                logger.error(f"Error in delayed_process for media group {mg_id}: {ex}")

        MEDIA_GROUPS[media_group_id]["task"] = asyncio.create_task(delayed_process(media_group_id))

    else:
        # Single document upload
        await process_submission(
            bot=context.bot,
            chat_id=msg.chat_id,
            documents=[document],
            caption=msg.caption or "",
            reply_msg=msg.reply_to_message,
            msg=msg,
        )


# Command: /submit [assignment_id] (Allows replying to a message containing files)
async def submit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    reply_msg = msg.reply_to_message
    caption = msg.caption or msg.text or ""

    # Strategy A: Extract assignment ID from command args
    assign_id = context.args[0] if context.args else None

    # Strategy B: Extract assignment ID from caption or command text
    if not assign_id:
        match_cmd = re.search(r"(?:/)?submit\s+(\d+)", caption, re.IGNORECASE)
        if match_cmd:
            assign_id = match_cmd.group(1)

    if not assign_id:
        match_id = re.search(r"\b(\d{5,7})\b", caption)
        if match_id:
            assign_id = match_id.group(1)

    # Strategy C: Extract assignment ID from replied message
    if not assign_id and reply_msg:
        replied_text = (reply_msg.text or "") + " " + (reply_msg.caption or "")
        match_reply = (
            re.search(r"BÀI TẬP #(\d+)", replied_text)
            or re.search(r"Assignment #(\d+)", replied_text)
            or re.search(r"\b(\d{5,7})\b", replied_text)
        )
        if match_reply:
            assign_id = match_reply.group(1)

    # Gather documents from reply or current message (check if reply belongs to an Album!)
    documents = []
    if reply_msg:
        rep_media_group_id = getattr(reply_msg, "media_group_id", None)
        if rep_media_group_id and rep_media_group_id in RECENT_MEDIA_GROUPS:
            logger.info(f"Found media group {rep_media_group_id} with {len(RECENT_MEDIA_GROUPS[rep_media_group_id])} documents in cache!")
            documents.extend(RECENT_MEDIA_GROUPS[rep_media_group_id])
        else:
            if reply_msg.document:
                documents.append(reply_msg.document)
            elif reply_msg.photo:
                documents.append(reply_msg.photo[-1])

    if msg.document and msg.document not in documents:
        documents.append(msg.document)
    elif msg.photo and msg.photo[-1] not in documents:
        documents.append(msg.photo[-1])

    if not documents:
        await msg.reply_text(
            "⚠️ **Không tìm thấy file đính kèm!** Vui lòng reply trực tiếp vào tin nhắn chứa file bài làm.",
            parse_mode="Markdown",
        )
        return

    # Call core process_submission with gathered documents and assignment_id
    await process_submission(
        bot=context.bot,
        chat_id=msg.chat_id,
        documents=documents,
        caption=f"/submit {assign_id}" if assign_id else caption,
        reply_msg=reply_msg,
        msg=msg,
    )


# Callback Query Handler for Interactive Inline Keyboards
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    chat_id = query.message.chat_id
    user_id = str(update.effective_user.id)

    if data == "menu_start":
        await start_command(update, context)

    elif data == "menu_check":
        await check_command(update, context)

    elif data == "menu_help":
        await help_command(update, context)

    elif data == "menu_whoami":
        await whoami_command(update, context)

    elif data == "menu_status":
        await status_command(update, context)

    elif data == "menu_admin_panel":
        await admin_command(update, context)

    elif data == "admin_clear_cache":
        if not admin_store.is_admin(user_id):
            await query.answer("⛔ Bạn không phải Admin!", show_alert=True)
            return

        cleared_count = 0
        for f in list(DOWNLOAD_DIR.glob("*")) + list(SCREENSHOT_DIR.glob("*")):
            if f.is_file() and not f.name.endswith(".json") and f.name != "submitted_jobs.json":
                try:
                    f.unlink()
                    cleared_count += 1
                except Exception:
                    pass

        await query.edit_message_text(
            f"🧹 **ĐÃ DỌN DẸP CACHE THÀNH CÔNG!**\n\n"
            f"• Số lượng file tạm đã xóa: `{cleared_count}` file.\n"
            f"Bộ nhớ đĩa server host đã được tối ưu sạch sẽ.",
            parse_mode="Markdown",
            reply_markup=get_admin_menu_keyboard(user_id),
        )

    elif data == "admin_user_list":
        if not admin_store.is_admin(user_id):
            await query.answer("⛔ Bạn không phải Admin!", show_alert=True)
            return

        users = user_store.load_users()
        lines = [f"👥 **DANH SÁCH {len(users)} TÀI KHOẢN ĐÃ ĐĂNG NHẬP**\n"]
        for uid, udata in users.items():
            msv = udata.get("msv", "N/A")
            uname = udata.get("username", "N/A")
            lines.append(f"• User ID `{uid}` (@{uname}): MSV `{msv}`")

        await query.edit_message_text(
            "\n".join(lines[:30]),
            parse_mode="Markdown",
            reply_markup=get_admin_menu_keyboard(user_id),
        )

    elif data == "admin_exec_help":
        if not admin_store.is_admin(user_id):
            await query.answer("⛔ Bạn không phải Admin!", show_alert=True)
            return

        await query.message.reply_text(
            "💻 **HƯỚNG DẪN THỰC THI TERMINAL SHELL**\n\n"
            "Gửi tin nhắn theo cú pháp:\n"
            "`/exec <câu_lệnh_shell>`\n\n"
            "Ví dụ:\n"
            "• `/exec df -h` (Kiểm tra dung lượng ổ đĩa)\n"
            "• `/exec uptime` (Xem thời gian Server hoạt động)\n"
            "• `/exec ps aux | grep python` (Xem các tiến trình đang chạy)\n"
            "• `/exec ls -lh downloads` (Xem file đính kèm)",
            parse_mode="Markdown",
        )

    elif data == "admin_broadcast_help":
        if not admin_store.is_admin(user_id):
            await query.answer("⛔ Bạn không phải Admin!", show_alert=True)
            return

        await query.message.reply_text(
            "📢 **HƯỚNG DẪN GỬI THÔNG BÁO TỚI TOÀN BỘ USER (BROADCAST)**\n\n"
            "Gửi tin nhắn theo cú pháp:\n"
            "`/broadcast <nội_dung_thông_báo>`\n\n"
            "Ví dụ: `/broadcast Bot vừa được cập nhật tính năng AI giải bài tập mới!`",
            parse_mode="Markdown",
        )

    elif data == "admin_list_roles":
        await admin_list_command(update, context)

    elif data == "menu_toggle_autocheck":
        new_state = state_db.toggle_auto_check()
        status_str = "✅ ĐÃ BẬT" if new_state else "❌ ĐÃ TẮT"
        await query.edit_message_text(
            f"⚙️ **Cài đặt Tự động Quét (Auto Check)**: {status_str}\n"
            f"Hệ thống sẽ {'tự động quét bài tập mỗi 30 phút.' if new_state else 'ngừng tự động quét trong background.'}",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(user_id),
        )

    elif data == "menu_login_help":
        await query.edit_message_text(
            "🔑 **HƯỚNG DẪN ĐĂNG NHẬP**\n\n"
            "Vui lòng gửi lệnh theo cú pháp:\n"
            "`/login <Mã_Sinh_Viên> <Mật_Khẩu>`\n\n"
            "Ví dụ: `/login 16T12345 matkhau123`\n"
            "*(Bot sẽ tự động xóa tin nhắn chứa mật khẩu để bảo vệ tài khoản)*",
            parse_mode="Markdown",
        )

    elif data.startswith("download_materials:"):
        assign_id = data.split(":")[1]
        msg = await query.message.reply_text(f"⏳ Đang tải file đề bài đính kèm cho Bài tập #{assign_id}...")
        try:
            files = await scraper.download_assignment_materials(assign_id)
            if not files:
                await msg.edit_text(f"⚠️ Không tải được file đề bài nào cho Bài tập #{assign_id}.")
            else:
                await msg.edit_text(f"✅ Đã tải thành công `{len(files)}` file đề bài vào thư mục downloads.")
                for fpath in files:
                    with open(fpath, "rb") as f_doc:
                        await context.bot.send_document(
                            chat_id=chat_id,
                            document=InputFile(f_doc, filename=fpath.name),
                            caption=f"📎 **File đề bài đính kèm**: `{fpath.name}` (Bài tập #{assign_id})",
                            parse_mode="Markdown",
                        )
        except Exception as e:
            logger.error(f"Error downloading materials via button: {e}")
            await msg.edit_text(f"❌ Lỗi khi tải file đề bài: {e}")

    elif data.startswith("ai_solve:"):
        assign_id = data.split(":")[1]
        context.args = [assign_id]
        await solve_command(update, context)

    elif data.startswith("submit_help:"):
        assign_id = data.split(":")[1]
        await query.message.reply_text(
            f"📤 **HƯỚNG DẪN NỘP BÀI CHO BÀI TẬP #{assign_id}**\n\n"
            f"Vui lòng gửi file bài làm (`.pdf`, `.docx`, `.xlsx`, `.zip`) trực tiếp vào Chat này kèm caption: `/submit {assign_id}` hoặc reply tin nhắn này.",
            parse_mode="Markdown",
        )

    elif data.startswith("auto_submit_completed:"):
        assign_id = data.split(":")[1]
        completed_file = DOWNLOAD_DIR / f"ExBai2_TrầnTuấnMinh.xlsx"
        if not completed_file.exists():
            matched_files = list(DOWNLOAD_DIR.glob(f"*{assign_id}*.xlsx")) + list(DOWNLOAD_DIR.glob("ExBai2_*.xlsx"))
            if matched_files:
                completed_file = matched_files[0]

        if not completed_file.exists():
            await query.message.reply_text(f"⚠️ Không tìm thấy file bài làm đã giải cho Bài tập #{assign_id}. Vui lòng dùng lệnh `/solve {assign_id}` trước.")
            return

        status_msg = await query.message.reply_text(f"⏳ **Đang tiến hành tự động nộp file `{completed_file.name}` lên ELit HUBT...**")
        success, message = await scraper.submit_assignment(assign_id, [completed_file])
        if success:
            await status_msg.edit_text(f"🎉 **NỘP BÀI THÀNH CÔNG CHO BÀI TẬP #{assign_id}!**\n\n{message}", parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"❌ **NỘP BÀI THẤT BẠI FOR BÀI TẬP #{assign_id}**\n\n{message}", parse_mode="Markdown")

    elif data.startswith("remove_"):
        assign_id = data.split("_")[1]
        confirm_text = (
            f"⚠️ **XÁC NHẬN XÓA BÀI NỘP**\n\n"
            f"Bạn có chắc chắn muốn **XÓA BÀI NỘP** cho **Bài tập #{assign_id}** trên ELit HUBT không?\n"
            f"*(Hành động này sẽ loại bỏ dữ liệu bài làm đã tải lên trước đó trên Moodle)*"
        )
        buttons = [
            [
                InlineKeyboardButton("✅ Đồng ý Xóa", callback_data=f"confirm_remove_{assign_id}"),
                InlineKeyboardButton("❌ Hủy", callback_data="cancel_remove"),
            ]
        ]
        await query.message.reply_text(confirm_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))

    elif data.startswith("confirm_remove_"):
        assign_id = data.split("_")[2]
        status_msg = await query.message.reply_text(f"⏳ **Đang tiến hành xóa bài nộp cho Bài tập #{assign_id}...**")
        success, msg_result = await scraper.remove_submission(assign_id)
        if success:
            await status_msg.edit_text(f"✅ **ĐÃ XÓA BÀI NỘP THÀNH CÔNG!**\n\n{msg_result}", parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"❌ **XÓA BÀI NỘP THẤT BẠI**: {msg_result}", parse_mode="Markdown")

    elif data == "cancel_remove":
        await query.edit_message_text("❌ **Đã hủy thao tác xóa bài nộp.**", parse_mode="Markdown")


# Command: /remove [assignment_id] or /delete [assignment_id]
async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return

    reply_msg = msg.reply_to_message
    caption = msg.text or ""

    assign_id = context.args[0] if context.args else None

    if not assign_id:
        match_cmd = re.search(r"(?:/)?(?:remove|delete)\s+(\d+)", caption, re.IGNORECASE)
        if match_cmd:
            assign_id = match_cmd.group(1)

    if not assign_id and reply_msg:
        replied_text = (reply_msg.text or "") + " " + (reply_msg.caption or "")
        match_reply = (
            re.search(r"BÀI TẬP #(\d+)", replied_text)
            or re.search(r"Assignment #(\d+)", replied_text)
            or re.search(r"\b(\d{5,7})\b", replied_text)
        )
        if match_reply:
            assign_id = match_reply.group(1)

    if not assign_id:
        await msg.reply_text(
            "⚠️ **Chưa xác định được ID bài tập cần xóa!**\n"
            "Vui lòng dùng cú pháp: `/remove <ID_Bài_Tập>` (ví dụ: `/remove 119340`) hoặc reply tin nhắn thông báo bài tập.",
            parse_mode="Markdown",
        )
        return

    confirm_text = (
        f"⚠️ **XÁC NHẬN XÓA BÀI NỘP**\n\n"
        f"Bạn có chắc chắn muốn **XÓA BÀI NỘP** cho **Bài tập #{assign_id}** trên ELit HUBT không?\n"
        f"*(Hành động này sẽ loại bỏ dữ liệu bài làm đã tải lên trước đó trên Moodle)*"
    )
    buttons = [
        [
            InlineKeyboardButton("✅ Đồng ý Xóa", callback_data=f"confirm_remove_{assign_id}"),
            InlineKeyboardButton("❌ Hủy", callback_data="cancel_remove"),
        ]
    ]
    await msg.reply_text(confirm_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))


# Global Error Handler
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f"Handled network/bot loop exception: {context.error}")


# Background Job: Scheduled Auto Check
async def auto_check_job(context: ContextTypes.DEFAULT_TYPE):
    if not state_db.is_auto_check_enabled():
        return

    chat_id = DEFAULT_CHAT_ID
    if not chat_id:
        logger.debug("No DEFAULT_CHAT_ID configured for background auto check.")
        return

    logger.info("Executing background auto_check_job...")
    try:
        all_users = user_store.load_users()
        scrapers_to_run = []
        if all_users:
            for uid in all_users:
                has_sess, scr = await ensure_user_session(uid)
                if has_sess:
                    scrapers_to_run.append(scr)
        else:
            has_sess, scr = await ensure_user_session("default")
            if has_sess:
                scrapers_to_run.append(scr)

        for scr in scrapers_to_run:
            try:
                assignments = await scr.check_today_classes_and_assignments()
                state_db.update_last_check()

                new_unsubmitted = []
                for a in assignments:
                    assign_id = a["assignment_id"]
                    if not a.get("is_submitted") and not state_db.is_assignment_seen(assign_id):
                        new_unsubmitted.append(a)
                        state_db.mark_assignment_seen(assign_id, a)

                if new_unsubmitted:
                    logger.info(f"Background job found {len(new_unsubmitted)} new unsubmitted assignments!")
                    
                    for assign in new_unsubmitted:
                        assign_id = assign["assignment_id"]
                        alert_lines = [
                            "🚨 **CẢNH BÁO BÀI TẬP MỚI PHÁT HIỆN!**\n",
                            f"📌 **Bài tập #{assign_id}**",
                            f"📘 **Môn học**: {assign['course_name']}",
                            f"📝 **Tiêu đề**: {assign['title']}",
                            f"📊 **Trạng thái bài nộp**: ❌ Chưa nộp (`{assign.get('status', '')}`)",
                        ]
                        if assign.get("grading_status"):
                            alert_lines.append(f"💯 **Trạng thái chấm điểm**: {assign['grading_status']}")
                        if assign.get("time_remaining"):
                            alert_lines.append(f"⏳ **Thời gian còn lại**: {assign['time_remaining']}")
                        if assign.get("last_modified"):
                            alert_lines.append(f"🕒 **Chỉnh sửa lần cuối**: {assign['last_modified']}")

                        alert_lines.append(f"🔗 [Xem bài tập trên ELit]({assign['url']})\n")
                        alert_lines.append(f"📄 **Mô tả**:\n{assign['description'][:500]}\n")

                        alert_text = "\n".join(alert_lines)

                        button_row = []
                        if assign.get("attached_links"):
                            button_row.append(
                                InlineKeyboardButton("📥 Tải đề bài", callback_data=f"download_materials:{assign_id}")
                            )
                        button_row.append(InlineKeyboardButton("💡 Gợi ý AI", callback_data=f"ai_solve:{assign_id}"))
                        button_row.append(InlineKeyboardButton("📤 Nộp bài", callback_data=f"submit_help:{assign_id}"))

                        buttons = [button_row]

                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=alert_text,
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(buttons),
                        )
            except Exception as ex_single:
                logger.warning(f"Error checking assignments for scraper: {ex_single}")

    except SessionExpiredException:
        logger.warning("Session expired during background auto check job.")
    except Exception as e:
        logger.error(f"Error in auto_check_job: {e}")


async def post_init(application: Application):
    """Sets Telegram Bot Command List and Telegram Chat Menu Button."""
    bot = application.bot
    try:
        commands = [
            BotCommand("start", "Khởi chạy & Mở Menu chính"),
            BotCommand("help", "Xem bảng hướng dẫn chi tiết"),
            BotCommand("whoami", "Xem thông tin tài khoản đang chọn"),
            BotCommand("check", "Quét môn học & bài tập chưa nộp"),
            BotCommand("solve", "AI tự động giải bài tập PDF/Excel"),
            BotCommand("submit", "Nộp bài trực tiếp lên ELit HUBT"),
            BotCommand("login", "Đăng nhập tài khoản MSV HUBT"),
            BotCommand("admin", "Admin Control Panel Quản trị Server"),
            BotCommand("status", "Xem trạng thái hệ thống & Server"),
        ]
        await bot.set_my_commands(commands)
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Registered Telegram Bot Commands & Menu Button successfully!")
    except Exception as ex:
        logger.warning(f"Note setting Telegram Bot Commands: {ex}")


def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set in environment or config.py!")
        print("❌ Error: TELEGRAM_BOT_TOKEN is missing. Please set it in .env")
        return

    logger.info("Starting ELit HUBT Telegram Bot application...")

    # Build Bot Application with JobQueue and post_init
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Register Global Error Handler
    app.add_error_handler(global_error_handler)

    # Register Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", start_command))
    app.add_handler(CommandHandler(["help", "huongdan"], help_command))
    app.add_handler(CommandHandler(["whoami", "account"], whoami_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("check", check_command))
    app.add_handler(CommandHandler("submit", submit_command))
    app.add_handler(CommandHandler(["remove", "delete"], remove_command))
    app.add_handler(CommandHandler("solve", solve_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("logout", logout_command))
    app.add_handler(CommandHandler(["admin", "panel"], admin_command))
    app.add_handler(CommandHandler("exec", exec_command))
    app.add_handler(CommandHandler("addadmin", add_admin_command))
    app.add_handler(CommandHandler("deladmin", del_admin_command))
    app.add_handler(CommandHandler("adminlist", admin_list_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # Register Callback Query Handler
    app.add_handler(CallbackQueryHandler(button_callback_handler))

    # Register Document & File Handler
    app.add_handler(
        MessageHandler(filters.Document.ALL | filters.PHOTO, file_handler)
    )

    # Register Scheduled JobQueue for Auto Check
    if app.job_queue:
        interval_seconds = CHECK_INTERVAL_MINUTES * 60
        app.job_queue.run_repeating(
            auto_check_job, interval=interval_seconds, first=10
        )
        logger.info(f"JobQueue background scanner scheduled every {CHECK_INTERVAL_MINUTES} minutes.")

    # Start Bot Polling
    print("🚀 ELit HUBT Telegram Bot is now running!")
    app.run_polling()


if __name__ == "__main__":
    main()
