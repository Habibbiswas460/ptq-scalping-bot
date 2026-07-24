"""
PTQ Scalping Bot - Core Module
SMART SCALP v3.4

Organized into 4 sub-modules:
├── trading/  : Broker connection & order execution
├── engines/  : Entry/Exit signal engines & state machine  
├── risk/     : Risk management, Greeks & validation
└── services/ : Dashboard, Database, Telegram, Session
"""

from importlib import import_module
from typing import Any


def main(*args: Any, **kwargs: Any):
	"""Lazy proxy for core.main.main."""
	from core.main import main as _main

	return _main(*args, **kwargs)


def __getattr__(name: str) -> Any:
	"""Lazy lookup across core subpackages for backward compatibility."""
	for module_name in ("core.trading", "core.engines", "core.risk", "core.services"):
		module = import_module(module_name)
		if hasattr(module, name):
			return getattr(module, name)
	raise AttributeError(f"module 'core' has no attribute '{name}'")
