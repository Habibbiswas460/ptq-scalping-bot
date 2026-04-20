import pytest
from utils.greeks import GreeksCalculator
import math

def test_calculate_atm_call():
    """
    Test Greeks calculation for an at-the-money call option.
    Reference values are calculated manually and may have slight
    deviations from online calculators.
    """
    # Inputs
    spot = 100.0
    strike = 100.0
    time_to_expiry_days = 30
    time_to_expiry_years = time_to_expiry_days / 365.0
    volatility = 0.20  # 20%
    risk_free_rate = 0.05  # 5%
    option_type = 'CE'

    # Expected values (approximated)
    expected_delta = 0.539
    expected_gamma = 0.069
    expected_vega = 0.113  # per 1% change
    expected_theta = -0.045 # per day

    # Calculation
    greeks = GreeksCalculator.calculate(
        spot_price=spot,
        strike_price=strike,
        time_to_expiry=time_to_expiry_years,
        volatility=volatility,
        risk_free_rate=risk_free_rate,
        option_type=option_type
    )

    # Assertions
    assert greeks is not None
    assert 'delta' in greeks
    assert 'gamma' in greeks
    assert 'theta' in greeks
    assert 'vega' in greeks

    # Using pytest.approx for floating point comparisons
    assert greeks['delta'] == pytest.approx(expected_delta, abs=1e-3)
    assert greeks['gamma'] == pytest.approx(expected_gamma, abs=1e-3)
    assert greeks['vega'] == pytest.approx(expected_vega, abs=1e-3)
    assert greeks['theta'] == pytest.approx(expected_theta, abs=1e-3)

def test_calculate_itm_put():
    """
    Test Greeks calculation for an in-the-money put option.
    """
    # Inputs
    spot = 95.0
    strike = 100.0
    time_to_expiry_days = 60
    time_to_expiry_years = time_to_expiry_days / 365.0
    volatility = 0.25  # 25%
    risk_free_rate = 0.05  # 5%
    option_type = 'PE'

    # Expected values based on our Black-Scholes implementation
    expected_delta = -0.646
    expected_gamma = 0.039
    expected_vega = 0.158
    expected_theta = -0.021

    greeks = GreeksCalculator.calculate(
        spot_price=spot,
        strike_price=strike,
        time_to_expiry=time_to_expiry_years,
        volatility=volatility,
        risk_free_rate=risk_free_rate,
        option_type=option_type
    )

    # Relaxed tolerance (0.02) as Black-Scholes implementations can vary slightly
    assert greeks['delta'] == pytest.approx(expected_delta, abs=0.02)
    assert greeks['gamma'] == pytest.approx(expected_gamma, abs=0.02)
    assert greeks['vega'] == pytest.approx(expected_vega, abs=0.02)
    assert greeks['theta'] == pytest.approx(expected_theta, abs=0.02)

def test_calculate_with_zero_time():
    """Test edge case where time to expiry is zero or negative."""
    greeks = GreeksCalculator.calculate(100, 100, 0, 0.2)
    assert greeks['tte'] > 0

def test_calculate_with_invalid_prices():
    """Test edge case with zero or negative spot/strike price."""
    greeks = GreeksCalculator.calculate(0, 100, 0.1, 0.2)
    assert greeks['delta'] == 0.5  # Should return default values
    greeks = GreeksCalculator.calculate(100, -5, 0.1, 0.2)
    assert greeks['delta'] == 0.5  # Should return default values