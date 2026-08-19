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

    def get_storage_state(self) -> Optional[Dict[str, Any]]:
        return session_vault.load_session_state(self.user_id)

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

            # 1. Check if already logged in (redirected to portal or home)
            if await self._is_logged_in(page):
                state = await context.storage_state()
                session_vault.save_session_state(self.user_id, state)
                return True, f"✅ Đăng nhập thành công tài khoản MSV `{username}`!"

            username_sel = "input[name='username'], #username, input[autocomplete='username'], input[type='text']"
            password_sel = "input[name='password'], #password, input[autocomplete='current-password'], input[type='password']"
            login_btn_sel = "#loginbtn, button[type='submit'], input[type='submit'], button:has-text('Đăng nhập'), input[value*='Đăng nhập']"

            # 2. Check if username field is present
            user_input = await DOMEngine.find_element(page, ["input[name='username']", "#username", "input[type='text']"])
            if not user_input:
                await page.wait_for_timeout(2000)
                if await self._is_logged_in(page):
                    state = await context.storage_state()
                    session_vault.save_session_state(self.user_id, state)
                    return True, f"✅ Đăng nhập thành công tài khoản MSV `{username}`!"
                return False, "Không tải được form đăng nhập ELit HUBT (Vui lòng thử lại hoặc đăng nhập bằng /login <token>)."

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

        context = await browser_pool.get_context(self.user_id, self.get_storage_state())
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)

        try:
            logger.info(f"Scanning classes & assignments for user {self.user_id}...")
            await page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=15000)
            if not await self._is_logged_in(page):
                raise SessionExpiredException("Session hết hạn. Vui lòng /login lại.")

            course_links = await page.evaluate("""
                () => {
                    const anchors = Array.from(document.querySelectorAll('a[href*="course/view.php?id="]'));
                    return anchors.map(a => ({ title: a.innerText.trim(), href: a.href }))
                        .filter(c => c.title.length > 3);
                }
            """)

            sem = asyncio.Semaphore(4)
            assignments = []
            seen_assign_ids = set()

            async def _inspect_course(c_info):
                nonlocal assignments, seen_assign_ids
                async with sem:
                    c_page = None
                    try:
                        c_page = await context.new_page()
                        await AntiBotStealth.apply_stealth(c_page)
                        await c_page.goto(c_info["href"], wait_until="domcontentloaded", timeout=12000)
                        assign_elements = await c_page.evaluate("""
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
                                details = await self._inspect_assignment_details(c_page, a["url"], c_info["title"])
                                if details:
                                    assignments.append(details)
                    except Exception as ex_course:
                        logger.warning(f"Error inspecting course {c_info['href']}: {ex_course}")
                    finally:
                        if c_page and not c_page.is_closed():
                            await c_page.close()

            # Run course scanning in parallel
            tasks = [_inspect_course(c) for c in course_links[:10]]
            await asyncio.gather(*tasks, return_exceptions=True)

            return assignments
        finally:
            if page and not page.is_closed():
                await page.close()

    async def _inspect_assignment_details(self, page, url: str, course_name: str) -> Optional[Dict[str, Any]]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=12000)
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
                        for (const row of rows) {
                            const th = (row.querySelector('th, .cell.c0') ? row.querySelector('th, .cell.c0').innerText : '').trim().toLowerCase();
                            const td = (row.querySelector('td, .cell.c1') ? row.querySelector('td, .cell.c1').innerText : '').trim();

                            if (/trạng thái nộp|submission status/i.test(th)) {
                                subStatus = td;
                            } else if (/trạng thái chấm|grading status/i.test(th)) {
                                gradingStatus = td;
                            } else if (/thời gian còn lại|time remaining/i.test(th)) {
                                timeRemaining = td;
                            } else if (/hạn chót|đến hạn|thời gian đến hạn|due date/i.test(th)) {
                                if (!dueDate) dueDate = td;
                            } else if (/lần sửa đổi cuối|last modified/i.test(th)) {
                                lastModified = td;
                            }
                        }
                    }

                    // 3. Fallback to raw text matching if table not structured
                    if (!dueDate) {
                        const allText = document.body.innerText;
                        const dueMatch = allText.match(/(?:Hạn chót|Thời gian đến hạn|Due date|Đến hạn):\s*([^\n\r]+)/i);
                        if (dueMatch) dueDate = dueMatch[1].trim();
                        const timeRemMatch = allText.match(/(?:Thời gian còn lại|Time remaining):\s*([^\n\r]+)/i);
                        if (timeRemMatch && !timeRemaining) timeRemaining = timeRemMatch[1].trim();
                    }

                    // 4. Unopened notice check
                    const alertElem = document.querySelector('.alert-warning, .alert-info, .submissionnotopen, .box.py-3.generalbox');
                    if (alertElem) {
                        const txt = alertElem.innerText;
                        if (/chưa được mở|chưa mở|not open|will open/i.test(txt)) {
                            unopenedNotice = true;
                            if (!opensAt) {
                                const m = txt.match(/(?:mở|open)[^:\d]*:\s*([^\n\r]+)/i);
                                if (m) opensAt = m[1].trim();
                            }
                        }
                    }

                    return {
                        opensAt,
                        dueDate,
                        timeRemaining,
                        subStatus,
                        gradingStatus,
                        lastModified,
                        unopenedNotice
                    };
                }
            """)

            opens_at = eval_data.get("opensAt", "")
            due_date = eval_data.get("dueDate", "")
            time_remaining = eval_data.get("timeRemaining", "")
            sub_status = eval_data.get("subStatus", "")
            grading_status = eval_data.get("gradingStatus", "")
            last_modified = eval_data.get("lastModified", "")
            unopened_notice = eval_data.get("unopenedNotice", False)

            # Check submission status
            is_submitted = False
            if sub_status:
                if any(k in sub_status.lower() for k in ["đã nộp", "submitted", "được chấm", "graded"]):
                    is_submitted = True
            elif "đã nộp để chấm" in (await page.content()).lower():
                is_submitted = True

            # Calculate open status
            is_open = True
            if unopened_notice:
                is_open = False
            elif opens_at:
                is_unopened, _ = check_is_unopened(opens_at)
                if is_unopened:
                    is_open = False

            parsed_due_dt = parse_moodle_datetime(due_date) if due_date else None
            parsed_open_dt = parse_moodle_datetime(opens_at) if opens_at else None

            return {
                "assignment_id": aid,
                "title": title,
                "course_name": course_name,
                "description": description[:300],
                "url": url,
                "opens_at": opens_at,
                "due_date": due_date,
                "due_datetime": parsed_due_dt.isoformat() if parsed_due_dt else None,
                "opens_datetime": parsed_open_dt.isoformat() if parsed_open_dt else None,
                "time_remaining": time_remaining,
                "submission_status": sub_status or ("Đã nộp bài" if is_submitted else "Chưa nộp bài"),
                "grading_status": grading_status,
                "last_modified": last_modified,
                "is_submitted": is_submitted,
                "is_open": is_open,
            }
        except Exception as e:
            logger.error(f"Error inspecting assignment {url}: {e}")
            return None

    async def download_assignment_materials(self, assignment_id: str) -> Tuple[List[Path], str]:
        context = await browser_pool.get_context(self.user_id, self.get_storage_state())
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)

        try:
            view_url = ASSIGNMENT_VIEW_URL.format(id=assignment_id)
            await page.goto(view_url, wait_until="domcontentloaded", timeout=15000)

            if not await self._is_logged_in(page):
                raise SessionExpiredException("Session hết hạn. Vui lòng /login lại.")

            downloaded_paths = []

            # Extract teacher instructions text
            intro_text = await page.evaluate("""
                () => {
                    const el = document.querySelector('#intro, .activity-description, .no-overflow, [data-region="activity-description"]');
                    return el ? el.innerText.trim() : '';
                }
            """)

            # Extract downloadable file links
            file_links = await page.evaluate("""
                () => {
                    const links = [];
                    const anchors = Array.from(document.querySelectorAll('#region-main a[href*="pluginfile.php"], #intro a[href*="pluginfile.php"], .activity-description a[href*="pluginfile.php"], .introattachment a[href*="pluginfile.php"], .fileuploadsubmission a[href*="pluginfile.php"], a[href*="/mod_assign/introattachment/"]'));
                    
                    for (const a of anchors) {
                        const href = a.href;
                        if (!href || href.includes('theme/') || href.includes('pix.php') || href.includes('user/pix.php') || href.includes('/icon')) {
                            continue;
                        }
                        const text = a.innerText.trim() || a.getAttribute('title') || href.split('/').pop().split('?')[0];
                        links.push({ url: href, text: text });
                    }
                    return links;
                }
            """)

            seen_urls = set()
            for link_info in file_links:
                url = link_info["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                text = link_info.get("text", "")
                cleaned_name = re.sub(r'[\\/*?:"<>|]', "_", text) or f"material_{assignment_id}"
                if not any(cleaned_name.lower().endswith(ext) for ext in [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip", ".rar", ".png", ".jpg", ".txt", ".pptx", ".ppt"]):
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

            return downloaded_paths, intro_text
        except SessionExpiredException:
            raise
        except Exception as e:
            logger.error(f"Error in download_assignment_materials: {e}")
            return [], intro_text
        finally:
            if page and not page.is_closed():
                await page.close()


    async def submit_assignment(self, assignment_id: str, file_paths: List[Path]) -> Tuple[bool, str, Optional[Path]]:
        context = await browser_pool.get_context(self.user_id, self.get_storage_state())
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)
        screenshot_path = SCREENSHOT_DIR / f"submit_{assignment_id}_{int(time.time())}.png"

        try:
            edit_url = ASSIGNMENT_EDIT_URL.format(id=assignment_id)
            logger.info(f"Opening edit submission page for assignment #{assignment_id} (user: {self.user_id})...")
            await page.goto(edit_url, wait_until="domcontentloaded", timeout=15000)

            # Check if session is expired or redirected to login
            if not await self._is_logged_in(page):
                await page.screenshot(path=str(screenshot_path))
                return False, "Session hết hạn hoặc chưa đăng nhập. Vui lòng dùng lệnh /login lại.", screenshot_path

            # If on view page, check if we need to click 'Thêm bài nộp' / 'Chỉnh sửa bài nộp' / 'Add submission'
            add_sub_btn = await DOMEngine.find_element(
                page,
                [
                    "a:has-text('Thêm bài nộp')", "button:has-text('Thêm bài nộp')", "input[value*='Thêm bài nộp']",
                    "a:has-text('Chỉnh sửa bài nộp')", "button:has-text('Chỉnh sửa bài nộp')", "input[value*='Chỉnh sửa bài nộp']",
                    "a:has-text('Add submission')", "button:has-text('Add submission')", "input[value*='Add submission']",
                    "a:has-text('Edit submission')", "button:has-text('Edit submission')", "input[value*='Edit submission']"
                ],
                timeout_ms=2000
            )
            if add_sub_btn:
                try:
                    await add_sub_btn.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception as ex_btn:
                    logger.debug(f"Click add submission button note: {ex_btn}")

            # Upload each file into Moodle FilePicker
            files_uploaded = 0
            for idx, fp in enumerate(file_paths):
                file_uploaded = False
                logger.info(f"Uploading file {idx + 1}/{len(file_paths)}: {fp.name}")

                # Step 1: Click 'Add file' button (.fp-btn-add)
                add_file_btn = await page.query_selector(
                    ".fp-btn-add, a[title='Thêm...'], a[title='Thêm tệp...'], a[title='Add...'], a[title='Add file'], .fp-toolbar a, .dndupload-message"
                )
                if add_file_btn:
                    try:
                        await add_file_btn.click()
                    except Exception as ex_click:
                        logger.warning(f"Error clicking add file button for {fp.name}: {ex_click}")

                # Step 2: Wait for modal to appear and click 'Tải file lên' / 'Upload a file' tab
                try:
                    upload_tab = await page.wait_for_selector(
                        ".fp-repo-name:has-text('Tải file lên'), .fp-repo-name:has-text('Upload a file'), span:has-text('Tải file lên'), span:has-text('Upload a file'), .fp-repo-area li:first-child a",
                        timeout=4000
                    )
                    if upload_tab:
                        await upload_tab.click()
                except Exception:
                    pass

                # Step 3: Wait for file input inside the modal
                try:
                    modal_file_input = await page.wait_for_selector(
                        "input[type='file'][name='repo_upload_file'], .moodle-dialogue input[type='file'], input[type='file']",
                        timeout=4000
                    )
                    if modal_file_input:
                        await modal_file_input.set_input_files(str(fp))

                        # Step 4: Click Upload confirm button
                        upload_confirm_btn = await page.wait_for_selector(
                            "button.fp-upload-btn, button:has-text('Tải file này lên'), button:has-text('Upload this file'), button:has-text('Đăng tải tệp này'), input[value*='Đăng tải tệp này']",
                            timeout=4000
                        )
                        if upload_confirm_btn:
                            await upload_confirm_btn.click()

                            # Wait for upload confirm button to disappear
                            try:
                                await page.wait_for_selector("button.fp-upload-btn", state="hidden", timeout=10000)
                            except Exception:
                                pass

                            await page.wait_for_timeout(500)
                            file_uploaded = True
                            files_uploaded += 1
                            logger.info(f"Successfully uploaded {idx + 1}/{len(file_paths)}: {fp.name}")
                except Exception as ex_modal:
                    logger.warning(f"Error in FilePicker modal for {fp.name}: {ex_modal}")

                # Fallback to direct input if FilePicker modal was not available
                if not file_uploaded:
                    direct_input = await page.query_selector("input[type='file']")
                    if direct_input:
                        try:
                            await direct_input.set_input_files(str(fp))
                            await page.wait_for_timeout(500)
                            file_uploaded = True
                            files_uploaded += 1
                        except Exception as ex_direct:
                            logger.warning(f"Direct file input error for {fp.name}: {ex_direct}")

            if files_uploaded < len(file_paths):
                await page.screenshot(path=str(screenshot_path))
                if files_uploaded == 0:
                    page_text = await page.inner_text("body")
                    if "hết hạn" in page_text.lower() or "quá hạn" in page_text.lower() or "closed" in page_text.lower() or "due date" in page_text.lower():
                        return False, "Bài tập đã hết hạn nộp hoặc đã bị khóa trên ELit HUBT.", screenshot_path
                    if "không cho phép nộp file" in page_text.lower() or "văn bản trực tuyến" in page_text.lower() or "online text" in page_text.lower():
                        return False, "Bài tập này yêu cầu nộp văn bản trực tuyến (Online text), không mở ô nộp file.", screenshot_path
                    return False, "Không tìm thấy ô chọn file nộp bài trên ELit HUBT.", screenshot_path
                return False, f"Chỉ tải lên được {files_uploaded}/{len(file_paths)} file lên FilePicker Moodle (Lỗi file: {file_paths[files_uploaded].name}).", screenshot_path

            # Click 'Save changes' / 'Lưu những thay đổi' button
            save_btn = await DOMEngine.find_element(
                page,
                [
                    "input[type='submit'][name='submitbutton']",
                    "#id_submitbutton",
                    "input[value*='Lưu']",
                    "button:has-text('Lưu những thay đổi')",
                    "button:has-text('Lưu')",
                    "input[value*='Save changes']",
                    "input[value*='Save']"
                ],
                timeout_ms=3000
            )
            if save_btn:
                await save_btn.click()
            else:
                await page.keyboard.press("Enter")

            # Wait for status table or confirmation
            try:
                await page.wait_for_selector(".submissionstatustable, table.generaltable, .alert", timeout=8000)
            except Exception:
                pass

            # Capture visual confirmation screenshot
            status_table = await page.query_selector(".submissionstatustable, table.generaltable")
            if status_table:
                await status_table.screenshot(path=str(screenshot_path))
            else:
                await page.screenshot(path=str(screenshot_path))

            page_content = await page.content()
            if any(t in page_content for t in ["Đã nộp", "Submitted for grading", "Lưu thành công", "✓ Nộp", "submitted"]):
                return True, f"Nộp thành công {len(file_paths)} file lên ELit HUBT! Moodle đã xác nhận bài nộp.", screenshot_path
            return True, f"Đã gửi yêu cầu nộp {len(file_paths)} file lên ELit HUBT. Vui lòng kiểm tra ảnh xác nhận đính kèm.", screenshot_path
        except Exception as e:
            logger.error(f"Error submitting assignment {assignment_id}: {e}")
            try:
                await page.screenshot(path=str(screenshot_path))
            except Exception:
                pass
            return False, f"Lỗi nộp bài: {str(e)}", screenshot_path
        finally:
            if page and not page.is_closed():
                await page.close()

    async def remove_assignment_submission(self, assignment_id: str) -> Tuple[bool, str, Optional[Path]]:
        context = await browser_pool.get_context(self.user_id, self.get_storage_state())
        page = await context.new_page()
        await AntiBotStealth.apply_stealth(page)
        screenshot_path = SCREENSHOT_DIR / f"remove_{assignment_id}.png"

        try:
            view_url = ASSIGNMENT_VIEW_URL.format(id=assignment_id)
            await page.goto(view_url, wait_until="domcontentloaded", timeout=12000)

            if not await self._is_logged_in(page):
                return False, "Session hết hạn hoặc chưa đăng nhập. Vui lòng dùng lệnh /login lại.", screenshot_path

            remove_btn = await DOMEngine.find_element(
                page,
                [
                    "input[value*='LOẠI BỎ BÀI NỘP']",
                    "button:has-text('LOẠI BỎ BÀI NỘP')",
                    "input[value*='Remove submission']",
                    "button:has-text('Remove submission')",
                    "a:has-text('LOẠI BỎ BÀI NỘP')",
                    "a:has-text('Remove submission')"
                ],
                timeout_ms=3000
            )
            if not remove_btn:
                await page.screenshot(path=str(screenshot_path))
                return False, "Không tìm thấy nút 'LOẠI BỎ BÀI NỘP' (Có thể bài tập chưa nộp hoặc đã bị khóa).", screenshot_path

            await remove_btn.click()

            confirm_btn = await DOMEngine.find_element(
                page,
                [
                    "input[value*='TIẾP TỤC']",
                    "button:has-text('TIẾP TỤC')",
                    "input[value*='Continue']",
                    "button:has-text('Continue')"
                ],
                timeout_ms=5000
            )
            if confirm_btn:
                await confirm_btn.click()
                try:
                    await page.wait_for_selector(".submissionstatustable, table.generaltable, .alert", timeout=6000)
                except Exception:
                    pass

            await page.screenshot(path=str(screenshot_path))
            return True, "Đã loại bỏ bài nộp thành công trên ELit HUBT!", screenshot_path
        except Exception as e:
            logger.error(f"Error removing assignment {assignment_id}: {e}")
            return False, f"Lỗi gỡ bài nộp: {str(e)}", screenshot_path
        finally:
            if page and not page.is_closed():
                await page.close()

    async def instant_auto_attendance(self, attendance_id: str) -> Tuple[bool, str, Optional[Path]]:
        """Auto-click 'Present' / 'Có mặt' within 0.5s of release."""
        context = await browser_pool.get_context(self.user_id, self.get_storage_state())
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
