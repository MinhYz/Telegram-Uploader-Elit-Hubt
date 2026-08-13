import json
import time
import aiosqlite
from typing import Dict, List, Optional, Any
from config.settings import DB_PATH
from database.crypto import encrypt_data, decrypt_data
from utils.logger import logger

class AsyncDatabase:
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)

    async def init_db(self):
        """Initialize database schema and tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    msv TEXT,
                    encrypted_password TEXT,
                    encrypted_token TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at REAL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS assignments (
                    assignment_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    course_name TEXT,
                    title TEXT,
                    url TEXT,
                    status TEXT,
                    grading_status TEXT,
                    time_remaining TEXT,
                    is_submitted INTEGER,
                    seen_at REAL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS grades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    course_name TEXT,
                    assignment_title TEXT,
                    grade TEXT,
                    feedback TEXT,
                    updated_at REAL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS patch_history (
                    patch_id TEXT PRIMARY KEY,
                    error_message TEXT,
                    git_diff TEXT,
                    status TEXT,
                    applied_at REAL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            await db.commit()
            logger.info(f"Database initialized at {self.db_path}")

    # User Store Operations
    async def save_user(self, user_id: str, msv: str = "", password: str = "", token: str = ""):
        enc_pass = encrypt_data(password) if password else ""
        enc_token = encrypt_data(token) if token else ""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, msv, encrypted_password, encrypted_token, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    msv = coalesce(nullif(?, ''), msv),
                    encrypted_password = coalesce(nullif(?, ''), encrypted_password),
                    encrypted_token = coalesce(nullif(?, ''), encrypted_token),
                    is_active = 1
            """, (user_id, msv, enc_pass, enc_token, time.time(), msv, enc_pass, enc_token))
            await db.commit()

    async def get_user(self, user_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ? AND is_active = 1", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "user_id": row["user_id"],
                        "msv": row["msv"],
                        "password": decrypt_data(row["encrypted_password"]),
                        "token": decrypt_data(row["encrypted_token"]),
                        "created_at": row["created_at"],
                    }
        return None

    async def get_all_active_users(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE is_active = 1") as cursor:
                rows = await cursor.fetchall()
                results = []
                for row in rows:
                    results.append({
                        "user_id": row["user_id"],
                        "msv": row["msv"],
                        "password": decrypt_data(row["encrypted_password"]),
                        "token": decrypt_data(row["encrypted_token"]),
                        "created_at": row["created_at"],
                    })
                return results

    async def delete_user(self, user_id: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id,))
            await db.commit()

    # Assignment Operations
    async def is_assignment_seen(self, assignment_id: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT 1 FROM assignments WHERE assignment_id = ?", (assignment_id,)) as cursor:
                return await cursor.fetchone() is not None

    async def mark_assignment_seen(self, assignment_id: str, data: Dict[str, Any]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO assignments (assignment_id, user_id, course_name, title, url, status, grading_status, time_remaining, is_submitted, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assignment_id) DO UPDATE SET
                    status = excluded.status,
                    grading_status = excluded.grading_status,
                    time_remaining = excluded.time_remaining,
                    is_submitted = excluded.is_submitted
            """, (
                assignment_id,
                data.get("user_id", "default"),
                data.get("course_name", ""),
                data.get("title", ""),
                data.get("url", ""),
                data.get("status", ""),
                data.get("grading_status", ""),
                data.get("time_remaining", ""),
                1 if data.get("is_submitted") else 0,
                time.time()
            ))
            await db.commit()

    # System Config Key-Value Store
    async def get_config(self, key: str, default: str = "") -> str:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT value FROM system_config WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default

    async def set_config(self, key: str, value: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO system_config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            await db.commit()

db = AsyncDatabase()
