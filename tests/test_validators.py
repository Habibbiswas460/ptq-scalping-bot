"""
Test Greeks Validator
Verify Greeks cross-validation logic
"""

import pytest
from core.risk.greeks_validator import (
    GreeksValidator, init_greeks_validator, validate_greeks, get_reliable_greeks
)


class TestGreeksValidator:
    """Greeks validator tests"""
    
    def setup_method(self):
        """Setup for each test"""
        self.validator = GreeksValidator()
    
    def test_bsm_calculation(self):
        """Test BSM Greeks calculation"""
        greeks = self.validator.get_bsm_greeks(
            spot=23500,
            strike=23500,
            tte_sec=21600,  # 6 hours
            iv=0.20,
            option_type='CE'
        )
        
        assert 'delta' in greeks
        assert 'gamma' in greeks
        assert 'theta' in greeks
        assert 'vega' in greeks
        
        # ATM call should have delta around 0.5
        assert 0.4 < greeks['delta'] < 0.6
        
        # Gamma should be positive
        assert greeks['gamma'] > 0
        
        # Theta should be negative for long call
        assert greeks['theta'] < 0
    
    def test_delta_divergence_detection(self):
        """Test delta divergence detection"""
        bsm = {'delta': 0.50, 'gamma': 0.001, 'theta': -50, 'vega': 5}
        api = {'delta': 0.495, 'gamma': 0.001, 'theta': -50, 'vega': 5}  # 1% diff
        
        comparison = self.validator.compare_greeks(bsm, api)
        
        assert 'delta' in comparison
        delta_diff, is_div = comparison['delta']
        
        # 1% delta difference should not diverge (threshold is 5%)
        assert not is_div
    
    def test_delta_significant_divergence(self):
        """Test significant delta divergence detection"""
        bsm = {'delta': 0.50, 'gamma': 0.001, 'theta': -50, 'vega': 5}
        api = {'delta': 0.40, 'gamma': 0.001, 'theta': -50, 'vega': 5}  # 20% diff
        
        comparison = self.validator.compare_greeks(bsm, api)
        
        assert 'delta' in comparison
        delta_diff, is_div = comparison['delta']
        
        # 20% difference should diverge (threshold is 5%)
        assert is_div
    
    def test_multiple_divergences(self):
        """Test detection of multiple divergences"""
        bsm = {'delta': 0.50, 'gamma': 0.001, 'theta': -50, 'vega': 5}
        api = {'delta': 0.40, 'gamma': 0.0005, 'theta': -30, 'vega': 5}
        
        comparison = self.validator.compare_greeks(bsm, api)
        
        div_count = sum(1 for _, (_, is_div) in comparison.items() if is_div)
        assert div_count >= 2
    
    def test_validate_greeks_full(self):
        """Test full validation workflow"""
        result = self.validator.validate_greeks(
            spot=23500,
            strike=23500,
            tte_sec=21600,
            iv=0.20,
            option_type='CE'
        )
        
        assert 'bsm' in result
        assert 'timestamp' in result
        assert 'spot' in result
        assert 'verdict' in result
        
        # Verdict should be one of expected values
        assert result['verdict'] in ['OK', 'WARNING', 'ERROR', 'API_UNAVAILABLE']
    
    def test_reliable_greeks_fallback(self):
        """Test reliable greeks selection"""
        reliable = self.validator.get_reliable_greeks(
            spot=23500,
            strike=23500,
            tte_sec=21600,
            iv=0.20,
            option_type='CE'
        )
        
        assert 'delta' in reliable
        assert 'source' in reliable
        assert 'confidence' in reliable
        
        # Confidence should be between 0 and 1
        assert 0.0 <= reliable['confidence'] <= 1.0


