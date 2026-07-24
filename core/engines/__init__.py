"""Engines package (lazy exports).

Importing this package should not eagerly load all engines, because some
modules (like entry_engine) pull in runtime-only dependencies such as DB.
"""

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
    for module_name in (
        "core.engines.entry_engine",
        "core.engines.exit_engine",
        "core.engines.state_machine",
        "core.engines.position_size_engine",
        "core.engines.market_quality_engine",
        "core.engines.weighted_score_engine",
        "core.engines.adaptive_confidence_engine",
    ):
        module = import_module(module_name)
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module 'core.engines' has no attribute '{name}'")
