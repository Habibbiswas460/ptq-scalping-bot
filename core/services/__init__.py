"""Services package (lazy exports).

Avoid eager imports here so importing ``core.services.*`` modules does not
automatically initialize heavyweight services like SQLite database.
"""

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
    for module_name in (
        "core.services.database",
        "core.services.telegram_bot",
        "core.services.session_manager",
        "core.services.mode_switch",
    ):
        module = import_module(module_name)
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module 'core.services' has no attribute '{name}'")
