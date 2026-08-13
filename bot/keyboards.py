from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class BotKeyboards:
    @staticmethod
    def main_menu(user_id: str, is_admin: bool = False) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("🔍 Quét bài tập hôm nay", callback_data="btn_check"),
                InlineKeyboardButton("📊 Trạng thái hệ thống", callback_data="btn_status"),
            ],
            [
                InlineKeyboardButton("💡 Giải bài bằng AI", callback_data="btn_solve_help"),
                InlineKeyboardButton("👤 Thông tin tài khoản", callback_data="btn_whoami"),
            ],
        ]
        if is_admin:
            keyboard.append([
                InlineKeyboardButton("🛠️ Admin Dashboard", callback_data="btn_admin_panel"),
                InlineKeyboardButton("💻 Remote Shell (/bash)", callback_data="btn_bash_help"),
            ])
        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def back_to_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Quay về Menu chính", callback_data="btn_main_menu")]
        ])

    @staticmethod
    def status_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Làm mới", callback_data="btn_status"),
                InlineKeyboardButton("🔙 Quay về Menu chính", callback_data="btn_main_menu"),
            ]
        ])

    @staticmethod
    def admin_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🧹 Dọn rác VPS ngay", callback_data="btn_purge_cache"),
                InlineKeyboardButton("🔙 Quay về Menu chính", callback_data="btn_main_menu"),
            ]
        ])

    @staticmethod
    def assignment_action(assign_id: str, is_submitted: bool, owner_user_id: str) -> InlineKeyboardMarkup:
        row = []
        row.append(InlineKeyboardButton("📥 Tải đề bài", callback_data=f"download_materials:{assign_id}"))
        row.append(InlineKeyboardButton("💡 Gợi ý AI", callback_data=f"ai_solve:{assign_id}"))
        
        if is_submitted:
            row.append(InlineKeyboardButton("🗑️ Xóa bài nộp", callback_data=f"remove_{assign_id}_{owner_user_id}"))
        else:
            row.append(InlineKeyboardButton("📤 Nộp bài", callback_data=f"submit_help:{assign_id}"))
        return InlineKeyboardMarkup([row])

keyboards = BotKeyboards()
