import traceback
from typing import Tuple, Optional
from pathlib import Path
from google import genai
from config.settings import GEMINI_API_KEY, BASE_DIR
from utils.git_patcher import git_patcher
from utils.logger import logger

class SelfDebuggerService:
    """AI Self-Debugging & Auto-Patching Engine."""

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    async def analyze_and_generate_patch(
        self, error: Exception, stack_trace: str, dom_snapshot: str = "", screenshot_path: Optional[Path] = None
    ) -> Tuple[bool, str, str]:
        """Send stack trace and DOM snapshot to Gemini AI to generate Git diff patch."""
        if not self.client:
            return False, "Chưa cấu hình GEMINI_API_KEY.", ""

        prompt = (
            f"Bạn là kĩ sư phần mềm Senior Python & Playwright.\n"
            f"Hệ thống gặp lỗi runtime sau đây:\n\n"
            f"Lỗi: {str(error)}\n\n"
            f"Stacktrace:\n{stack_trace[:2000]}\n\n"
            f"DOM Snapshot:\n{dom_snapshot[:1000]}\n\n"
            f"Hãy đưa ra giải thích nguyên nhân ngắn gọn và xuất ra ĐÚNG 1 khối mã Git Diff (unified format) để khắc phục lỗi."
        )

        try:
            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text or ""
            
            # Extract git diff block
            git_diff = ""
            if "```diff" in text:
                git_diff = text.split("```diff")[1].split("```")[0].strip()
            elif "```" in text:
                git_diff = text.split("```")[1].split("```")[0].strip()
            else:
                git_diff = text.strip()

            explanation = text.split("```")[0] if "```" in text else "Đã tạo bản sửa lỗi Git Diff tự động."
            return True, explanation, git_diff
        except Exception as e:
            logger.error(f"SelfDebugger analysis error: {e}")
            return False, f"Lỗi phân tích Gemini: {str(e)}", ""

    async def apply_git_patch(self, git_diff: str) -> Tuple[bool, str]:
        return git_patcher.apply_patch(git_diff)

    async def rollback() -> Tuple[bool, str]:
        return git_patcher.rollback_last_commit()

self_debugger = SelfDebuggerService()
