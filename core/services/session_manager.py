from datetime import datetime

def is_trading_session_allowed(SESSION_FILTER_ENABLED, DAY_TYPE, BLACKOUT_SESSIONS, EXPIRY_ONLY_SESSIONS, ALLOWED_SESSIONS):
    """Check if current time is in allowed trading session"""
    if not SESSION_FILTER_ENABLED:
        return True, "Session filter disabled"
    now = datetime.now()
    current_time_min = now.hour * 60 + now.minute
    for session in BLACKOUT_SESSIONS:
        start_min = session['start_hour'] * 60 + session['start_minute']
        end_min = session['end_hour'] * 60 + session['end_minute']
        if start_min <= current_time_min <= end_min:
            return False, f"Blackout: {session.get('reason', 'Restricted')}"
    if DAY_TYPE == "EXPIRY":
        for session in EXPIRY_ONLY_SESSIONS:
            start_min = session['start_hour'] * 60 + session['start_minute']
            end_min = session['end_hour'] * 60 + session['end_minute']
            if start_min <= current_time_min <= end_min:
                return True, "Expiry session"
    for session in ALLOWED_SESSIONS:
        start_min = session['start_hour'] * 60 + session['start_minute']
        end_min = session['end_hour'] * 60 + session['end_minute']
        if start_min <= current_time_min <= end_min:
            return True, "Allowed session"
    return False, "Outside trading hours"


# Legacy alias for backward compatibility
def is_session_allowed(session_filter_enabled=True, day_type="NORMAL", 
                       blackout_sessions=None, expiry_only_sessions=None, 
                       allowed_sessions=None):
    """Wrapper for is_trading_session_allowed with default parameters"""
    from config.constants import (
        SESSION_FILTER_ENABLED, BLACKOUT_SESSIONS, 
        EXPIRY_ONLY_SESSIONS, ALLOWED_SESSIONS
    )
    return is_trading_session_allowed(
        session_filter_enabled if session_filter_enabled is not None else SESSION_FILTER_ENABLED,
        day_type,
        blackout_sessions if blackout_sessions is not None else BLACKOUT_SESSIONS,
        expiry_only_sessions if expiry_only_sessions is not None else EXPIRY_ONLY_SESSIONS,
        allowed_sessions if allowed_sessions is not None else ALLOWED_SESSIONS
    )
