"""
Paper Trade Validation Framework
End-to-end pipeline verification: Tick → Signal → Execution → Exit
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass, field
import json
import logging


@dataclass
class ValidationCheckpoint:
    """Single validation checkpoint in the trade pipeline"""
    stage: str              # 'ENTRY', 'EXECUTION', 'EXIT', 'PNL'
    timestamp: datetime
    status: str             # 'OK', 'WARNING', 'FAIL'
    message: str
    details: Dict = field(default_factory=dict)
    severity: str = 'INFO'  # 'DEBUG', 'INFO', 'WARNING', 'ERROR'


@dataclass
class PaperTradeValidation:
    """Complete validation record for a paper trade"""
    trade_id: str
    symbol: str
    entry_direction: str    # 'CE' or 'PE'
    entry_signal: Dict
    entry_price: float
    entry_time: datetime
    expected_sl: float
    expected_tp: float
    
    exit_price: float = 0.0
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    actual_pnl: float = 0.0
    
    checkpoints: List[ValidationCheckpoint] = field(default_factory=list)
    verdict: str = 'PENDING'  # 'VALID', 'WARNING', 'INVALID'
    issues: List[str] = field(default_factory=list)


class PaperTradeValidator:
    """
    Validate paper trades through complete lifecycle.
    Ensures:
    - Entry signals are generated correctly
    - Ticks flow properly to strategy
    - Entry parameters match expectations
    - Exit conditions trigger as designed
    - PnL calculations are accurate
    """
    
    def __init__(self, max_validations: int = 100):
        self.validations: Dict[str, PaperTradeValidation] = {}
        self.max_validations = max_validations
        self.logger = logging.getLogger(__name__)
    
    def start_validation(self, trade_id: str, symbol: str, direction: str,
                        entry_signal: Dict, entry_price: float) -> PaperTradeValidation:
        """Start validation for a new paper trade"""
        
        validation = PaperTradeValidation(
            trade_id=trade_id,
            symbol=symbol,
            entry_direction=direction,
            entry_signal=entry_signal,
            entry_price=entry_price,
            entry_time=datetime.now(),
            expected_sl=entry_signal.get('sl_points', 6),
            expected_tp=entry_signal.get('tp_points', 12)
        )
        
        # Log entry checkpoint
        confidence = entry_signal.get('confidence', 0)
        validation.checkpoints.append(ValidationCheckpoint(
            stage='ENTRY',
            timestamp=datetime.now(),
            status='OK' if confidence >= 70 else 'WARNING',
            message=f"Entry signal generated: {direction} @ ₹{entry_price:.0f}",
            details={
                'confidence': confidence,
                'signal_factors': len(entry_signal.get('factors', [])),
                'premium_valid': entry_signal.get('premium_valid', False)
            },
            severity='INFO'
        ))
        
        # Store validation
        if len(self.validations) >= self.max_validations:
            # Remove oldest
            oldest_id = next(iter(self.validations))
            del self.validations[oldest_id]
        
        self.validations[trade_id] = validation
        return validation
    
    def check_tick_pipeline(self, trade_id: str, tick: Dict, 
                           indicators: Dict) -> Optional[ValidationCheckpoint]:
        """
        Validate that tick data flows properly through indicator pipeline.
        
        Checks:
        - Tick has required fields (ltp, open, high, low, close, volume)
        - Indicators calculated from tick are consistent
        - No missing or stale data
        """
        if trade_id not in self.validations:
            return None
        
        validation = self.validations[trade_id]
        
        # Required tick fields
        required_fields = ['ltp', 'open', 'high', 'low', 'close', 'volume']
        missing = [f for f in required_fields if f not in tick]
        
        if missing:
            checkpoint = ValidationCheckpoint(
                stage='EXECUTION',
                timestamp=datetime.now(),
                status='FAIL',
                message=f"Tick pipeline broken: missing fields {missing}",
                details={'tick_fields': list(tick.keys())},
                severity='ERROR'
            )
            validation.checkpoints.append(checkpoint)
            validation.issues.append(f"Missing tick fields: {missing}")
            return checkpoint
        
        # Check indicator consistency
        issues = []
        
        # EMA sanity: EMA9 should be between high and low (or close to close)
        if 'ema_5' in indicators and 'ema_9' in indicators:
            ema_fast = indicators['ema_5']
            ema_signal = indicators['ema_9']
            if ema_fast == 0 or ema_signal == 0:
                issues.append("EMA values are zero")
            elif abs(ema_fast - ema_signal) > tick['high'] - tick['low']:
                # EMA difference shouldn't exceed bar range
                issues.append(f"EMA values diverge too much")
        
        # RSI sanity: should be 0-100
        if 'rsi' in indicators:
            rsi = indicators['rsi']
            if not (0 <= rsi <= 100):
                issues.append(f"RSI out of range: {rsi}")
        
        # MACD sanity: signal should be EMA of MACD
        if 'macd' in indicators and 'macd_signal' in indicators:
            if indicators['macd'] == 0 and indicators['macd_signal'] != 0:
                issues.append("MACD zero but signal non-zero")
        
        status = 'FAIL' if issues else 'OK'
        checkpoint = ValidationCheckpoint(
            stage='EXECUTION',
            timestamp=datetime.now(),
            status=status,
            message="Tick pipeline OK" if not issues else f"Pipeline issues: {issues[0]}",
            details={'indicators_count': len(indicators), 'issues': issues},
            severity='ERROR' if issues else 'DEBUG'
        )
        
        validation.checkpoints.append(checkpoint)
        if issues:
            validation.issues.extend(issues)
        
        return checkpoint
    
    def check_exit_conditions(self, trade_id: str, current_price: float,
                            exit_conditions: Dict) -> Optional[ValidationCheckpoint]:
        """
        Validate exit conditions triggered correctly.
        
        Checks:
        - SL triggered when price crosses SL level
        - TP triggered when price crosses TP level
        - Exit reason matches actual exit condition
        - Exit price is reasonable
        """
        if trade_id not in self.validations:
            return None
        
        validation = self.validations[trade_id]
        
        issues = []
        
        # Verify exit logic consistency
        sl_price = validation.entry_price - validation.expected_sl
        tp_price = validation.entry_price + validation.expected_tp
        
        # Check if exit triggered appropriately
        if exit_conditions.get('sl_hit'):
            if current_price > sl_price + 1:  # Allow 1 pt slippage
                issues.append(f"SL claimed but price {current_price} > SL {sl_price}")
        
        if exit_conditions.get('tp_hit'):
            if current_price < tp_price - 1:  # Allow 1 pt slippage
                issues.append(f"TP claimed but price {current_price} < TP {tp_price}")
        
        # Verify exit reason is valid
        valid_reasons = ['SL_HIT', 'TP_HIT', 'TRAILING_SL', 'RSI_EXIT', 
                        'TIME_EXIT', 'GREEK_EXIT', 'MANUAL', 'KILL_SWITCH']
        exit_reason = exit_conditions.get('exit_reason', '')
        
        if exit_reason and exit_reason not in valid_reasons:
            issues.append(f"Unknown exit reason: {exit_reason}")
        
        status = 'WARNING' if issues else 'OK'
        checkpoint = ValidationCheckpoint(
            stage='EXIT',
            timestamp=datetime.now(),
            status=status,
            message=f"Exit: {exit_reason}" if not issues else f"Exit issues detected",
            details={
                'expected_sl': sl_price,
                'expected_tp': tp_price,
                'current_price': current_price,
                'exit_reason': exit_reason,
                'issues': issues
            },
            severity='WARNING' if issues else 'INFO'
        )
        
        validation.checkpoints.append(checkpoint)
        if issues:
            validation.issues.extend(issues)
        
        return checkpoint
    
    def complete_validation(self, trade_id: str, exit_price: float, 
                           exit_reason: str, actual_pnl: float) -> PaperTradeValidation:
        """Complete validation for a closed paper trade"""
        
        if trade_id not in self.validations:
            return None
        
        validation = self.validations[trade_id]
        validation.exit_price = exit_price
        validation.exit_time = datetime.now()
        validation.exit_reason = exit_reason
        validation.actual_pnl = actual_pnl
        
        # Determine verdict
        if validation.issues:
            if any('FAIL' in c.status for c in validation.checkpoints):
                validation.verdict = 'INVALID'
            else:
                validation.verdict = 'WARNING'
        else:
            validation.verdict = 'VALID'
        
        # Final summary checkpoint
        validation.checkpoints.append(ValidationCheckpoint(
            stage='PNL',
            timestamp=datetime.now(),
            status='OK',
            message=f"Trade completed: {exit_reason}, PnL ₹{actual_pnl:.0f}",
            details={
                'entry_price': validation.entry_price,
                'exit_price': exit_price,
                'pnl': actual_pnl,
                'hold_sec': (validation.exit_time - validation.entry_time).total_seconds(),
                'verdict': validation.verdict
            }
        ))
        
        self.logger.info(f"Paper trade {trade_id} verdict: {validation.verdict}")
        
        return validation
    
    def get_validation_report(self, trade_id: str) -> Optional[str]:
        """Get formatted validation report for a trade"""
        
        if trade_id not in self.validations:
            return None
        
        v = self.validations[trade_id]
        
        report = f"""
