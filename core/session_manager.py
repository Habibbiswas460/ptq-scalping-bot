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
"""
Handles session and timing logic for PTQ Scalping Bot
"""
# Example stub for session management

def is_session_allowed(...):
    # Implement session/time checks here
    pass

# Add more session-related functions/classes as needed
