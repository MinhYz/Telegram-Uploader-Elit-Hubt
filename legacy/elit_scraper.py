import asyncio
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.async_api import async_playwright, Page, BrowserContext
from config import (
    BASE_URL,
    LOGIN_URL,
    PORTAL_URL,
    ASSIGNMENT_VIEW_URL,
    ASSIGNMENT_EDIT_URL,
    DOWNLOAD_DIR,
    SCREENSHOT_DIR,
    HEADLESS,
    logger,
)
from session_manager import SessionManager


class SessionExpiredException(Exception):
    """Raised when Moodle session has expired and requires login."""
    pass


class ElitScraper:
    """Handles all Playwright headless browser automation for ELit HUBT LMS."""

    def __init__(self, session_manager: SessionManager = None):
        self.session_manager = session_manager or SessionManager()

    async def login(self, username: str, password: str) -> tuple[bool, str]:
        """
        Log into ELit HUBT LMS using Playwright, save storage state.
        Returns (success: bool, message: str).
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                logger.info(f"Navigating to login page: {LOGIN_URL}")
                await page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)

                # Fill credentials
                await page.fill("input[name='username'], #username", username)
                await page.fill("input[name='password'], #password", password)

                # Submit form
                login_btn = await page.query_selector("#loginbtn, button[type='submit'], input[type='submit']")
                if login_btn:
                    await login_btn.click()
                else:
                    await page.keyboard.press("Enter")

                await page.wait_for_load_state("networkidle", timeout=30000)

                # Check login status
                current_url = page.url
                if "login/index.php" in current_url:
                    # Check for login error text
                    error_elem = await page.query_selector(".alert-danger, #loginerrormessage, .loginerrors")
                    error_msg = await error_elem.inner_text() if error_elem else "Sai tên đăng nhập hoặc mật khẩu."
                    logger.warning(f"Login failed for user {username}: {error_msg}")
                    return False, f"Đăng nhập thất bại: {error_msg.strip()}"

                # Save session state & extract token upon successful login
                token = await self.session_manager.save_session(context)
                logger.info(f"Login successful for MSV {username} (Token: {token[:8]}...)")
                return True, "Đăng nhập thành công! Session & Token đã được lưu.", token

            except Exception as e:
                logger.error(f"Exception during login: {e}")
                return False, f"Lỗi hệ thống khi đăng nhập: {str(e)}", ""
            finally:
                await browser.close()

    async def check_today_classes_and_assignments(self) -> list[dict]:
        """
        Scans Portal for active courses & scans courses for unsubmitted assignments.
        Returns list of assignment dicts.
        """
        if not self.session_manager.has_session():
            raise SessionExpiredException("Chưa có session đăng nhập. Vui lòng gửi /login.")

        assignments_found = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await self.session_manager.create_context(browser)
            page = await context.new_page()

            try:
                logger.info(f"Navigating to Portal: {PORTAL_URL}")
                await page.goto(PORTAL_URL, wait_until="networkidle", timeout=30000)

                if await self.session_manager.is_session_expired(page):
                    raise SessionExpiredException("Session đã hết hạn. Vui lòng đăng nhập lại qua /login.")

                # Extract active course links under Portal
                # Select links with text "VÀO HỌC" or course links
                course_links = []
                link_elements = await page.query_selector_all("a")
                for elem in link_elements:
                    text = (await elem.inner_text()).strip()
                    href = await elem.get_attribute("href") or ""
                    if ("VÀO HỌC" in text.upper() or "course/view.php?id=" in href) and href not in course_links:
                        course_links.append(href)

                logger.info(f"Found {len(course_links)} active course links on Portal.")

                # If no direct 'VÀO HỌC' buttons, check homepage/dashboard course list
                if not course_links:
                    await page.goto(BASE_URL, wait_until="networkidle")
                    elements = await page.query_selector_all("a[href*='/course/view.php?id=']")
                    for elem in elements:
                        href = await elem.get_attribute("href")
                        if href and href not in course_links:
                            course_links.append(href)

                # Scan each course for assignment modules
                for course_url in course_links:
                    try:
                        logger.info(f"Scanning course: {course_url}")
                        await page.goto(course_url, wait_until="networkidle", timeout=25000)

                        if await self.session_manager.is_session_expired(page):
                            raise SessionExpiredException("Session hết hạn khi duyệt môn học.")

                        course_title_elem = await page.query_selector(".page-header-headings h1, h1, .breadcrumb-item.active")
                        course_name = (await course_title_elem.inner_text()).strip() if course_title_elem else "Môn học"

                        # Find assignment links on course page
                        assign_elements = await page.query_selector_all("a[href*='/mod/assign/view.php?id=']")
                        assign_urls = set()
                        for a in assign_elements:
                            href = await a.get_attribute("href")
                            if href:
                                assign_urls.add(href)

                        logger.info(f"Found {len(assign_urls)} assignment modules in course '{course_name}'")

                        for assign_url in assign_urls:
                            parsed = urlparse(assign_url)
                            query = parse_qs(parsed.query)
                            assign_id = query.get("id", [None])[0]

                            if not assign_id:
                                continue

                            # Inspect assignment view page
                            assign_detail = await self._inspect_assignment_page(context, page, assign_id, course_name)
                            if assign_detail:
                                assignments_found.append(assign_detail)

                    except SessionExpiredException:
                        raise
                    except Exception as e:
                        logger.error(f"Error scanning course {course_url}: {e}")
                        continue

            finally:
                await browser.close()

        return assignments_found

    async def _inspect_assignment_page(
        self, context: BrowserContext, page: Page, assign_id: str, course_name: str
    ) -> dict:
        """Inspects an individual assignment page, extracts status, description, and downloads attachments."""
        view_url = ASSIGNMENT_VIEW_URL.format(id=assign_id)
        logger.info(f"Inspecting assignment ID {assign_id}: {view_url}")
        
        await page.goto(view_url, wait_until="networkidle", timeout=25000)
        
        if await self.session_manager.is_session_expired(page):
            raise SessionExpiredException("Session hết hạn.")

        # Extract Title
        title_elem = await page.query_selector("h2, .page-header-headings h1, h3")
        title = (await title_elem.inner_text()).strip() if title_elem else f"Bài tập #{assign_id}"

        # Extract Description / Instructions
        intro_elem = await page.query_selector(".intro, #intro, .generalbox.mod_introbox")
        description = (await intro_elem.inner_text()).strip() if intro_elem else "Không có mô tả chi tiết."

        # Extract Submission Status details
        submission_status_val = "Chưa nộp"
        grading_status_val = ""
        time_remaining_val = ""
        last_modified_val = ""
        is_submitted = False

        status_table = await page.query_selector(".submissionstatustable, table.generaltable")
        if status_table:
            table_text = await status_table.inner_text()
            
            # Iterate through status table rows
            rows = await status_table.query_selector_all("tr")
            for row in rows:
                th = await row.query_selector("th, td.c0")
                td = await row.query_selector("td.cell, td.c1, td:nth-child(2)")
                if th and td:
                    header = (await th.inner_text()).strip()
                    val = (await td.inner_text()).strip()

                    if "Trạng thái bài nộp" in header:
                        submission_status_val = val
                    elif "Trạng thái chấm điểm" in header:
                        grading_status_val = val
                    elif "Thời gian còn lại" in header:
                        time_remaining_val = val
                    elif "Chỉnh sửa lần cuối" in header:
                        last_modified_val = val

            # Robust detection of submission status
            sub_lower = submission_status_val.lower()
            if any(t in sub_lower for t in ["✓", "đã nộp", "nộp để", "submitted"]) or (
                "nộp" in sub_lower and "chưa" not in sub_lower and "không" not in sub_lower
            ):
                is_submitted = True
            elif "chưa nộp" in sub_lower or "no attempt" in sub_lower or "chưa có" in sub_lower:
                is_submitted = False
            else:
                # Fallback table text check
                if any(t in table_text.lower() for t in ["✓ nộp", "đã nộp", "submitted for grading", "nộp để chấm điểm"]):
                    is_submitted = True

        # Extract attached homework file links without auto-downloading
        attached_links = []
        file_links = await page.query_selector_all(
            ".intro a[href*='pluginfile.php'], .fileuploadsubmission a[href*='pluginfile.php'], .generalbox a[href*='pluginfile.php']"
        )

        for link in file_links:
            href = await link.get_attribute("href")
            link_text = (await link.inner_text()).strip()
            if href:
                attached_links.append({"name": link_text, "url": href})

        return {
            "assignment_id": str(assign_id),
            "course_name": course_name,
            "title": title,
            "description": description,
            "status": submission_status_val,
            "grading_status": grading_status_val,
            "time_remaining": time_remaining_val,
            "last_modified": last_modified_val,
            "is_submitted": is_submitted,
            "url": view_url,
            "attached_links": attached_links,
            "downloaded_files": [],
        }

    async def download_assignment_materials(self, assignment_id: str) -> list[Path]:
        """Fetch and download homework files on demand when user clicks button."""
        if not self.session_manager.has_session():
            raise SessionExpiredException("Session chưa đăng nhập.")

        downloaded_paths = []
        view_url = ASSIGNMENT_VIEW_URL.format(id=assignment_id)

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await self.session_manager.create_context(browser)
            page = await context.new_page()

            try:
                await page.goto(view_url, wait_until="networkidle", timeout=25000)
                if await self.session_manager.is_session_expired(page):
                    raise SessionExpiredException("Session hết hạn.")

                file_links = await page.query_selector_all(
                    ".intro a[href*='pluginfile.php'], .fileuploadsubmission a[href*='pluginfile.php'], .generalbox a[href*='pluginfile.php']"
                )

                for link in file_links:
                    href = await link.get_attribute("href")
                    link_text = (await link.inner_text()).strip()
                    if href:
                        file_path = await self._download_attachment(context, page, href, link_text, assignment_id)
                        if file_path:
                            downloaded_paths.append(file_path)
            finally:
                await browser.close()

        return downloaded_paths

    async def _download_attachment(
        self, context: BrowserContext, page: Page, url: str, link_text: str, assign_id: str
    ) -> Path:
        """Download homework file cleanly without prefixes."""
        try:
            filename = re.sub(r'[\\/*?:"<>|]', "_", link_text) or f"attachment_{assign_id}"
            if not any(filename.lower().endswith(ext) for ext in [".pdf", ".docx", ".xlsx", ".zip", ".rar", ".png", ".jpg", ".txt"]):
                ext = Path(urlparse(url).path).suffix
                if ext:
                    filename += ext

            target_path = DOWNLOAD_DIR / filename
            
            response = await context.request.get(url)
            if response.status == 200:
                body = await response.body()
                target_path.write_bytes(body)
                logger.info(f"Downloaded attachment cleanly for Assign #{assign_id}: {target_path}")
                return target_path
            else:
                logger.warning(f"Failed download HTTP {response.status} for {url}")
        except Exception as e:
            logger.error(f"Error downloading attachment {url}: {e}")
        return None

    async def submit_assignment(
        self, assignment_id: str, file_paths: list[str] | str
    ) -> tuple[bool, str, Path]:
        """
        Upload single or multiple files into Moodle assignment edit submission page and click 'Save changes'.
        Returns (success: bool, status_message: str, screenshot_path: Path).
        """
        if isinstance(file_paths, str):
            file_paths = [file_paths]

        if not self.session_manager.has_session():
            raise SessionExpiredException("Session chưa đăng nhập.")

        edit_url = ASSIGNMENT_EDIT_URL.format(id=assignment_id)
        screenshot_path = SCREENSHOT_DIR / f"submission_status_{assignment_id}.png"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await self.session_manager.create_context(browser)
            page = await context.new_page()

            try:
                logger.info(f"Opening edit submission page for ID {assignment_id}: {edit_url}")
                await page.goto(edit_url, wait_until="networkidle", timeout=30000)

                if await self.session_manager.is_session_expired(page):
                    raise SessionExpiredException("Session hết hạn. Vui lòng thực hiện /login.")

                # Upload each file into Moodle FilePicker
                for idx, fp in enumerate(file_paths):
                    logger.info(f"Processing upload for file {idx + 1}/{len(file_paths)}: {fp}")

                    # Step 1: Click 'Add file' button (.fp-btn-add)
                    add_file_btn = await page.query_selector(".fp-btn-add, a[title='Thêm...'], a[title='Add...']")
                    if add_file_btn and await add_file_btn.is_visible():
                        try:
                            await add_file_btn.click()
                            await page.wait_for_timeout(1000)
                        except Exception as ex:
                            logger.debug(f"Add file button click note: {ex}")

                    # Step 2: Select 'Tải file lên' / 'Upload a file' tab in modal
                    upload_tab = await page.query_selector(
                        ".fp-repo-name:has-text('Tải file lên'), .fp-repo-name:has-text('Upload a file'), span:has-text('Tải file lên')"
                    )
                    if upload_tab and await upload_tab.is_visible():
                        try:
                            await upload_tab.click()
                            await page.wait_for_timeout(500)
                        except Exception as ex:
                            logger.debug(f"Tab click note: {ex}")

                    # Step 3: Find file input in FilePicker modal
                    file_input = await page.query_selector("input[type='file'][name='repo_upload_file'], .moodle-dialogue input[type='file'], input[type='file']")
                    if not file_input:
                        file_inputs = await page.query_selector_all("input[type='file']")
                        if file_inputs:
                            file_input = file_inputs[0]

                    if not file_input:
                        await page.screenshot(path=str(screenshot_path))
                        return False, f"Không tìm thấy ô nộp file Moodle cho file: {Path(fp).name}", screenshot_path

                    # Set file path
                    await file_input.set_input_files(fp)
                    logger.info(f"Set input file {idx + 1}: {fp}")
                    await page.wait_for_timeout(500)

                    # Step 4: Click 'Upload this file' button (.fp-upload-btn)
                    upload_confirm_btn = await page.query_selector(
                        "button.fp-upload-btn, button:has-text('Tải file này lên'), button:has-text('Upload this file')"
                    )
                    if upload_confirm_btn and await upload_confirm_btn.is_visible():
                        await upload_confirm_btn.click()
                        await page.wait_for_load_state("networkidle", timeout=20000)
                        await page.wait_for_timeout(1500)

                # Click "LƯU NHỮNG THAY ĐỔI" (Save changes button)
                save_btn = await page.query_selector(
                    "input[type='submit'][name='submitbutton'], input[value*='Lưu'], button:has-text('Lưu những thay đổi'), #id_submitbutton"
                )
                if save_btn:
                    await save_btn.click()
                else:
                    await page.keyboard.press("Enter")

                await page.wait_for_load_state("networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # Capture visual proof screenshot
                status_table = await page.query_selector(".submissionstatustable, table.generaltable")
                if status_table:
                    await status_table.screenshot(path=str(screenshot_path))
                else:
                    await page.screenshot(path=str(screenshot_path), full_page=False)

                # Confirm submission status on status page
                page_content = await page.content()
                if any(t in page_content for t in ["Đã nộp", "Submitted for grading", "Lưu thành công", "✓ Nộp"]):
                    logger.info(f"Successfully submitted assignment #{assignment_id} with {len(file_paths)} file(s).")
                    return True, f"Nộp thành công {len(file_paths)} file lên ELit HUBT! Moodle đã ghi nhận.", screenshot_path
                else:
                    return True, f"Đã gửi yêu cầu lưu {len(file_paths)} file. Vui lòng kiểm tra hình ảnh xác nhận.", screenshot_path

            except SessionExpiredException:
                raise
            except Exception as e:
                logger.error(f"Error submitting assignment #{assignment_id}: {e}")
                await page.screenshot(path=str(screenshot_path))
                return False, f"Lỗi trong quá trình nộp bài: {str(e)}", screenshot_path
            finally:
                await browser.close()

    async def remove_assignment_submission(self, assignment_id: str) -> tuple[bool, str, Path]:
        """
        Removes an assignment submission on Moodle (LOẠI BỎ BÀI NỘP workflow).
        Returns (success: bool, status_message: str, screenshot_path: Path).
        """
        if not self.session_manager.has_session():
            raise SessionExpiredException("Session chưa đăng nhập.")

        view_url = ASSIGNMENT_VIEW_URL.format(id=assignment_id)
        screenshot_path = SCREENSHOT_DIR / f"remove_{assignment_id}.png"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await self.session_manager.create_context(browser)
            page = await context.new_page()

            try:
                logger.info(f"Navigating to assignment page for removal (ID #{assignment_id}): {view_url}")
                await page.goto(view_url, wait_until="networkidle", timeout=30000)

                if await self.session_manager.is_session_expired(page):
                    raise SessionExpiredException("Session hết hạn. Vui lòng thực hiện /login.")

                # Locate "LOẠI BỎ BÀI NỘP" button / link
                remove_btn = await page.query_selector(
                    "input[value*='LOẠI BỎ BÀI NỘP'], input[value*='Loại bỏ bài nộp'], button:has-text('LOẠI BỎ BÀI NỘP'), button:has-text('Loại bỏ bài nộp'), a:has-text('LOẠI BỎ BÀI NỘP'), a:has-text('Loại bỏ bài nộp')"
                )

                if not remove_btn or not (await remove_btn.is_visible()):
                    await page.screenshot(path=str(screenshot_path))
                    page_text = await page.inner_text("body")
                    if "Chưa có bài nộp nào" in page_text or "Chưa nộp" in page_text:
                        return True, "Bài tập này hiện tại chưa có bài nộp nào để xóa.", screenshot_path
                    return False, "Không tìm thấy nút 'LOẠI BỎ BÀI NỘP' (có thể đã quá hạn hoặc bài tập chưa nộp).", screenshot_path

                # Click "LOẠI BỎ BÀI NỘP"
                logger.info(f"Clicking 'LOẠI BỎ BÀI NỘP' for Assignment #{assignment_id}")
                await remove_btn.click()
                await page.wait_for_load_state("networkidle", timeout=30000)

                # Moodle confirmation page (action=removesubmissionconfirm)
                confirm_btn = await page.query_selector(
                    "input[value*='TIẾP TỤC'], input[value*='Tiếp tục'], button:has-text('TIẾP TỤC'), button:has-text('Tiếp tục'), input[type='submit'][name='continue']"
                )
                if confirm_btn and await confirm_btn.is_visible():
                    logger.info(f"Clicking 'TIẾP TỤC' confirmation for Assignment #{assignment_id}")
                    await confirm_btn.click()
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    await page.wait_for_timeout(2000)

                # Capture visual proof screenshot of updated status
                status_table = await page.query_selector(".submissionstatustable, table.generaltable")
                if status_table:
                    await status_table.screenshot(path=str(screenshot_path))
                else:
                    await page.screenshot(path=str(screenshot_path), full_page=False)

                page_content = await page.content()
                if any(t in page_content for t in ["Chưa nộp", "Chưa có bài nộp", "No attempt", "Loại bỏ bài nộp thành công"]):
                    logger.info(f"Successfully removed submission for Assignment #{assignment_id}")
                    return True, "Đã loại bỏ bài nộp thành công trên ELit HUBT!", screenshot_path
                else:
                    return True, "Đã gửi yêu cầu xóa bài nộp. Vui lòng kiểm tra hình ảnh xác nhận.", screenshot_path

            except SessionExpiredException:
                raise
            except Exception as e:
                logger.error(f"Error removing submission for Assignment #{assignment_id}: {e}")
                await page.screenshot(path=str(screenshot_path))
                return False, f"Lỗi trong quá trình xóa bài nộp: {str(e)}", screenshot_path
            finally:
                await browser.close()