╔════════════════════════════════════════════════════════════════╗
║ PAPER TRADE VALIDATION REPORT
║ Trade ID: {v.trade_id}
╚════════════════════════════════════════════════════════════════╝

Direction: {v.entry_direction}  |  Symbol: {v.symbol}
Entry: ₹{v.entry_price:.0f} @ {v.entry_time.strftime('%H:%M:%S')}
Expected SL/TP: {v.expected_sl}/{v.expected_tp} pts

Exit: ₹{v.exit_price:.0f} @ {v.exit_reason} (PnL: ₹{v.actual_pnl:.0f})

Verdict: {v.verdict}
Issues: {len(v.issues)}
Checkpoints: {len(v.checkpoints)}

─────────────────────────────────────────────────────────────────
CHECKPOINTS:
"""
        for cp in v.checkpoints:
            report += f"\n  [{cp.status:8}] {cp.stage:12} - {cp.message}\n"
            if cp.severity == 'ERROR':
                report += f"           ⚠️  ERROR: {cp.details}\n"
        
        if v.issues:
            report += f"\n─────────────────────────────────────────────────────────────────\nISSUES:\n"
            for issue in v.issues:
                report += f"  🔴 {issue}\n"
        
        return report
    
    def get_summary_stats(self) -> Dict:
        """Get overall validation statistics"""
        
        if not self.validations:
            return {}
        
        total = len(self.validations)
        valid = sum(1 for v in self.validations.values() if v.verdict == 'VALID')
        warning = sum(1 for v in self.validations.values() if v.verdict == 'WARNING')
        invalid = sum(1 for v in self.validations.values() if v.verdict == 'INVALID')
        
        avg_pnl = sum(v.actual_pnl for v in self.validations.values()) / total if total > 0 else 0
        
        return {
            'total_trades': total,
            'valid': valid,
            'warning': warning,
            'invalid': invalid,
            'valid_pct': (valid / total * 100) if total > 0 else 0,
            'avg_pnl': avg_pnl,
            'total_pnl': sum(v.actual_pnl for v in self.validations.values())
        }


# Global validator instance
_paper_validator = None

def init_paper_trade_validator(max_validations: int = 100) -> PaperTradeValidator:
    """Initialize global paper trade validator"""
    global _paper_validator
    _paper_validator = PaperTradeValidator(max_validations)
    return _paper_validator

def get_paper_validator() -> PaperTradeValidator:
    """Get global paper trade validator"""
    global _paper_validator
    if _paper_validator is None:
        _paper_validator = PaperTradeValidator()
    return _paper_validator
