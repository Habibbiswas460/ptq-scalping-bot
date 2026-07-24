"""
Centralized environment configuration helpers.

This module is the single source for loading .env and parsing env values.
Other config modules (for example config.constants) should import helpers from
here to keep behavior consistent across the project.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv


# Resolve repository root reliably from config/ folder.
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"


def load_environment() -> None:
    """Load .env once for the current process if present."""
    # Do not override existing shell variables unless caller explicitly exports.
    if ENV_FILE.exists():
        load_dotenv(dotenv_path=ENV_FILE, override=False)
    else:
        load_dotenv(override=False)


def env_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment."""
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


def env_int(key: str, default: int = 0) -> int:
    """Get integer from environment."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def env_float(key: str, default: float = 0.0) -> float:
    """Get float from environment."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def env_str(key: str, default: str = "") -> str:
    """Get string from environment."""
    return os.getenv(key, default)


def parse_tsl_levels(levels_str: str) -> List[Tuple[int, int]]:
    """Parse TSL levels from comma-separated string.

    Format: "8:4,12:7,16:11" -> [(8, 4), (12, 7), (16, 11)]
    """
    if not levels_str:
        return [(8, 4), (12, 7), (16, 11), (20, 15), (25, 20), (30, 25), (40, 35), (50, 45)]

    levels: List[Tuple[int, int]] = []
    for pair in levels_str.split(","):
        if ":" in pair:
            profit, lock = pair.strip().split(":", 1)
            try:
                levels.append((int(profit), int(lock)))
            except ValueError:
                continue

    return levels if levels else [(8, 4), (12, 7), (16, 11), (20, 15)]


# Load env at import so all dependent modules see a consistent state.
load_environment()
