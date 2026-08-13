import re
import time
import asyncio
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional
from config.settings import (
    BASE_URL, LOGIN_URL, PORTAL_URL, ASSIGNMENT_VIEW_URL, ASSIGNMENT_EDIT_URL,
    ATTENDANCE_VIEW_URL, DOWNLOAD_DIR, SCREENSHOT_DIR, SESSION_DIR
)
from core.browser_pool import browser_pool
from core.session_vault import session_vault
from core.anti_bot import AntiBotStealth
from core.dom_engine import DOMEngine, circuit_breaker, CircuitBreakerOpenException
from utils.logger import logger

class SessionExpiredException(Exception):
    pass

class MoodleScraperService:
    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.storage_state_path = session_vault.get_session_file(user_id)

    async def login(self, username: str = "", password: str = "", token: str = "") -> Tuple[bool, str]:
        if circuit_breaker.is_open():
            raise CircuitBreakerOpenException("Circuit Breaker active due to continuous Moodle 5xx errors.")

        page = None
        try:
            context = await browser_pool.get_context(self.user_id)
            page = await context.new_page()
            await AntiBotStealth.apply_stealth(page)
            if token:
                logger.info(f"Logging in user {self.user_id} via Session Token Cookie...")
                await context.add_cookies([{
                    "name": "MoodleSession",
                    "value": token,
                    "domain": "elit.hubt.edu.vn",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }])
                await page.goto(PORTAL_URL, wait_until="networkidle", timeout=30000)
                if await self._is_logged_in(page):
                    state = await context.storage_state()
                    session_vault.save_session_state(self.user_id, state)
                    return True, "Đăng nhập thành công bằng Token Session!"
                return False, "Token MoodleSession không hợp lệ hoặc đã hết hạn."

            logger.info(f"Logging in user {self.user_id} via MSV credentials...")
            await page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
            
            username_sel = "input[name='username'], #username"
            password_sel = "input[name='password'], #password"
            login_btn_sel = "#loginbtn, button[type='submit'], input[type='submit']"

            await AntiBotStealth.human_type(page, username_sel, username)
            await AntiBotStealth.human_type(page, password_sel, password)
            await AntiBotStealth.human_move_and_click(page, login_btn_sel)
            
            await page.wait_for_load_state("networkidle", timeout=30000)

            if await self._is_logged_in(page):
                state = await context.storage_state()
                session_vault.save_session_state(self.user_id, state)
                return True, f"Đăng nhập thành công tài khoản MSV `{username}`!"
            
            err_count = await page.locator(".alert-danger, #loginerrormessage, .loginerrors").count()
            err_msg = "Sai tên đăng nhập hoặc mật khẩu."
            if err_count > 0:
                err_text = await page.locator(".alert-danger, #loginerrormessage, .loginerrors").first.text_content()
                if err_text:
                    err_msg = err_text.strip()
            return False, f"Đăng nhập thất bại: {err_msg}"
        except Exception as e:
            logger.error(f"Login error for {self.user_id}: {e}")
            return False, f"Lỗi trong quá trình đăng nhập: {str(e)}"
        finally:
            await page.close()

    async def _is_logged_in(self, page) -> bool:
        if page.url.startswith(LOGIN_URL):
            return False
        return await page.query_selector("a[href*='login/logout.php'], .userbutton, .userpicture") is not None

    async def check_today_classes_and_assignments(self) -> List[Dict[str, Any]]:
        if circuit_breaker.is_open():
            raise CircuitBreakerOpenException("Circuit Breaker active.")

        context = await browser_pool.get_context(self.user_id, str(self.storage_state_path))
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)

        try:
            logger.info(f"Scanning classes & assignments for user {self.user_id}...")
            await page.goto(PORTAL_URL, wait_until="networkidle", timeout=30000)
            if not await self._is_logged_in(page):
                raise SessionExpiredException("Session hết hạn. Vui lòng /login lại.")

            course_links = await page.evaluate("""
                () => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="course/view.php?id="]'));
                    return anchors.map(a => ({ title: a.innerText.trim(), href: a.href }))
                        .filter(c => c.title.length > 3);
                }
            """)

            assignments = []
            seen_assign_ids = set()

            for c in course_links[:10]:
                try:
                    await page.goto(c["href"], wait_until="networkidle", timeout=20000)
                    assign_elements = await page.evaluate("""
                        () => {
                            const assignAnchors = Array.from(document.querySelectorAll('a[href*="mod/assign/view.php?id="]'));
                            return assignAnchors.map(a => ({
                                title: a.innerText.trim(),
                                url: a.href,
                                id: a.href.split('id=')[1]
                            }));
                        }
                    """)
                    for a in assign_elements:
                        aid = a["id"]
                        if aid not in seen_assign_ids:
                            seen_assign_ids.add(aid)
                            details = await self._inspect_assignment_details(page, a["url"], c["title"])
                            if details:
                                assignments.append(details)
                except Exception as ex_course:
                    logger.warning(f"Error inspecting course {c['href']}: {ex_course}")

            return assignments
        finally:
            await page.close()

    async def _inspect_assignment_details(self, page, url: str, course_name: str) -> Optional[Dict[str, Any]]:
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
            aid = url.split("id=")[1]
            title_elem = await page.query_selector("h2, .page-header-headings h1")
            title = await title_elem.inner_text() if title_elem else f"Bài tập #{aid}"

            desc_elem = await page.query_selector("#intro, .no-overflow")
            description = await desc_elem.inner_text() if desc_elem else "Không có mô tả chi tiết."

            sub_status_elem = await page.query_selector(".submissionstatustable td.submissionstatus, td.cell.c1")
            sub_status = await sub_status_elem.inner_text() if sub_status_elem else "Chưa nộp"

            is_submitted = "Đã nộp" in sub_status or "Submitted" in sub_status

            time_elem = await page.query_selector("td:has-text('Thời gian còn lại'), td.earlysubmission, td.latesubmission")
            time_remaining = await time_elem.inner_text() if time_elem else ""

            return {
                "assignment_id": aid,
                "course_name": course_name,
                "title": title.strip(),
                "description": description.strip(),
                "url": url,
                "status": sub_status.strip(),
                "is_submitted": is_submitted,
                "time_remaining": time_remaining.strip(),
                "user_id": self.user_id,
            }
        except Exception as e:
            logger.warning(f"Error inspecting assignment details {url}: {e}")
            return None

    async def submit_assignment(self, assignment_id: str, file_paths: List[Path]) -> Tuple[bool, str, Optional[Path]]:
        context = await browser_pool.get_context(self.user_id, str(self.storage_state_path))
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)
        screenshot_path = SCREENSHOT_DIR / f"submit_{assignment_id}_{int(time.time())}.png"

        try:
            edit_url = ASSIGNMENT_EDIT_URL.format(id=assignment_id)
            await page.goto(edit_url, wait_until="networkidle", timeout=30000)

            file_input = await DOMEngine.find_element(page, ["input[type='file']"])
            if not file_input:
                return False, "Không tìm thấy ô chọn file nộp bài.", screenshot_path

            str_paths = [str(p) for p in file_paths]
            await file_input.set_input_files(str_paths)
            await page.wait_for_timeout(2000)

            save_btn = await DOMEngine.find_element(page, ["input[value*='Lưu'], input[value*='Save'], button:has-text('Lưu')"])
            if save_btn:
                await save_btn.click()
                await page.wait_for_load_state("networkidle", timeout=30000)

            await page.screenshot(path=str(screenshot_path))
            return True, f"Nộp thành công {len(file_paths)} file lên ELit HUBT!", screenshot_path
        except Exception as e:
            logger.error(f"Error submitting assignment {assignment_id}: {e}")
            await page.screenshot(path=str(screenshot_path))
            return False, f"Lỗi nộp bài: {str(e)}", screenshot_path
        finally:
            await page.close()

    async def remove_assignment_submission(self, assignment_id: str) -> Tuple[bool, str, Optional[Path]]:
        context = await browser_pool.get_context(self.user_id, str(self.storage_state_path))
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)
        screenshot_path = SCREENSHOT_DIR / f"remove_{assignment_id}.png"

        try:
            view_url = ASSIGNMENT_VIEW_URL.format(id=assignment_id)
            await page.goto(view_url, wait_until="networkidle", timeout=30000)

            remove_btn = await DOMEngine.find_element(page, ["input[value*='LOẠI BỎ BÀI NỘP']", "button:has-text('LOẠI BỎ BÀI NỘP')"])
            if not remove_btn:
                return False, "Không tìm thấy nút 'LOẠI BỎ BÀI NỘP'.", screenshot_path

            await remove_btn.click()
            await page.wait_for_load_state("networkidle", timeout=30000)

            confirm_btn = await DOMEngine.find_element(page, ["input[value*='TIẾP TỤC']", "button:has-text('TIẾP TỤC')"])
            if confirm_btn:
                await confirm_btn.click()
                await page.wait_for_load_state("networkidle", timeout=30000)

            await page.screenshot(path=str(screenshot_path))
            return True, "Đã loại bỏ bài nộp thành công trên ELit HUBT!", screenshot_path
        except Exception as e:
            logger.error(f"Error removing assignment {assignment_id}: {e}")
            return False, f"Lỗi gỡ bài nộp: {str(e)}", screenshot_path
        finally:
            await page.close()

    async def instant_auto_attendance(self, attendance_id: str) -> Tuple[bool, str, Optional[Path]]:
        """Auto-click 'Present' / 'Có mặt' within 0.5s of release."""
        context = await browser_pool.get_context(self.user_id, str(self.storage_state_path))
        page = await context.new_page()
        screenshot_path = SCREENSHOT_DIR / f"attendance_{attendance_id}.png"

        try:
            url = ATTENDANCE_VIEW_URL.format(id=attendance_id)
            await page.goto(url, wait_until="commit", timeout=10000)
            
            present_btn = await DOMEngine.find_element(page, ["a:has-text('Submit attendance')", "a:has-text('Điểm danh')", "input[value*='Present']"])
            if present_btn:
                await present_btn.click()
                await page.screenshot(path=str(screenshot_path))
                return True, "Đã điểm danh tự động thành công!", screenshot_path
            return False, "Không tìm thấy nút điểm danh mở.", screenshot_path
        finally:
            await page.close()
