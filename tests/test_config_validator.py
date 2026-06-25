import os
from pathlib import Path

from config.validator import ConfigValidator

CONFIG_ENV_KEYS = [
    'PAPER_TRADING', 'USE_LIVE_DATA', 'ENABLE_WEBSOCKET',
    'TOTAL_CAPITAL', 'SL_POINTS', 'TP_POINTS',
    'MAX_TRADES_PER_DAY', 'MAX_TRADES_PER_HOUR',
    'MAX_DAILY_LOSS',
    'ANGEL_API_KEY', 'ANGEL_CLIENT_ID',
    'ANGEL_PASSWORD', 'ANGEL_TOTP_SECRET',
]


def clear_config_env(monkeypatch):
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_validate_config_paper_trading_allows_missing_creds(tmp_path, monkeypatch):
    clear_config_env(monkeypatch)
    env_path = tmp_path / '.env'
    env_path.write_text(
        """
PAPER_TRADING=true
USE_LIVE_DATA=false
SL_POINTS=6
TP_POINTS=12
TOTAL_CAPITAL=30000
MAX_DAILY_LOSS=1500
"""
    )

    validator = ConfigValidator(str(env_path))
    is_valid, errors, warnings = validator.validate(auto_fix=False)

    assert is_valid is True
    assert errors == []
    assert any('MISSING' in warning for warning in warnings)


def test_validate_config_live_requires_credentials(tmp_path, monkeypatch):
    clear_config_env(monkeypatch)
    env_path = tmp_path / '.env'
    env_path.write_text(
        """
PAPER_TRADING=false
USE_LIVE_DATA=true
SL_POINTS=6
TP_POINTS=12
TOTAL_CAPITAL=30000
MAX_DAILY_LOSS=1500
"""
    )

    validator = ConfigValidator(str(env_path))
    is_valid, errors, warnings = validator.validate(auto_fix=False)

    assert is_valid is False
    assert any('ANGEL_API_KEY' in err for err in errors)
    assert any('ANGEL_CLIENT_ID' in err for err in errors)
    assert any('ANGEL_PASSWORD' in err for err in errors)
    assert any('ANGEL_TOTP_SECRET' in err for err in errors)


def test_validate_config_auto_fix_writes_defaults(tmp_path, monkeypatch):
    clear_config_env(monkeypatch)
    env_path = tmp_path / '.env'
    env_path.write_text(
        """
PAPER_TRADING=true
USE_LIVE_DATA=false
TOTAL_CAPITAL=30000
SL_POINTS=6
TP_POINTS=12
"""
    )

    validator = ConfigValidator(str(env_path))
    is_valid, errors, warnings = validator.validate(auto_fix=True)

    assert is_valid is True
    assert env_path.exists()
    contents = env_path.read_text()
    assert 'PAPER_TRADING=true' in contents
    assert 'USE_LIVE_DATA=false' in contents
    assert 'ENABLE_WEBSOCKET=true' in contents
    assert 'MAX_TRADES_PER_DAY=15' in contents
