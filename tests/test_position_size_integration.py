from datetime import datetime
from types import SimpleNamespace

from core.engines import state_machine


class DummyRiskManager:
    def can_trade(self, spot_price=None):
        return True, {
            "legacy_size_multiplier": 0.7,
            "risk_budget": {
                "capital": 30000,
                "per_trade_risk_amount": 450,
                "daily_risk_budget_amount": 1500,
                "remaining_risk_amount": 450,
                "legacy_size_multiplier": 0.7,
                "sizing_context": ["Time-based: 70%"],
                "daily_loss_state": {"loss_utilization": 0.0},
                "recovery_mode": {"active": False, "severity": 0.0},
            },
            "warnings": ["Time-based: 70%"],
            "reasons": [],
        }


class DummyBroker:
    def __init__(self):
        self.last_qty = None

    def place_order(self, side, qty, trades_this_hour=0, direction="CE", signal_params=None):
        self.last_qty = qty
        return {
            "order_id": "PAPER_TEST_1",
            "entry_price": 100.0,
            "entry_time": datetime.now(),
            "qty": qty,
            "side": side,
            "direction": direction,
            "symbol": "NIFTYTESTCE",
            "status": "COMPLETE",
        }


class DummyLogger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))

    def trade_entry(self, payload):
        self.messages.append(("trade_entry", payload))

    def state_change(self, src, dst, reason):
        self.messages.append(("state_change", {"src": src, "dst": dst, "reason": reason}))


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
            "breakdown": {
                "score_multiplier": 1.0,
                "confidence_multiplier": 1.0,
                "market_quality_multiplier": 1.0,
                "regime_multiplier": 1.0,
                "volatility_multiplier": 1.0,
                "recovery_multiplier": 1.0,
                "daily_loss_multiplier": 1.0,
                "soft_allocation_multiplier": 1.0,
            },
        }


class ZeroQtyPositionSizeEngine:
    def calculate(self, **kwargs):
        return {
            "risk_budget_used": 0.0,
            "risk_amount": 0.0,
            "position_size": 0,
            "lots": 0,
            "allocation_grade": "REJECT",
            "capped": True,
            "cap_reason": "allocator_zero_quantity",
            "breakdown": {},
        }


def _signal_params():
    return {
        "direction": "CE",
        "score": 84,
        "confidence": 82,
        "sl_points": 6,
        "tp_points": 12,
        "regime": "BULLISH",
        "factors": ["EMA9>21"],
        "details": {
            "reason": "Entry signal",
            "market_quality_score": 81,
            "market_quality_grade": "A",
            "market_quality_components": {"spread": 20},
            "hard_reject_reason": None,
            "market_quality": {"quality_score": 81},
            "weighted_score": 84,
            "regime": "BULLISH",
        },
    }


def test_state_entry_ready_uses_allocator_quantity(monkeypatch):
    logged_entries = []

    monkeypatch.setattr("core.risk.risk_manager.get_risk_manager", lambda: DummyRiskManager())
    monkeypatch.setattr("core.engines.entry_engine.get_last_signal_params", _signal_params)
    monkeypatch.setattr("core.engines.entry_engine.get_signal_direction", lambda: "CE")
    monkeypatch.setattr("core.engines.position_size_engine.PositionSizeEngine", DummyPositionSizeEngine)
    monkeypatch.setattr("core.services.database.log_trade_entry", lambda trade: logged_entries.append(trade) or 1)

    state = SimpleNamespace(consecutive_entry_signals=1, trades_this_hour=0, current_trade=None, estimated_vix=15.0)
    broker = DummyBroker()
    logger = DummyLogger()

    next_state = state_machine.state_entry_ready(
        tick={"spot_price": 25000},
        greeks={"delta": 0.5},
        state=state,
        broker=broker,
        logger=logger,
    )

    assert next_state == "IN_TRADE"
    assert broker.last_qty == 150
    assert state.current_trade["allocation_grade"] == "A"
    assert logged_entries[0]["risk_amount"] == 450.0
    assert logged_entries[0]["qty"] == 150
    assert any("Risk sizing context" in message for level, message in logger.messages if level == "info")


def test_state_entry_ready_blocks_zero_allocator_quantity(monkeypatch):
    monkeypatch.setattr("core.risk.risk_manager.get_risk_manager", lambda: DummyRiskManager())
    monkeypatch.setattr("core.engines.entry_engine.get_last_signal_params", _signal_params)
    monkeypatch.setattr("core.engines.entry_engine.get_signal_direction", lambda: "CE")
    monkeypatch.setattr("core.engines.position_size_engine.PositionSizeEngine", ZeroQtyPositionSizeEngine)

    state = SimpleNamespace(consecutive_entry_signals=1, trades_this_hour=0, current_trade=None, estimated_vix=15.0)
    broker = DummyBroker()
    logger = DummyLogger()

    next_state = state_machine.state_entry_ready(
        tick={"spot_price": 25000},
        greeks={"delta": 0.5},
        state=state,
        broker=broker,
        logger=logger,
    )

    assert next_state == "COOLDOWN"
    assert broker.last_qty is None
