"""
Custom exceptions for the Angel One client.
"""

class AngelOneError(Exception):
    """Base exception class for Angel One client errors."""
    pass

class AngelOneLoginError(AngelOneError):
    """Raised when login to the Angel One API fails."""
    pass

class AngelOneApiError(AngelOneError):
    """Raised when an API call returns an error."""
    pass

class AngelOneOrderError(AngelOneApiError):
    """Raised for order placement or modification errors."""
    pass
