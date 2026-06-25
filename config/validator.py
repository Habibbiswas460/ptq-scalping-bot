"""
PTQ Scalping Bot - Configuration Validator
Validates .env settings at startup with warnings and auto-fixes
"""

import os
from typing import Dict, List, Tuple, Optional
from dotenv import load_dotenv


class ConfigValidationError(Exception):
    """Critical configuration error that prevents bot from starting"""
    pass


class ConfigValidator:
    """Validates and optionally fixes .env configuration"""
    
    # Required settings (critical - bot won't start without these)
    REQUIRED_SETTINGS = {
        'ANGEL_API_KEY': 'Angel One API key is required for trading',
        'ANGEL_CLIENT_ID': 'Angel One client ID is required',
        'ANGEL_PASSWORD': 'Angel One PIN/password is required',
        'ANGEL_TOTP_SECRET': 'Angel One TOTP secret is required for login',
    }
    
    # Recommended settings with defaults
    RECOMMENDED_SETTINGS = {
        'PAPER_TRADING': ('true', 'Paper trading recommended for testing'),
        'USE_LIVE_DATA': ('true', 'Live data recommended for accurate signals'),
        'ENABLE_WEBSOCKET': ('true', 'WebSocket recommended for low latency'),
        'TOTAL_CAPITAL': ('30000', 'Capital should be set'),
        'SL_POINTS': ('6', 'Stop loss should be configured'),
        'TP_POINTS': ('12', 'Take profit should be configured'),
        'MAX_TRADES_PER_DAY': ('15', 'Max trades per day recommended'),
        'MAX_TRADES_PER_HOUR': ('10', 'Max trades per hour recommended'),
    }
    
    # Value ranges for validation
    VALUE_RANGES = {
        'TOTAL_CAPITAL': (10000, 1000000, 'Capital should be between ₹10,000 and ₹10,00,000'),
        'SL_POINTS': (3, 50, 'Stop loss should be between 3 and 50 points'),
        'TP_POINTS': (5, 100, 'Take profit should be between 5 and 100 points'),
        'CE_QUANTITY': (1, 1000, 'CE quantity should be between 1 and 1000'),
        'PE_QUANTITY': (1, 1000, 'PE quantity should be between 1 and 1000'),
        'KILL_SWITCH_LATENCY_MS': (100, 1000, 'Latency threshold should be 100-1000ms'),
        'SPREAD_LIMIT_PCT': (0.1, 5.0, 'Spread limit should be 0.1-5.0%'),
        'MAX_DAILY_LOSS': (1000, 100000, 'Max daily loss should be ₹1,000 to ₹1,00,000'),
    }
    
    def __init__(self, env_path: str = '.env'):
        self.env_path = env_path
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.fixes_applied: List[str] = []
        self._env_vars: Dict[str, str] = {}
        
    def load_env(self):
        """Load environment variables"""
        load_dotenv(self.env_path, override=True)
        
        # Read .env file directly for validation and auto-fix
        if os.path.exists(self.env_path):
            with open(self.env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        self._env_vars[key.strip()] = value.strip()
                        os.environ[key.strip()] = value.strip()

    def get_env_value(self, key: str, default: str = '') -> str:
        """Get configuration value from parsed .env or from process environment."""
        return self._env_vars.get(key, os.getenv(key, default))
    
    def validate(self, auto_fix: bool = False) -> Tuple[bool, List[str], List[str]]:
        """
        Validate all configuration settings.
        
        Args:
            auto_fix: If True, automatically fix missing/invalid settings
            
        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []
        self.fixes_applied = []
        
        self.load_env()
        
        # Check required settings
        self._validate_required()
        
        # Check recommended settings
        self._validate_recommended(auto_fix)
        
        # Check value ranges
        self._validate_ranges(auto_fix)
        
        # Check logical consistency
        self._validate_consistency()
        
        # Write fixes if any were applied
        if self.fixes_applied and auto_fix:
            self._write_fixes()
        
        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings
    
    def _validate_required(self):
        """Validate required settings"""
        paper = self.get_env_value('PAPER_TRADING', 'true').lower() == 'true'
        if paper:
            return

        for key, message in self.REQUIRED_SETTINGS.items():
            value = self.get_env_value(key, '')
            if not value or value in (
                '',
                'your_api_key',
                'your_client_id',
                'your_password',
                'your_totp_secret',
                'your_api_key_here',
                'your_client_id_here',
            ):
                self.errors.append(f"❌ MISSING: {key} - {message}")
    
    def _validate_recommended(self, auto_fix: bool):
        """Validate recommended settings"""
        for key, (default, message) in self.RECOMMENDED_SETTINGS.items():
            value = self.get_env_value(key, '')
            if not value:
                self.warnings.append(f"⚠️  MISSING: {key} - {message}")
                if auto_fix:
                    self._env_vars[key] = default
                    self.fixes_applied.append(f"Set {key}={default}")
    
    def _validate_ranges(self, auto_fix: bool):
        """Validate value ranges"""
        for key, (min_val, max_val, message) in self.VALUE_RANGES.items():
            value_str = self.get_env_value(key, '')
            if value_str:
                try:
                    value = float(value_str)
                    if value < min_val:
                        self.warnings.append(f"⚠️  LOW VALUE: {key}={value} - {message}")
                        if auto_fix:
                            self._env_vars[key] = str(min_val)
                            self.fixes_applied.append(f"Set {key}={min_val} (was {value})")
                    elif value > max_val:
                        self.warnings.append(f"⚠️  HIGH VALUE: {key}={value} - {message}")
                        if auto_fix:
                            self._env_vars[key] = str(max_val)
                            self.fixes_applied.append(f"Set {key}={max_val} (was {value})")
                except ValueError:
                    self.warnings.append(f"⚠️  INVALID: {key}={value_str} - Should be a number")
    
    def _validate_consistency(self):
        """Validate logical consistency between settings"""
        # Paper trading with live credentials check
        paper = self.get_env_value('PAPER_TRADING', 'true').lower() == 'true'
        has_creds = bool(self.get_env_value('ANGEL_API_KEY', ''))
        
        if not paper and not has_creds:
            self.errors.append("❌ Live trading enabled but no broker credentials configured!")
        
        # Stop loss vs take profit
        sl = float(self.get_env_value('SL_POINTS', '6') or '6')
        tp = float(self.get_env_value('TP_POINTS', '12') or '12')
        if tp <= sl:
            self.warnings.append(f"⚠️  Risk/Reward: TP ({tp}) should be greater than SL ({sl})")
        
        # Capital vs max loss
        capital = float(self.get_env_value('TOTAL_CAPITAL', '30000') or '30000')
        max_loss = float(self.get_env_value('MAX_DAILY_LOSS', '25000') or '25000')
        if max_loss > capital * 0.5:
            self.warnings.append(
                f"⚠️  Max daily loss (₹{max_loss:,.0f}) is more than 50% of capital (₹{capital:,.0f})"
            )
    
    def _write_fixes(self):
        """Write auto-fixes to .env file"""
        if not os.path.exists(self.env_path):
            return
        
        lines = []
        with open(self.env_path, 'r') as f:
            lines = f.readlines()
        
        # Update existing lines
        updated_keys = set()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and '=' in stripped:
                key = stripped.split('=', 1)[0].strip()
                if key in self._env_vars:
                    lines[i] = f"{key}={self._env_vars[key]}\n"
                    updated_keys.add(key)
        
        # Add new keys
        for key, value in self._env_vars.items():
            if key not in updated_keys:
                lines.append(f"\n{key}={value}\n")
        
        with open(self.env_path, 'w') as f:
            f.writelines(lines)
    
    def print_report(self):
        """Print validation report"""
        print("\n" + "=" * 60)
        print("📋 CONFIGURATION VALIDATION REPORT")
        print("=" * 60)
        
        if self.errors:
            print("\n🔴 ERRORS (must fix before running):")
            for error in self.errors:
                print(f"   {error}")
        
        if self.warnings:
            print("\n🟡 WARNINGS (recommended to fix):")
            for warning in self.warnings:
                print(f"   {warning}")
        
        if self.fixes_applied:
            print("\n🔧 AUTO-FIXES APPLIED:")
            for fix in self.fixes_applied:
                print(f"   ✓ {fix}")
        
        if not self.errors and not self.warnings:
            print("\n✅ All configuration settings are valid!")
        
        print("\n" + "=" * 60)


def validate_config(auto_fix: bool = False) -> bool:
    """
    Validate configuration at startup.
    
    Args:
        auto_fix: Automatically fix minor issues
        
    Returns:
        True if configuration is valid, False otherwise
    """
    validator = ConfigValidator()
    is_valid, errors, warnings = validator.validate(auto_fix=auto_fix)
    validator.print_report()
    
    return is_valid


def validate_config_quiet() -> Tuple[bool, List[str], List[str]]:
    """Validate without printing (for programmatic use)"""
    validator = ConfigValidator()
    return validator.validate(auto_fix=False)


if __name__ == '__main__':
    import sys
    auto_fix = '--fix' in sys.argv
    is_valid = validate_config(auto_fix=auto_fix)
    sys.exit(0 if is_valid else 1)
