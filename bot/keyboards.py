from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class BotKeyboards:
    @staticmethod
    def main_menu(user_id: str, is_admin: bool = False) -> InlineKeyboardMarkup:
        keyboard = [
            [
                InlineKeyboardButton("🔍 Quét bài tập hôm nay", callback_data="btn_check"),
                InlineKeyboardButton("📅 Tra cứu Thời khóa biểu", callback_data="btn_tkb_menu"),
            ],
            [
                InlineKeyboardButton("💡 Giải bài bằng AI", callback_data="btn_solve_help"),
                InlineKeyboardButton("📊 Trạng thái hệ thống", callback_data="btn_status"),
            ],
            [
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
    def schedule_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔍 Lớp mẫu TH30.10", callback_data="btn_tkb_quick:th30.10"),
                InlineKeyboardButton("🔍 Lớp mẫu TH30.01", callback_data="btn_tkb_quick:th30.01"),
            ],
            [
                InlineKeyboardButton("🔙 Quay về Menu chính", callback_data="btn_main_menu"),
            ]
        ])

    @staticmethod
    def schedule_result_menu(query: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Làm mới TKB", callback_data=f"btn_tkb_quick:{query}"),
                InlineKeyboardButton("🔙 Menu chính", callback_data="btn_main_menu"),
            ]
        ])

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
                InlineKeyboardButton("🐧 Neofetch", callback_data="btn_neofetch"),
                InlineKeyboardButton("⚡ Speedtest", callback_data="btn_speedtest"),
            ],
            [
                InlineKeyboardButton("🔙 Quay về Menu chính", callback_data="btn_main_menu"),
            ]
        ])

    @staticmethod
    def admin_menu() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🧹 Dọn rác VPS ngay", callback_data="btn_purge_cache"),
                InlineKeyboardButton("👥 Danh sách Admin", callback_data="btn_admin_list"),
            ],
            [
                InlineKeyboardButton("🔙 Quay về Menu chính", callback_data="btn_main_menu"),
            ]
        ])

    @staticmethod
    def assignment_action(assign_id: str, is_submitted: bool, owner_user_id: str, is_open: bool = True) -> InlineKeyboardMarkup:
        row = []
        row.append(InlineKeyboardButton("📥 Tải đề bài", callback_data=f"download_materials:{assign_id}"))
        row.append(InlineKeyboardButton("💡 Gợi ý AI", callback_data=f"ai_solve:{assign_id}"))
        
        if not is_open:
            row.append(InlineKeyboardButton("🔒 Chưa mở", callback_data=f"unopened_info:{assign_id}"))
        elif is_submitted:
            row.append(InlineKeyboardButton("🗑️ Xóa bài nộp", callback_data=f"remove_{assign_id}_{owner_user_id}"))
        else:
            row.append(InlineKeyboardButton("📤 Nộp bài", callback_data=f"submit_help:{assign_id}"))
        return InlineKeyboardMarkup([row])

keyboards = BotKeyboards()
