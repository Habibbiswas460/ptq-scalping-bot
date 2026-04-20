"""
PTQ Scalping Bot - Core Module
SMART SCALP v3.4

Organized into 4 sub-modules:
├── trading/  : Broker connection & order execution
├── engines/  : Entry/Exit signal engines & state machine  
├── risk/     : Risk management, Greeks & validation
└── services/ : Dashboard, Database, Telegram, Session
"""

# Main entry
from core.main import main

# Re-export from sub-modules for backwards compatibility
from core.trading import *
from core.engines import *
from core.risk import *
from core.services import *
