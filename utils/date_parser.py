import re
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import dateutil.parser

# Vietnam Timezone (UTC+7)
VN_TZ = timezone(timedelta(hours=7))

VN_MONTHS_MAP = {
    'tháng một': 1, 'tháng 1': 1, 'tháng giêng': 1, 'january': 1, 'jan': 1,
    'tháng hai': 2, 'tháng 2': 2, 'february': 2, 'feb': 2,
    'tháng ba': 3, 'tháng 3': 3, 'march': 3, 'mar': 3,
    'tháng tư': 4, 'tháng 4': 4, 'tháng bốn': 4, 'april': 4, 'apr': 4,
    'tháng năm': 5, 'tháng 5': 5, 'may': 5,
    'tháng sáu': 6, 'tháng 6': 6, 'june': 6, 'jun': 6,
    'tháng bảy': 7, 'tháng 7': 7, 'july': 7, 'jul': 7,
    'tháng tám': 8, 'tháng 8': 8, 'august': 8, 'aug': 8,
    'tháng chín': 9, 'tháng 9': 9, 'september': 9, 'sep': 9,
    'tháng mười': 10, 'tháng 10': 10, 'october': 10, 'oct': 10,
    'tháng mười một': 11, 'tháng 11': 11, 'november': 11, 'nov': 11,
    'tháng mười hai': 12, 'tháng 12': 12, 'tháng chạp': 12, 'december': 12, 'dec': 12
}

def get_vietnam_now() -> datetime:
    """Return current datetime in Vietnam Timezone (UTC+7)."""
    return datetime.now(VN_TZ)

def parse_moodle_datetime(raw_text: str) -> Optional[datetime]:
    """
    Parses various Moodle date-time string formats (Vietnamese & English).
    Returns a timezone-aware datetime (UTC+7) or None.
    """
    if not raw_text:
        return None
    
    clean_text = raw_text.strip()
    # Strip prefix label if present (e.g., Opens:, Due:, Mở:, Hạn chót:)
    clean_text = re.sub(
        r'^(opens?|due|mở\s+lúc|mở\s+vào|mở|thời gian mở|được mở vào|được mở|hạn chót|hạn nộp|thời gian đến hạn|đến hạn|due\s+date|opened)[\s:]+',
        '',
        clean_text,
        flags=re.IGNORECASE
    ).strip()

    # Strip day of week prefix: "Thứ Hai,", "Thứ 2,", "Monday,", etc.
    text_no_dow = re.sub(
        r'^(thứ\s+[a-z0-9]+|chủ nhật|cn|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)[,\s]*',
        '',
        clean_text,
        flags=re.IGNORECASE
    ).strip()

    # Case 1: Standard dd/mm/yyyy hh:mm or dd-mm-yyyy hh:mm(:ss) (am/pm)?
    m_std = re.search(
        r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})[,\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?',
        text_no_dow,
        flags=re.IGNORECASE
    )
    if m_std:
        day, month, year, hour, minute, sec, ampm = m_std.groups()
        day, month, year, hour, minute = int(day), int(month), int(year), int(hour), int(minute)
        if ampm:
            ampm_l = ampm.lower()
            if ampm_l == 'pm' and hour < 12:
                hour += 12
            elif ampm_l == 'am' and hour == 12:
                hour = 0
        try:
            return datetime(year, month, day, hour, minute, tzinfo=VN_TZ)
        except ValueError:
            pass

    # Case 2: Named Vietnamese or English Month: "18 Tháng 8 2026, 07:00" or "18 August 2026, 7:00 AM"
    text_lower = text_no_dow.lower()
    for k, month_num in sorted(VN_MONTHS_MAP.items(), key=lambda x: -len(x[0])):
        if k in text_lower:
            pattern = rf'(\d{{1,2}})\s+{re.escape(k)}[,\s]+(\d{{4}})[,\s]+(\d{{1,2}}):(\d{{2}})(?::(\d{{2}}))?\s*(am|pm)?'
            m_month = re.search(pattern, text_lower)
            if m_month:
                day, year, hour, minute, sec, ampm = m_month.groups()
                day, year, hour, minute = int(day), int(year), int(hour), int(minute)
                if ampm:
                    ampm_l = ampm.lower()
                    if ampm_l == 'pm' and hour < 12:
                        hour += 12
                    elif ampm_l == 'am' and hour == 12:
                        hour = 0
                try:
                    return datetime(year, month_num, day, hour, minute, tzinfo=VN_TZ)
                except ValueError:
                    pass

    # Case 3: Try python-dateutil fallback
    try:
        dt = dateutil.parser.parse(text_no_dow, fuzzy=True, dayfirst=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TZ)
        return dt
    except Exception:
        pass

    return None

def check_is_unopened(opens_at_str: str) -> Tuple[bool, Optional[datetime]]:
    """
    Checks whether an assignment is not yet opened based on its Opens datetime.
    Returns (is_unopened: bool, parsed_datetime: Optional[datetime]).
    If opens_dt > current Vietnam time, returns (True, opens_dt).
    """
    if not opens_at_str:
        return False, None
    
    dt = parse_moodle_datetime(opens_at_str)
    if not dt:
        # If string exists and explicitly states unopened or future keywords
        low = opens_at_str.lower()
        if any(w in low for w in ["chưa mở", "not yet open", "chưa tới"]):
            return True, None
        return False, None

    now = get_vietnam_now()
    is_unopened = dt > now
    return is_unopened, dt
