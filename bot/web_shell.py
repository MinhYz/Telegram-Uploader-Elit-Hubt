import asyncio
import subprocess
from config.settings import WEB_SHELL_PIN, BASE_DIR
from utils.logger import logger

class WebShellManager:
    """Remote Web Shell (/bash) protected by PIN-code 2FA."""

    def __init__(self):
        self.authenticated_users = set()

    def authenticate(self, user_id: str, input_pin: str) -> bool:
        if input_pin == WEB_SHELL_PIN:
            self.authenticated_users.add(user_id)
            logger.info(f"User {user_id} authenticated for Web Shell access.")
            return True
        return False

    def is_authenticated(self, user_id: str) -> bool:
        return user_id in self.authenticated_users

    async def execute_cmd(self, user_id: str, cmd_str: str) -> str:
        if not self.is_authenticated(user_id):
            return "⛔ Vui lòng xác thực PIN 2FA trước bằng lệnh: `/bash pin <mã_pin>`"

        # Block destructive root commands
        blocked = ["rm -rf /", "mkfs", "dd ", "shutdown", "reboot"]
        if any(b in cmd_str for b in blocked):
            return "❌ Câu lệnh bị chặn vì lý do an toàn hệ thống!"

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(BASE_DIR),
            )
            stdout, stderr = await proc.communicate()
            output = (stdout.decode() + "\n" + stderr.decode()).strip()
            return f"```bash\n{output[:3500]}\n```"
        except Exception as e:
            return f"❌ Lỗi thực thi lệnh: {str(e)}"

web_shell = WebShellManager()
