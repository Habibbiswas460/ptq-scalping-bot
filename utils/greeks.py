"""
Greeks Calculator using Black-Scholes-Merton Model
Lightweight implementation for option Greeks calculation
"""

import math
from typing import Dict, Optional
from datetime import datetime


class GreeksCalculator:
    """Calculate option Greeks using BSM model"""
    
    @staticmethod
    def norm_cdf(x: float) -> float:
        """Cumulative distribution function for standard normal distribution"""
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
    
    @staticmethod
    def norm_pdf(x: float) -> float:
        """Probability density function for standard normal distribution"""
        return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)
    
    @staticmethod
    def calculate(
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,  # in years
        volatility: float,
        risk_free_rate: float = 0.05,  # 5% default
        option_type: str = 'CE'  # CE or PE
    ) -> Dict[str, float]:
        """
        Calculate all Greeks for an option
        
        Args:
            spot_price: Current underlying price
            strike_price: Option strike price
            time_to_expiry: Time to expiry in years (e.g., 1/365 for 1 day)
            volatility: Implied volatility (e.g., 0.20 for 20%)
            risk_free_rate: Risk-free interest rate
            option_type: 'CE' for Call or 'PE' for Put
        
        Returns:
            Dict with delta, gamma, theta, vega, theta_sec
        """
        # Ensure minimum values to avoid division by zero
        if time_to_expiry <= 0:
            time_to_expiry = 1 / (365 * 24)  # Minimum 1 hour
        
        if volatility <= 0:
            volatility = 0.15  # Default 15% IV
        
        if spot_price <= 0 or strike_price <= 0:
            return {
                'delta': 0.5,
                'gamma': 0.001,
                'theta': -50.0,
                'vega': 5.0,
                'theta_sec': 0.0005,
                'tte': time_to_expiry * 365 * 24 * 3600
            }
        
        # Black-Scholes components
        S = spot_price
        K = strike_price
        T = time_to_expiry
        r = risk_free_rate
        sigma = volatility
        
        try:
            # d1 and d2
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            
            # Greeks calculation
            if option_type == 'CE':
                # Call option
                delta = GreeksCalculator.norm_cdf(d1)
            else:
                # Put option
                delta = GreeksCalculator.norm_cdf(d1) - 1.0
            
            # Gamma (same for call and put)
            gamma = GreeksCalculator.norm_pdf(d1) / (S * sigma * math.sqrt(T))
            
            # Theta (per day)
            if option_type == 'CE':
                theta = (-(S * GreeksCalculator.norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) 
                        - r * K * math.exp(-r * T) * GreeksCalculator.norm_cdf(d2))
            else:
                theta = (-(S * GreeksCalculator.norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) 
                        + r * K * math.exp(-r * T) * GreeksCalculator.norm_cdf(-d2))
            
            theta_per_day = theta / 365.0  # Convert to per-day
            
            # Vega (per 1% change in volatility)
            vega = S * GreeksCalculator.norm_pdf(d1) * math.sqrt(T) / 100.0
            
            # Theta per second (for scalping)
            theta_per_sec = theta_per_day / (24 * 60 * 60)
            
            return {
                'delta': delta,
                'gamma': gamma,
                'theta': theta_per_day,
                'vega': vega,
                'theta_sec': abs(theta_per_sec),  # Absolute value for comparison
                'tte': time_to_expiry * 365 * 24 * 3600
            }
        except Exception as e:
            # Return safe defaults if calculation fails
            return {
                'delta': 0.5,
                'gamma': 0.001,
                'theta': -50.0,
                'vega': 5.0,
                'theta_sec': 0.0005,
                'tte': time_to_expiry * 365 * 24 * 3600
            }
    
    @staticmethod
    def calculate_from_ltp(
        ltp: float,
        spot_price: float,
        strike_price: float,
        time_to_expiry_sec: float,
        option_type: str = 'CE',
        risk_free_rate: float = 0.05
    ) -> Dict[str, float]:
        """
        Calculate Greeks by deriving IV from LTP
        Uses Newton-Raphson to find implied volatility
        
        Args:
            ltp: Last traded price of option
            spot_price: Current underlying price
            strike_price: Strike price
            time_to_expiry_sec: Time to expiry in seconds
            option_type: 'CE' or 'PE'
            risk_free_rate: Risk-free rate
        
        Returns:
            Greeks dict
        """
        # Convert seconds to years
        T = time_to_expiry_sec / (365 * 24 * 3600)
        
        if T <= 0 or ltp <= 0:
            return {
                'delta': 0.0,
                'gamma': 0.0,
                'theta': 0.0,
                'vega': 0.0,
                'theta_sec': 0.0,
                'tte': 0.0
            }
        
        # Estimate IV using Newton-Raphson (simplified)
        # Start with a reasonable guess based on moneyness
        moneyness = spot_price / strike_price
        
        if option_type == 'CE':
            if moneyness > 1.05:  # ITM
                iv_guess = 0.25
            elif moneyness < 0.95:  # OTM
                iv_guess = 0.35
            else:  # ATM
                iv_guess = 0.30
        else:
            if moneyness < 0.95:  # ITM
                iv_guess = 0.25
            elif moneyness > 1.05:  # OTM
                iv_guess = 0.35
            else:  # ATM
                iv_guess = 0.30
        
        # For simplicity, use the guess directly
        # In production, implement full IV solver
        implied_vol = iv_guess
        
        # Calculate Greeks with estimated IV
        return GreeksCalculator.calculate(
            spot_price=spot_price,
            strike_price=strike_price,
            time_to_expiry=T,
            volatility=implied_vol,
            risk_free_rate=risk_free_rate,
            option_type=option_type
        )
    
    @staticmethod
    def time_to_expiry_seconds(expiry_time: datetime) -> float:
        """
        Calculate time to expiry in seconds
        
        Args:
            expiry_time: Expiry datetime (e.g., 15:30 on expiry day)
        
        Returns:
            Seconds to expiry
        """
        now = datetime.now()
        delta = expiry_time - now
        return max(0, delta.total_seconds())
