import time
from datetime import datetime

def current_time_ms():
    """Current timestamp in milliseconds"""
    return int(time.time() * 1000)

def now():
    """Current datetime"""
    return datetime.now()

def cooldown_seconds(DAY_TYPE, COOLDOWN_EXPIRY_SEC, COOLDOWN_NORMAL_SEC):
    """Get cooldown duration based on day type"""
    return COOLDOWN_EXPIRY_SEC if DAY_TYPE == "EXPIRY" else COOLDOWN_NORMAL_SEC

def is_expiry_date():
    """Check if today is expiry date
    Normal: Thursday
    Special: Jan 27, 2026 (Republic Day shifts expiry from Jan 30 to Jan 27)
    """
    now = datetime.now()
    if now.month == 1 and 22 <= now.day <= 26:
        return False
    if now.month == 1 and now.day == 27:
        return True
    return now.weekday() == 3

def market_open(TEST_MODE):
    """Check if market is open"""
    if TEST_MODE:
        return True
    now = datetime.now()
    market_start = now.replace(hour=9, minute=15, second=0)
    market_end = now.replace(hour=15, minute=30, second=0)
    return market_start <= now <= market_end
