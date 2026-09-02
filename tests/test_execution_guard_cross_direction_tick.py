from datetime import datetime
from types import SimpleNamespace

from core.engines import state_machine


class DummyRiskManager:
    def can_trade(self, spot_price=None):
        return True, {"risk_budget": {"capital": 30000}, "warnings": [], "reasons": []}


class DummyPositionSizeEngine:
    def calculate(self, **kwargs):
        return {
            "risk_budget_used": 1.0,
            "risk_amount": 450.0,
            "position_size": 150,
            "lots": 2,
            "allocation_grade": "A",
            "capped": False,
            "cap_reason": None,
            "breakdown": {},
        }


class DummyLogger:
    def info(self, message):
        pass

    def warning(self, message):
        pass

    def trade_entry(self, payload):
        pass

    def state_change(self, src, dst, reason):
        pass


class CrossDirectionBroker:
    """Subscribed to a CE contract while the signal below is PE — the exact
    shape of the 2026-09-02 production incident (47/47 PE signals blocked
    all morning by comparing against the subscribed CE contract's price)."""

    def __init__(self, resolved_pe_tick):
        self.current_symbol = "NIFTY08SEP2623850CE"
        self._resolved_pe_tick = resolved_pe_tick
        self.last_qty = None

    def get_tick_for_direction(self, direction):
        assert direction == "PE"
        return self._resolved_pe_tick

    def place_order(self, side, qty, trades_this_hour=0, direction="CE", signal_params=None):
        self.last_qty = qty
        return {
            "order_id": "PAPER_TEST_1",
            "entry_price": self._resolved_pe_tick["ltp"],
            "entry_time": datetime.now(),
            "qty": qty,
            "side": side,
            "direction": direction,
            "symbol": "NIFTYTESTPE",
            "status": "COMPLETE",
        }


def _pe_signal_params(signal_ltp):
    return {
        "direction": "PE",
        "score": 66,
        "confidence": 82,
        "sl_points": 6,
        "tp_points": 12,
        "regime": "BEARISH",
        "factors": ["EMA9<21"],
        "signal_ltp": signal_ltp,
        "details": {
            "reason": "Entry signal",
            "market_quality_score": 81,
            "market_quality_grade": "A",
            "market_quality_components": {"spread": 20},
            "hard_reject_reason": None,
            "market_quality": {"quality_score": 81},
            "weighted_score": 66,
            "regime": "BEARISH",
        },
    }


def test_execution_guard_compares_resolved_instrument_not_subscribed_one(monkeypatch):
    # Real PE premium at signal time (matches what entry_engine.py would have
    # fetched via get_tick_for_direction and stored as signal_ltp).
    resolved_pe_tick = {"ltp": 112.40, "spot_price": 23861, "bid": 112.0, "ask": 112.8}

    monkeypatch.setattr("core.risk.risk_manager.get_risk_manager", lambda: DummyRiskManager())
    monkeypatch.setattr("core.engines.entry_engine.get_last_signal_params", lambda: _pe_signal_params(112.40))
    monkeypatch.setattr("core.engines.entry_engine.get_signal_direction", lambda: "PE")
    monkeypatch.setattr("core.engines.position_size_engine.PositionSizeEngine", DummyPositionSizeEngine)
    monkeypatch.setattr("core.services.database.log_trade_entry", lambda trade: 1)

    state = SimpleNamespace(consecutive_entry_signals=1, trades_this_hour=0, current_trade=None, estimated_vix=15.0)
    broker = CrossDirectionBroker(resolved_pe_tick)
    logger = DummyLogger()

    # The subscribed CE contract's tick — wildly different price from the PE
    # signal, the same shape that produced the false "Execution drift too
    # high 48.89%" block in production on 2026-09-02.
    subscribed_ce_tick = {"ltp": 167.35, "spot_price": 23861}

    next_state = state_machine.state_entry_ready(
        tick=subscribed_ce_tick,
        greeks={"delta": -0.5},
        state=state,
        broker=broker,
        logger=logger,
    )

    assert next_state == "IN_TRADE"
    assert broker.last_qty == 150