class TestEMARegimeDetection:
    """Test EMA-based regime detection"""
    
    def test_ema_calculation(self):
        """Test EMA calculation"""
        from core.risk.session_trend import SimpleEMA
        
        ema = SimpleEMA(period=9)
        
        prices = [23500, 23505, 23510, 23515, 23520, 23525, 23530, 23535, 23540]
        
        for price in prices:
            ema.update(price)
        
        current_ema = ema.get()
        assert current_ema is not None
        assert 23500 < current_ema < 23540
    
    def test_bullish_regime(self):
        """Test BULLISH regime detection"""
        from core.risk.session_trend import SessionTrendTracker
        
        tracker = SessionTrendTracker()
        tracker.start_session(23500)
        
        # Simulate bullish price action
        prices = [23505, 23510, 23515, 23520, 23525, 23530, 23535, 23540, 23545]
        
        for price in prices:
            trend = tracker.update_price(price)
        
        assert tracker.current_trend in ['BULLISH', 'SIDEWAYS']
        assert tracker.confidence > 30
    
    def test_bearish_regime(self):
        """Test BEARISH regime detection"""
        from core.risk.session_trend import SessionTrendTracker
        
        tracker = SessionTrendTracker()
        tracker.start_session(23500)
        
        # Simulate bearish price action
        prices = [23495, 23490, 23485, 23480, 23475, 23470, 23465, 23460, 23455]
        
        for price in prices:
            trend = tracker.update_price(price)
        
        assert tracker.current_trend in ['BEARISH', 'SIDEWAYS']
        assert tracker.confidence > 30
    
    def test_sideways_regime(self):
        """Test SIDEWAYS regime detection"""
        from core.risk.session_trend import SessionTrendTracker
        
        tracker = SessionTrendTracker()
        tracker.start_session(23500)
        
        # Simulate sideways price action
        prices = [23500, 23502, 23499, 23501, 23500, 23502, 23498, 23501, 23500]
        
        for price in prices:
            trend = tracker.update_price(price)
        
        # Should be mostly SIDEWAYS
        assert tracker.current_trend == 'SIDEWAYS'
    
    def test_rsi_reversal_ce_trade(self):
        """Test CE trade allowed on RSI reversal"""
        from core.risk.session_trend import SessionTrendTracker
        
        tracker = SessionTrendTracker()
        tracker.start_session(23500)
        tracker.update_price(23450)  # Bearish move
        
        # Very low RSI (oversold)
        can_trade = tracker.can_trade_ce(rsi=25)
        assert can_trade  # Should allow CE on oversold bounce
    
    def test_rsi_reversal_pe_trade(self):
        """Test PE trade allowed on RSI reversal"""
        from core.risk.session_trend import SessionTrendTracker
        
        tracker = SessionTrendTracker()
        tracker.start_session(23500)
        tracker.update_price(23550)  # Bullish move
        
        # Very high RSI (overbought)
        can_trade = tracker.can_trade_pe(rsi=75)
        assert can_trade  # Should allow PE on overbought drop


class TestPaperTradeValidator:
    """Test paper trade validation framework"""
    
    def test_validation_start(self):
        """Test starting a validation"""
        from core.services.paper_trade_validator import PaperTradeValidator
        
        validator = PaperTradeValidator()
        
        signal = {
            'confidence': 85,
            'factors': [1, 2, 3],
            'premium_valid': True,
            'sl_points': 6,
            'tp_points': 12
        }
        
        validation = validator.start_validation(
            trade_id='T001',
            symbol='NIFTY23500CE',
            direction='CE',
            entry_signal=signal,
            entry_price=250
        )
        
        assert validation.trade_id == 'T001'
        assert validation.entry_price == 250
        assert len(validation.checkpoints) >= 1
    
    def test_tick_pipeline_validation(self):
        """Test tick pipeline validation"""
        from core.services.paper_trade_validator import PaperTradeValidator
        
        validator = PaperTradeValidator()
        
        signal = {'confidence': 85, 'sl_points': 6, 'tp_points': 12}
        validator.start_validation('T001', 'NIFTY23500CE', 'CE', signal, 250)
        
        tick = {
            'ltp': 255,
            'open': 250,
            'high': 260,
            'low': 245,
            'close': 255,
            'volume': 1000
        }
        
        indicators = {
            'ema_5': 254,
            'ema_9': 253,
            'ema_21': 252,
            'ema_50': 250,
            'rsi': 65,
            'macd': 0.5,
            'macd_signal': 0.4
        }
        
        checkpoint = validator.check_tick_pipeline('T001', tick, indicators)
        
        assert checkpoint is not None
        assert checkpoint.status == 'OK'
    
    def test_completion_summary(self):
        """Test validation completion"""
        from core.services.paper_trade_validator import PaperTradeValidator
        
        validator = PaperTradeValidator()
        
        signal = {'confidence': 85, 'sl_points': 6, 'tp_points': 12}
        validator.start_validation('T001', 'NIFTY23500CE', 'CE', signal, 250)
        
        validation = validator.complete_validation(
            trade_id='T001',
            exit_price=258,
            exit_reason='TP_HIT',
            actual_pnl=800
        )
        
        assert validation.verdict in ['VALID', 'WARNING', 'INVALID']
        assert validation.actual_pnl == 800
        assert len(validation.checkpoints) >= 2
    
    def test_stats_generation(self):
        """Test statistics generation"""
        from core.services.paper_trade_validator import PaperTradeValidator
        
        validator = PaperTradeValidator()
        
        # Add 3 trades
        for i in range(3):
            signal = {'confidence': 85, 'sl_points': 6, 'tp_points': 12}
            validator.start_validation(f'T{i:03d}', 'NIFTY23500CE', 'CE', signal, 250)
            validator.complete_validation(f'T{i:03d}', 255 + i, 'TP_HIT', 500 + i*100)
        
        stats = validator.get_summary_stats()
        
        assert stats['total_trades'] == 3
        assert stats['total_pnl'] > 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
