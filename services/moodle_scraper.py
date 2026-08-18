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
from utils.date_parser import parse_moodle_datetime, check_is_unopened, get_vietnam_now
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
            
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            if await self._is_logged_in(page):
                state = await context.storage_state()
                session_vault.save_session_state(self.user_id, state)
                return True, f"✅ Đăng nhập thành công tài khoản MSV `{username}`!"

            await asyncio.sleep(2)
            if await self._is_logged_in(page):
                state = await context.storage_state()
                session_vault.save_session_state(self.user_id, state)
                return True, f"✅ Đăng nhập thành công tài khoản MSV `{username}`!"

            # Attempt verification via Portal navigation
            try:
                await page.goto(PORTAL_URL, wait_until="networkidle", timeout=10000)
                if await self._is_logged_in(page):
                    state = await context.storage_state()
                    session_vault.save_session_state(self.user_id, state)
                    return True, f"✅ Đăng nhập thành công tài khoản MSV `{username}`!"
            except Exception:
                pass

            err_count = await page.locator(".alert-danger, #loginerrormessage, .loginerrors, .error").count()
            err_msg = "Tên đăng nhập (MSV) hoặc mật khẩu không chính xác."
            if err_count > 0:
                err_text = await page.locator(".alert-danger, #loginerrormessage, .loginerrors, .error").first.text_content()
                if err_text:
                    err_msg = err_text.strip()
            return False, f"❌ Đăng nhập thất bại: {err_msg}"
        except Exception as e:
            logger.error(f"Login error for {self.user_id}: {e}")
            return False, f"Lỗi trong quá trình đăng nhập: {str(e)}"
        finally:
            if page and not page.is_closed():
                await page.close()

    async def _is_logged_in(self, page) -> bool:
        if not page or page.is_closed():
            return False
        try:
            url = page.url
            if "login/index.php" not in url:
                return True
            count = await page.locator("a[href*='login/logout.php'], .userbutton, .userpicture, .usermenu").count()
            if count > 0:
                return True
        except Exception:
            pass
        return False

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

            # Comprehensive DOM data extraction for Dates, Status, Submission Info
            eval_data = await page.evaluate(r"""
                () => {
                    let opensAt = '';
                    let dueDate = '';
                    let timeRemaining = '';
                    let subStatus = '';
                    let gradingStatus = '';
                    let lastModified = '';
                    let unopenedNotice = false;

                    // 1. Activity dates container (Moodle 3.11+ / 4.x)
                    const actDates = document.querySelectorAll('[data-region="activity-dates"] div, .activity-dates div');
                    for (const d of actDates) {
                        const text = d.innerText.trim();
                        if (/opens?|mở\s+lúc|mở\s+vào|mở|thời gian mở|được mở/i.test(text)) {
                            opensAt = text.replace(/^(opens?|mở\s+lúc|mở\s+vào|mở|thời gian mở|được mở vào|được mở)[\s:]+/i, '').trim();
                        } else if (/due|hạn chót|đến hạn|thời gian đến hạn|hạn nộp|thời gian hết hạn/i.test(text)) {
                            dueDate = text.replace(/^(due|due\s+date|hạn chót|đến hạn|thời gian đến hạn|hạn nộp|thời gian hết hạn)[\s:]+/i, '').trim();
                        }
                    }

                    // 2. Submission Status Table
                    const statusTable = document.querySelector('.submissionstatustable, table.generaltable');
                    if (statusTable) {
                        const rows = Array.from(statusTable.querySelectorAll('tr'));
                        for (const r of rows) {
                            const th = r.querySelector('th, td.c0');
                            const td = r.querySelector('td.cell, td.c1, td:nth-child(2)');
                            if (th && td) {
                                const header = th.innerText.trim();
                                const val = td.innerText.trim();

                                if (/trạng thái bài nộp|submission status/i.test(header)) {
                                    subStatus = val;
                                } else if (/trạng thái chấm|grading status/i.test(header)) {
                                    gradingStatus = val;
                                } else if (/thời gian còn lại|time remaining/i.test(header)) {
                                    timeRemaining = val;
                                } else if (/thời gian mở|opens?|allow submissions from|được mở|mở\s+vào/i.test(header)) {
                                    opensAt = val;
                                } else if (/hạn chót|due date|due|thời gian đến hạn|đến hạn|thời gian hết hạn/i.test(header)) {
                                    dueDate = val;
                                } else if (/chỉnh sửa lần cuối|last modified/i.test(header)) {
                                    lastModified = val;
                                }
                            }
                        }
                    }

                    // 3. Fallback scan in page body text
                    const bodyText = document.body ? document.body.innerText : '';
                    if (!opensAt) {
                        const openMatch = bodyText.match(/(?:Opens|Mở vào|Mở lúc|Thời gian mở|Được mở vào|Được mở)[:\s]+([^\n\r,]+(?:,\s*[^\n\r]+)?)/i);
                        if (openMatch) {
                            opensAt = openMatch[1].trim();
                        }
                    }
                    if (!dueDate) {
                        const dueMatch = bodyText.match(/(?:Due date|Due|Hạn chót|Thời gian đến hạn|Đến hạn|Hạn nộp|Thời gian hết hạn)[:\s]+([^\n\r,]+(?:,\s*[^\n\r]+)?)/i);
                        if (dueMatch) {
                            dueDate = dueMatch[1].trim();
                        }
                    }
                    if (!timeRemaining) {
                        const timeMatch = bodyText.match(/(?:Thời gian còn lại|Time remaining)[:\s]+([^\n\r]+)/i);
                        if (timeMatch) {
                            timeRemaining = timeMatch[1].trim();
                        }
                    }

                    // 4. Check submit buttons existence
                    const submitButtons = document.querySelectorAll(
                        "input[value*='Thêm bài nộp'], button:has-text('Thêm bài nộp'), input[value*='Add submission'], button:has-text('Add submission'), input[value*='SỬA BÀI NỘP'], a[href*='editsubmission'], input[value*='LOẠI BỎ BÀI NỘP']"
                    );
                    const hasSubmitBtn = submitButtons.length > 0;

                    // 5. Check if page explicitly states unopened
                    if (/chưa mở|not yet open|chưa tới thời gian|sẽ được mở vào|bài tập này chưa mở/i.test(bodyText)) {
                        unopenedNotice = true;
                    }

                    return {
                        opensAt,
                        dueDate,
                        timeRemaining,
                        subStatus,
                        gradingStatus,
                        lastModified,
                        hasSubmitBtn,
                        unopenedNotice
                    };
                }
            """)

            opens_at = eval_data.get("opensAt", "").strip()
            due_date = eval_data.get("dueDate", "").strip()
            time_remaining = eval_data.get("timeRemaining", "").strip()
            sub_status = eval_data.get("subStatus", "").strip() or "Chưa nộp"
            grading_status = eval_data.get("gradingStatus", "").strip()

            # Robust unopened & submission status detection
            sub_lower = sub_status.lower()
            is_submitted = any(t in sub_lower for t in ["đã nộp", "submitted", "nộp để chấm điểm", "✓"]) and "chưa" not in sub_lower

            is_unopened = False
            if opens_at:
                is_unopened, _ = check_is_unopened(opens_at)
            elif eval_data.get("unopenedNotice") and not eval_data.get("hasSubmitBtn") and not is_submitted:
                is_unopened = True

            is_open = not is_unopened
            if not is_open and not is_submitted:
                sub_status = "Chưa mở"

            return {
                "assignment_id": aid,
                "course_name": course_name,
                "title": title.strip(),
                "description": description.strip(),
                "url": url,
                "status": sub_status,
                "grading_status": grading_status,
                "opens_at": opens_at,
                "due_date": due_date,
                "time_remaining": time_remaining,
                "is_open": is_open,
                "is_submitted": is_submitted,
                "user_id": self.user_id,
            }
        except Exception as e:
            logger.warning(f"Error inspecting assignment details {url}: {e}")
            return None

    async def download_assignment_materials(self, assignment_id: str) -> List[Path]:
        """Fetch and download homework files on demand when user clicks download button."""
        context = await browser_pool.get_context(self.user_id, str(self.storage_state_path))
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)
        downloaded_paths = []

        try:
            view_url = ASSIGNMENT_VIEW_URL.format(id=assignment_id)
            await page.goto(view_url, wait_until="networkidle", timeout=25000)

            file_links = await page.evaluate("""
                () => {
                    const anchors = Array.from(document.querySelectorAll(
                        ".intro a[href*='pluginfile.php'], .generalbox a[href*='pluginfile.php'], .fileuploadsubmission a[href*='pluginfile.php'], a[href*='mod_assign/introattachment']"
                    ));
                    return anchors.map(a => ({
                        text: a.innerText.trim(),
                        url: a.href
                    })).filter(x => x.url && x.text);
                }
            """)

            for link_info in file_links:
                url = link_info["url"]
                text = link_info["text"]
                cleaned_name = re.sub(r'[\\/*?:"<>|]', "_", text) or f"material_{assignment_id}"
                if not any(cleaned_name.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip", ".rar", ".png", ".jpg", ".txt"]):
                    cleaned_name += ".pdf"

                save_path = DOWNLOAD_DIR / f"{assignment_id}_{cleaned_name}"
                try:
                    resp = await page.request.get(url)
                    if resp.status == 200:
                        body = await resp.body()
                        save_path.write_bytes(body)
                        downloaded_paths.append(save_path)
                except Exception as ex_dl:
                    logger.warning(f"Failed to download attachment {url}: {ex_dl}")

            return downloaded_paths
        except Exception as e:
            logger.error(f"Error in download_assignment_materials: {e}")
            return []
        finally:
            await page.close()


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
