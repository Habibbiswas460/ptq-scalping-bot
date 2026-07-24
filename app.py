"""
PTQ Scalping Bot - Entry Point
All logic is in core/main.py
"""

# ============================================================================
# SUPPRESS VERBOSE SMARTAPI SDK OUTPUT
# The SmartAPI SDK has extremely verbose logging that prints every symbol
# during searchScrip calls. This must be suppressed before any imports.
# ============================================================================
import logging
import sys
import os
import re


class _RedactingStream:
    """Redact known sensitive fields from any SDK/std streams."""

    _PATTERNS = [
        re.compile(r"(?i)(password['\"]?\s*[:=]\s*['\"]?)([^'\",}\s]+)"),
        re.compile(r"(?i)(totp['\"]?\s*[:=]\s*['\"]?)([^'\",}\s]+)"),
        re.compile(r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?)([^'\",}\s]+)"),
        re.compile(r"(?i)(refresh[_-]?token['\"]?\s*[:=]\s*['\"]?)([^'\",}\s]+)"),
        re.compile(r"(?i)(jwt[_-]?token['\"]?\s*[:=]\s*['\"]?)([^'\",}\s]+)"),
        re.compile(r"(?i)(X-PrivateKey['\"]?\s*[:=]\s*['\"]?)([^'\",}\s]+)"),
    ]

    def __init__(self, wrapped):
        self._wrapped = wrapped

    def write(self, data):
        if not isinstance(data, str):
            return self._wrapped.write(data)
        redacted = data
        for pat in self._PATTERNS:
            redacted = pat.sub(r"\1[REDACTED]", redacted)
        return self._wrapped.write(redacted)

    def flush(self):
        return self._wrapped.flush()

    def isatty(self):
        return self._wrapped.isatty()

    def fileno(self):
        return self._wrapped.fileno()


# Install stream redaction first so third-party SDK stderr prints are scrubbed.
sys.stdout = _RedactingStream(sys.stdout)
sys.stderr = _RedactingStream(sys.stderr)

# Method 1: Disable all SDK loggers
for logger_name in ['SmartApi', 'smartConnect', 'smartapi', 'SmartApi.smartConnect', 
                    'urllib3', 'requests', 'websocket', 'root']:
    sdk_logger = logging.getLogger(logger_name)
    sdk_logger.setLevel(logging.CRITICAL)  # Only show critical errors
    sdk_logger.handlers = []
    sdk_logger.addHandler(logging.NullHandler())
    sdk_logger.propagate = False

# Method 2: Set environment variable to suppress (some SDKs respect this)
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

# Method 3: Override the global logging config
logging.basicConfig(level=logging.CRITICAL)

from config.constants import PAPER_TRADING
from config.validator import validate_config_quiet
from core.main import run_with_auto_reconnect

if __name__ == "__main__":
    is_valid, errors, warnings = validate_config_quiet()
    if warnings:
        for warning in warnings:
            print(warning)
    if not is_valid:
        for error in errors:
            print(error)
        sys.exit(1)

    run_with_auto_reconnect()
