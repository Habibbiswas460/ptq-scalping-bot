"""
Greeks Validator - Cross-validate BSM vs Broker API Greeks
Purpose: Detect when Greeks model diverges from reality
"""

from typing import Dict, Optional, Tuple
from datetime import datetime
import logging

from utils.greeks import GreeksCalculator
from core.risk.greeks_calc import GreeksFetcher


class GreeksValidator:
    """
    Validate Greeks consistency between BSM model and broker API.
    Flags divergence when difference > threshold (delta 5%, gamma 10%, theta 20%)
    """
    
    def __init__(self, broker_client=None):
        self.bsm_calc = GreeksCalculator()
        self.api_fetcher = GreeksFetcher(broker_client)
        self.divergence_log = []
        self.validation_enabled = True
        
        # Thresholds for divergence detection
        self.delta_threshold = 0.05      # 5% difference
        self.gamma_threshold = 0.10      # 10% difference  
        self.theta_threshold = 0.20      # 20% difference (most volatile)
        self.vega_threshold = 0.15       # 15% difference
        
        self.logger = logging.getLogger(__name__)
    
    def get_bsm_greeks(self, spot: float, strike: float, tte_sec: float, 
                       iv: float = 0.20, option_type: str = 'CE') -> Dict:
        """Calculate greeks using BSM model"""
        try:
            tte_years = tte_sec / (365.25 * 24 * 3600)
            greeks = self.bsm_calc.calculate(
                spot_price=spot,
                strike_price=strike,
                time_to_expiry=tte_years,
                volatility=iv,
                option_type=option_type
            )
            return greeks
        except Exception as e:
            self.logger.error(f"BSM calculation failed: {e}")
            return {}
    
    def get_api_greeks(self, underlying: str = "NIFTY", strike: int = None) -> Optional[Dict]:
        """Try to fetch Greeks from broker API"""
        try:
            return self.api_fetcher.fetch_from_api(underlying, strike)
        except Exception as e:
            self.logger.debug(f"API Greeks fetch failed: {e}")
            return None
    
    def compare_greeks(self, bsm: Dict, api: Dict) -> Dict[str, Tuple[float, bool]]:
        """
        Compare BSM vs API Greeks.
        
        Returns:
            {greek_name: (difference_pct, is_divergent)}
        """
        results = {}
        
        if not bsm or not api:
            return results
        
        # Delta comparison
        if 'delta' in bsm and 'delta' in api:
            delta_diff = abs(bsm['delta'] - api['delta']) / max(abs(bsm['delta']), 0.01)
            is_div = delta_diff > self.delta_threshold
            results['delta'] = (delta_diff, is_div)
        
        # Gamma comparison
        if 'gamma' in bsm and 'gamma' in api:
            gamma_diff = abs(bsm['gamma'] - api['gamma']) / max(abs(bsm['gamma']), 0.001)
            is_div = gamma_diff > self.gamma_threshold
            results['gamma'] = (gamma_diff, is_div)
        
        # Theta comparison
        if 'theta' in bsm and 'theta' in api:
            theta_diff = abs(bsm['theta'] - api['theta']) / max(abs(bsm['theta']), 1.0)
            is_div = theta_diff > self.theta_threshold
            results['theta'] = (theta_diff, is_div)
        
        # Vega comparison
        if 'vega' in bsm and 'vega' in api:
            vega_diff = abs(bsm['vega'] - api['vega']) / max(abs(bsm['vega']), 0.1)
            is_div = vega_diff > self.vega_threshold
            results['vega'] = (vega_diff, is_div)
        
        return results
    
    def validate_greeks(self, spot: float, strike: float, tte_sec: float,
                       iv: float = 0.20, option_type: str = 'CE',
                       underlying: str = "NIFTY") -> Dict:
        """
        Full Greeks validation: BSM vs API comparison.
        
        Returns:
            {
                'bsm': {...greeks},
                'api': {...greeks or None},
                'divergences': {greek: (diff%, is_div)},
                'verdict': 'OK' | 'WARNING' | 'ERROR'
            }
        """
        if not self.validation_enabled:
            return {'verdict': 'DISABLED'}
        
        result = {
            'timestamp': datetime.now().isoformat(),
            'spot': spot,
            'strike': strike,
            'tte_sec': tte_sec,
            'option_type': option_type
        }
        
        # Get BSM greeks
        bsm = self.get_bsm_greeks(spot, strike, tte_sec, iv, option_type)
        result['bsm'] = bsm
        
        # Try to get API greeks
        api = self.get_api_greeks(underlying, strike)
        result['api'] = api
        
        # Compare if both available
        if api:
            divergences = self.compare_greeks(bsm, api)
            result['divergences'] = divergences
            
            # Determine verdict
            div_count = sum(1 for _, (_, is_div) in divergences.items() if is_div)
            
            if div_count == 0:
                result['verdict'] = 'OK'
            elif div_count == 1:
                result['verdict'] = 'WARNING'
            else:
                result['verdict'] = 'ERROR'
            
            # Log divergences
            if div_count > 0:
                self.divergence_log.append(result)
                self.logger.warning(
                    f"Greeks divergence detected: {divergences}\n"
                    f"  BSM: delta={bsm.get('delta', 0):.3f}, theta={bsm.get('theta', 0):.2f}\n"
                    f"  API: delta={api.get('delta', 0):.3f}, theta={api.get('theta', 0):.2f}"
                )
        else:
            result['divergences'] = {}
            result['verdict'] = 'API_UNAVAILABLE'
        
        return result
    
    def get_reliable_greeks(self, spot: float, strike: float, tte_sec: float,
                           iv: float = 0.20, option_type: str = 'CE',
                           underlying: str = "NIFTY") -> Dict:
        """
        Get greeks with confidence level.
        Uses API if available and consistent with BSM, otherwise falls back to BSM.
        
        Returns:
            {
                'delta': float,
                'gamma': float,
                'theta': float,
                'vega': float,
                'source': 'BSM' | 'API' | 'BLEND',
                'confidence': 0.0-1.0
            }
        """
        validation = self.validate_greeks(spot, strike, tte_sec, iv, option_type, underlying)
        
        bsm = validation.get('bsm', {})
        api = validation.get('api', {})
        divergences = validation.get('divergences', {})
        verdict = validation.get('verdict', 'ERROR')
        
        # Decision logic
        if verdict == 'OK':
            # API is consistent with BSM - use API with high confidence
            result = api.copy()
            result['source'] = 'API'
            result['confidence'] = 0.95
        elif verdict == 'WARNING':
            # One divergence - use BSM with caution
            result = bsm.copy()
            result['source'] = 'BSM_CAUTION'
            result['confidence'] = 0.70
        elif verdict == 'ERROR':
            # Multiple divergences - use BSM, flag warning
            result = bsm.copy()
            result['source'] = 'BSM_WARNING'
            result['confidence'] = 0.50
        else:
            # API unavailable - pure BSM
            result = bsm.copy()
            result['source'] = 'BSM'
            result['confidence'] = 0.80
        
        return result
    
    def get_divergence_report(self) -> str:
        """Generate report of all detected divergences"""
        if not self.divergence_log:
            return "No divergences detected."
        
        report = f"Greeks Divergence Report ({len(self.divergence_log)} events):\n"
        for entry in self.divergence_log[-10:]:  # Last 10
            report += f"\n{entry['timestamp']} - Strike {entry['strike']}\n"
            for greek, (diff, is_div) in entry.get('divergences', {}).items():
                status = "🔴 DIV" if is_div else "✓"
                report += f"  {greek}: {diff*100:.1f}% {status}\n"
        
        return report


# Global validator instance
_validator = None

def init_greeks_validator(broker_client=None):
    """Initialize global validator"""
    global _validator
    _validator = GreeksValidator(broker_client)
    return _validator

def validate_greeks(spot: float, strike: float, tte_sec: float,
                   iv: float = 0.20, option_type: str = 'CE',
                   underlying: str = "NIFTY") -> Dict:
    """Validate Greeks globally"""
    if _validator is None:
        init_greeks_validator()
    return _validator.validate_greeks(spot, strike, tte_sec, iv, option_type, underlying)

def get_reliable_greeks(spot: float, strike: float, tte_sec: float,
                       iv: float = 0.20, option_type: str = 'CE',
                       underlying: str = "NIFTY") -> Dict:
    """Get reliable Greeks globally"""
    if _validator is None:
        init_greeks_validator()
    return _validator.get_reliable_greeks(spot, strike, tte_sec, iv, option_type, underlying)
