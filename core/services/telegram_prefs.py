"""Runtime-toggleable Telegram preferences.

The TELEGRAM_NOTIFY_* settings existed in config and .env but nothing ever read them, so
switching one off had no effect. They are now real, and changeable from the Telegram menu
without a restart, which is why they need somewhere to live outside the process.

`.env` still supplies the defaults; this file only stores what the user has since changed, so
an untouched install behaves exactly as its .env says.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

from config.constants import (
    TELEGRAM_NOTIFY_ENTRIES,
    TELEGRAM_NOTIFY_EXITS,
    TELEGRAM_NOTIFY_KILL_SWITCH,
    TELEGRAM_DAILY_SUMMARY,
    TELEGRAM_HEARTBEAT,
    TELEGRAM_HEARTBEAT_MIN,
)

PREFS_PATH = os.path.join('data', 'telegram_prefs.json')

# key -> (label shown in the menu, default from .env)
SCHEMA: Dict[str, tuple] = {
    'notify_entries':    ('Entry alerts',      TELEGRAM_NOTIFY_ENTRIES),
    'notify_exits':      ('Exit alerts',       TELEGRAM_NOTIFY_EXITS),
    'notify_kill':       ('Kill-switch alerts', TELEGRAM_NOTIFY_KILL_SWITCH),
    'daily_summary':     ('Daily summary',     TELEGRAM_DAILY_SUMMARY),
    'notify_errors':     ('Error alerts',      True),
    'heartbeat':         ('Heartbeat',         TELEGRAM_HEARTBEAT),
}

# heartbeat interval is a number, not a toggle
INTERVAL_KEY = 'heartbeat_min'
INTERVAL_CHOICES = (1, 5, 15, 30, 60)
# An out-of-range .env value would otherwise leave the menu's cycle button stuck, since it
# steps through INTERVAL_CHOICES by index.
INTERVAL_DEFAULT = (TELEGRAM_HEARTBEAT_MIN
                    if TELEGRAM_HEARTBEAT_MIN in INTERVAL_CHOICES else 15)


class TelegramPrefs:
    """Small JSON-backed preference store. Never raises into the caller: a broken or
    unwritable prefs file must not take the trading bot down, so every failure falls back
    to the .env defaults."""

    def __init__(self, path: str = PREFS_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._values: Dict[str, Any] = {k: v[1] for k, v in SCHEMA.items()}
        self._values[INTERVAL_KEY] = INTERVAL_DEFAULT
        self.load()

    # ── persistence ──────────────────────────────────────────────────────
    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, 'r') as f:
                    stored = json.load(f)
                if isinstance(stored, dict):
                    for k, v in stored.items():
                        if k in SCHEMA and isinstance(v, bool):
                            self._values[k] = v
                        elif k == INTERVAL_KEY and isinstance(v, int) and v > 0:
                            self._values[k] = v
        except Exception:
            pass          # keep the .env defaults

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, 'w') as f:
                json.dump(self._values, f, indent=2, sort_keys=True)
            os.replace(tmp, self.path)      # atomic, so a crash cannot leave a half file
            return True
        except Exception:
            return False

    # ── access ───────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def toggle(self, key: str) -> bool:
        """Flip a boolean preference and persist. Returns the new value."""
        if key not in SCHEMA:
            return False
        with self._lock:
            self._values[key] = not bool(self._values.get(key))
            new = self._values[key]
        self.save()
        return new

    def cycle_interval(self) -> int:
        """Step the heartbeat interval to the next supported value and persist."""
        with self._lock:
            cur = self._values.get(INTERVAL_KEY, INTERVAL_DEFAULT)
            try:
                nxt = INTERVAL_CHOICES[(INTERVAL_CHOICES.index(cur) + 1) % len(INTERVAL_CHOICES)]
            except ValueError:
                nxt = INTERVAL_DEFAULT
            self._values[INTERVAL_KEY] = nxt
        self.save()
        return nxt

    def as_dict(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._values)
