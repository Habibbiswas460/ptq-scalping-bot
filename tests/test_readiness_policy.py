"""Unit tests for readiness policy decisions and pre-open launch gating."""

import pytest

from utils import market_readiness_checker as checker


class _DummyClient:
    def get_ltp(self, exchange, symbol, token):
        if exchange == "NSE":
            return 24078.5
        return 120.0


class _DummyBroker:
    def __init__(self):
        self.broker_client = _DummyClient()
        self.current_strike = 24100

    def connect(self):
        return True

    def get_ws_status(self):
        return {"connected": True, "circuit_breaker_open": False, "reconnect_attempts": 0}

    def get_tick(self):
        # Keep this deterministic and minimal. For this test we use sample_seconds=0,
        # so the sampler does not depend on live timing.
        return {
            "spot_price": 24078.5,
            "timestamp": 1,
            "data_source": "REST",
            "delta": 0.5,
        }

    def _build_option_symbol(self, strike, side):
        return f"NIFTY{strike}{side}"

    def _get_token(self, symbol, exchange):
        return "99999"

    def logout(self):
        return None


class _FailingIndicatorStrategy:
    def calculate_indicators(self, sampled_ticks):
        return {}

    def generate_signal(self, sampled_ticks):
        return 0, None, 0, {"reason": "Failed to calculate indicators"}


class TestReadinessPolicy:
    def test_market_closed_strict_true_deferred_is_blocked(self):
        status, launch_allowed = checker._derive_outcome(
            overall_ready=True,
            paper_live_preopen_mode=True,
            strict_preopen_gate=True,
        )

        assert status == "DEFERRED"
        assert launch_allowed is False

    def test_market_closed_strict_false_deferred_is_allowed(self):
        status, launch_allowed = checker._derive_outcome(
            overall_ready=True,
            paper_live_preopen_mode=True,
            strict_preopen_gate=False,
        )

        assert status == "DEFERRED"
        assert launch_allowed is True

    def test_market_open_indicators_fail_results_in_not_ready_and_blocked(self, monkeypatch):
        monkeypatch.setattr(checker, "BrokerInterface", _DummyBroker)
        monkeypatch.setattr(checker, "get_strategy", lambda: _FailingIndicatorStrategy())
        monkeypatch.setattr(checker, "PAPER_TRADING", True)
        monkeypatch.setattr(checker, "USE_LIVE_DATA", True)
        monkeypatch.setattr(checker, "ENABLE_WEBSOCKET", False)
        monkeypatch.setattr(checker, "is_stale_data_kill_active", lambda: False)
        monkeypatch.setattr(checker, "is_high_latency_paused", lambda: False)
        monkeypatch.setattr(checker, "_is_market_open_now", lambda: True)

        result = checker.run_readiness_check(
            sample_seconds=0,
            tick_interval=0.1,
            min_ticks=1,
            strict_engines=False,
        )

        indicators = next(item for item in result["checks"] if item["name"] == "Indicators")

        assert indicators["passed"] is False
        assert indicators["blocking"] is True
        assert result["overall_status"] == "NOT_READY"
        assert result["launch_allowed"] is False
        assert result["overall_ready"] is False
        assert result["technical_ready"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
