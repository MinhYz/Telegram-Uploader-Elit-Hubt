import httpx
from bs4 import BeautifulSoup
from typing import Dict, List, Any, Optional
from utils.logger import logger

class ScheduleService:
    """Service to fetch and parse HUBT student schedule from itc.hubt.edu.vn/thoikhoabieu/"""

    BASE_URL = "https://itc.hubt.edu.vn/thoikhoabieu/"

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    async def fetch_schedule(self, search_query: str) -> Dict[str, Any]:
        """
        Fetch schedule for a given query (class name, course, batch, etc.)
        """
        query = search_query.strip()
        if not query:
            return {"success": False, "error": "Vui lòng nhập tên lớp hoặc ngành cần tra cứu."}

        payload = {
            "thongtinsinhvien": query,
            "btn_submit": ""
        }

        try:
            async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
                response = await client.post(self.BASE_URL, data=payload, headers=self.headers)
                
            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Không thể kết nối đến cổng TKB HUBT (HTTP {response.status_code})."
                }

            return self._parse_html(response.text, query)

        except httpx.TimeoutException:
            logger.error("ScheduleService: Timeout connecting to HUBT TKB")
            return {"success": False, "error": "Cổng TKB HUBT phản hồi quá chậm (Timeout). Vui lòng thử lại sau."}
        except Exception as e:
            logger.error(f"ScheduleService error: {e}", exc_info=True)
            return {"success": False, "error": f"Lỗi kết nối cổng TKB: {str(e)}"}

    def _parse_html(self, html_content: str, query: str) -> Dict[str, Any]:
        """
        Parse HTML response from HUBT schedule page.
        """
        if "Thông tin không hợp lệ" in html_content:
            return {
                "success": False,
                "error": f"Không tìm thấy thời khóa biểu cho từ khóa `{query}`! Hãy kiểm tra lại tên lớp (Ví dụ: `TH30.10`)."
            }

        soup = BeautifulSoup(html_content, "html.parser")
        
        # Look for containers
        containers = soup.find_all("div", class_="container")
        if not containers:
            return {"success": False, "error": "Không tìm thấy dữ liệu thời khóa biểu phù hợp."}

        # Find schedule blocks
        # Typically the result container has <h3> (Phase/Semester) followed by <table> elements
        result_container = containers[-1] if len(containers) > 1 else soup

        tables = result_container.find_all("table", class_="table")
        if not tables:
            # Check if there are any tables at all
            tables = soup.find_all("table", class_="table")

        if not tables:
            return {
                "success": False,
                "error": f"Không tìm thấy thời khóa biểu nào phù hợp với `{query}`."
            }

        # Parse schedule phases and tables
        # Let's group tables by preceding h3 headings if present
        schedules = []
        current_phase = "Thời khóa biểu chung"

        # Walk through children of result container
        for elem in result_container.children:
            if not elem.name:
                continue
            if elem.name in ["h3", "h4"]:
                title_text = elem.get_text(strip=True)
                if "THỜI KHÓA BIỂU" in title_text.upper():
                    current_phase = title_text
            elif elem.name == "table" and "table" in elem.get("class", []):
                parsed_table = self._parse_table(elem, current_phase)
                if parsed_table:
                    schedules.append(parsed_table)

        # Fallback if walking direct children didn't catch all tables
        if not schedules and tables:
            for table in tables:
                parsed_table = self._parse_table(table, "Thời khóa biểu")
                if parsed_table:
                    schedules.append(parsed_table)

        if not schedules:
            return {
                "success": False,
                "error": f"Không thể trích xuất bảng thời khóa biểu cho `{query}`."
            }

        return {
            "success": True,
            "query": query,
            "total_classes": len(schedules),
            "schedules": schedules
        }

    def _parse_table(self, table_elem, phase_name: str) -> Optional[Dict[str, Any]]:
        """
        Parse a single schedule table.
        """
        # Get class header from first thead or th
        class_info = ""
        thead_first = table_elem.find("thead")
        if thead_first:
            th_info = thead_first.find("th")
            if th_info:
                class_info = th_info.get_text(strip=True)

        rows = []
        # Find all data rows
        for tr in table_elem.find_all("tr"):
            tds = tr.find_all("td")
            if not tds or len(tds) < 5:
                continue
            
            day = tds[0].get_text(strip=True)
            session = tds[1].get_text(strip=True)
            subject = tds[2].get_text(strip=True)
            room = tds[3].get_text(strip=True)
            
            zoom_td = tds[4]
            zoom_id = zoom_td.get_text(strip=True)
            zoom_link = ""
            zoom_a = zoom_td.find("a")
            if zoom_a and zoom_a.get("href"):
                zoom_link = zoom_a["href"]

            apply_date = tds[5].get_text(strip=True) if len(tds) > 5 else ""

            rows.append({
                "day": day,
                "session": session,
                "subject": subject,
                "room": room,
                "zoom_id": zoom_id,
                "zoom_link": zoom_link,
                "apply_date": apply_date
            })

        if not rows and not class_info:
            return None

        return {
            "phase": phase_name,
            "class_info": class_info,
            "entries": rows
        }

    def format_schedule_messages(self, schedule_result: Dict[str, Any], max_items: int = 5) -> List[str]:
        """
        Format schedule result into Telegram Markdown message chunks.
        """
        if not schedule_result.get("success"):
            return [f"❌ **TRA CỨU THỜI KHÓA BIỂU THẤT BẠI**\n\n{schedule_result.get('error', 'Lỗi không xác định')}"]

        schedules = schedule_result.get("schedules", [])
        query = schedule_result.get("query", "")
        total = schedule_result.get("total_classes", 0)

        messages = []
        
        # Display message chunks
        displayed_schedules = schedules[:max_items]

        current_msg = f"📅 **THỜI KHÓA BIỂU HUBT - TỪ KHÓA:** `{query.upper()}`\n"
        if total > max_items:
            current_msg += f"*(Hiển thị {max_items}/{total} kết quả tìm thấy)*\n"
        current_msg += "───────────────────\n\n"

        for idx, sch in enumerate(displayed_schedules, 1):
            phase = sch.get("phase", "")
            class_info = sch.get("class_info", "Thông tin lớp")
            entries = sch.get("entries", [])

            block = f"🏷️ **{class_info}**\n"
            if phase and phase != "Thời khóa biểu":
                block += f"📌 *{phase}*\n"
            block += "\n"

            if not entries:
                block += "*(Không có môn học hoặc đang cập nhật)*\n\n"
            else:
                for item in entries:
                    day_str = f"Thứ {item['day']}" if item['day'].isdigit() else f"Chủ Nhật" if item['day'].upper() == "CN" else item['day']
                    session_emoji = "🌅" if "SÁNG" in item['session'].upper() else ("🌇" if "CHIỀU" in item['session'].upper() else "🌙")
                    
                    block += f"🗓️ **{day_str}** | {session_emoji} **{item['session']}**\n"
                    block += f"   📖 **Môn**: `{item['subject']}`\n"
                    
                    room_str = item['room']
                    if "OL" in room_str.upper() or item['zoom_id']:
                        if item['zoom_link']:
                            room_str += f" | 💻 [Zoom: {item['zoom_id']}]({item['zoom_link']})"
                        elif item['zoom_id']:
                            room_str += f" | 💻 Zoom: `{item['zoom_id']}`"
                    
                    block += f"   📍 **Phòng**: `{room_str}`\n"
                    if item['apply_date']:
                        block += f"   ⏱️ **Thời gian**: {item['apply_date']}\n"
                    block += "\n"

            block += "───────────────────\n\n"

            # Check message length limit (4096 in Telegram)
            if len(current_msg) + len(block) > 3500:
                messages.append(current_msg.strip())
                current_msg = block
            else:
                current_msg += block

        if current_msg.strip():
            messages.append(current_msg.strip())

        return messages

schedule_service = ScheduleService()
