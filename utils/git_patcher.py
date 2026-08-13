import subprocess
from pathlib import Path
from config.settings import BASE_DIR
from utils.logger import logger

class GitPatcher:
    """Git Diff Application & Rollback Engine for Self-Debugging."""

    @staticmethod
    def apply_patch(diff_content: str) -> tuple[bool, str]:
        """Apply a git diff patch string to the repository."""
        patch_file = BASE_DIR / "temp_patch.patch"
        try:
            with open(patch_file, "w", encoding="utf-8") as f:
                f.write(diff_content)

            res = subprocess.run(
                ["git", "apply", str(patch_file)],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
            )
            if patch_file.exists():
                patch_file.unlink()

            if res.returncode == 0:
                logger.info("Successfully applied Git diff patch.")
                return True, "Đã áp dụng Git diff patch thành công!"
            else:
                logger.error(f"Git apply patch failed: {res.stderr}")
                return False, f"Lỗi áp dụng patch: {res.stderr}"
        except Exception as e:
            logger.error(f"Failed to apply patch: {e}")
            if patch_file.exists():
                patch_file.unlink()
            return False, f"Ngoại lệ khi áp dụng patch: {str(e)}"

    @staticmethod
    def rollback_last_commit() -> tuple[bool, str]:
        """Rollback git working tree to HEAD."""
        try:
            res = subprocess.run(
                ["git", "checkout", "--", "."],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
            )
            if res.returncode == 0:
                logger.info("Successfully rolled back working tree to HEAD.")
                return True, "Khôi phục mã nguồn về trạng thái HEAD thành công!"
            return False, f"Lỗi rollback: {res.stderr}"
        except Exception as e:
            return False, f"Ngoại lệ khi rollback: {str(e)}"

git_patcher = GitPatcher()
