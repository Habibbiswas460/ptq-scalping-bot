"""
PTQ Scalping Bot - Greeks Calculator Interface
Wrapper for Greeks calculation
"""

from datetime import datetime, timedelta
from typing import Dict

from utils.greeks import GreeksCalculator
from config.constants import CONFIG


def calculate_greeks(tick: Dict, spot_price: float, current_strike: int,
                     expiry_time: datetime = None) -> Dict[str, float]:
    """
    Calculate option Greeks using BSM model
    """
    # Ensure valid values
    if not spot_price or spot_price <= 0:
        spot_price = tick.get('spot_price', tick['ltp'] * 100)
    
    if not current_strike or current_strike <= 0:
        current_strike = round(spot_price / 100) * 100
    
    if not expiry_time:
        # Default to next Thursday 15:30
        now = datetime.now()
        days_ahead = 3 - now.weekday()  # Thursday
        if days_ahead <= 0:
            days_ahead += 7
        expiry_time = now.replace(hour=15, minute=30, second=0, microsecond=0) + timedelta(days=days_ahead)
    
    # Calculate time to expiry
    tte_sec = GreeksCalculator.time_to_expiry_seconds(expiry_time)
    
    # Ensure minimum time to expiry
    if tte_sec <= 0:
        tte_sec = 3600  # Default 1 hour
    
    # Use Greeks calculator
    try:
        greeks = GreeksCalculator.calculate_from_ltp(
            ltp=tick['ltp'],
            spot_price=spot_price,
            strike_price=current_strike,
            time_to_expiry_sec=tte_sec,
            option_type=CONFIG['trading']['option_type']
        )
        return greeks
    except Exception:
        # Return safe default Greeks if calculation fails
        return {
            'delta': 0.5,
            'gamma': 0.001,
            'theta': -50.0,
            'vega': 5.0,
            'theta_sec': 0.0005,
            'tte': tte_sec
        }
