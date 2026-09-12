"""Guards for the tick-input repair (delta / oi).

Both repairs are flag-gated and default OFF, so the frozen baseline's scoring behaviour is
unchanged unless a flag is set. These tests lock that down and check each repair does what it
claims when enabled.
"""
import importlib
import pytest

import config.constants as C
from core.engines.weighted_score_engine import WeightedScoreEngine


@pytest.fixture(autouse=True)
def _restore():
    yield
    importlib.reload(C)


def _score(delta=None, oi_direction='NEUTRAL', direction='CE'):
    ind = {'Close': 120.0, 'VWAP': 119.0, 'Vol_Ratio': 1.5, 'RSI': 60.0,
           'MACD_Hist': 1.0, 'MACD_Hist_Prev': 0.5, 'ATR': 4.0, 'EMA_9': 121.0,
           'EMA_21': 118.0, 'regime': 'SIDEWAYS'}
    if delta is not None:
        ind['Delta'] = delta
    tick = {'ltp': 120.0, 'bid': 119.8, 'ask': 120.2}
    return WeightedScoreEngine().score(ind, tick, direction, oi_direction)


# ── defaults ──────────────────────────────────────────────────────────────
def test_code_defaults_are_off(monkeypatch):
    """The CODE default must be OFF so a checkout with no .env entries reproduces the frozen
    baseline's scoring. `.env` may switch either flag on for a measured session — that is the
    intended use — so this asserts the default, not the currently effective value."""
    from config.configuration import env_bool
    monkeypatch.delenv('TICK_DELTA_ENABLED', raising=False)
    monkeypatch.delenv('TICK_OI_ENABLED', raising=False)
    assert env_bool('TICK_DELTA_ENABLED', False) is False
    assert env_bool('TICK_OI_ENABLED', False) is False


def test_flags_are_readable_booleans():
    """Whatever .env says, the flags must resolve to real booleans the engines can branch on."""
    assert isinstance(C.TICK_DELTA_ENABLED, bool)
    assert isinstance(C.TICK_OI_ENABLED, bool)


def test_unpopulated_delta_still_scores_zero():
    """The baseline behaviour: with no delta on the tick, both components stay 0."""
    _, contrib = _score(delta=None)
    assert contrib['delta'] == 0
    assert contrib['greeks'] == 0


# ── the delta repair ──────────────────────────────────────────────────────
def test_populated_delta_earns_both_components():
    _, contrib = _score(delta=0.52)
    assert contrib['delta'] == WeightedScoreEngine.DEFAULT_WEIGHTS['delta']
    assert contrib['greeks'] == WeightedScoreEngine.DEFAULT_WEIGHTS['greeks']


def test_delta_half_band_and_out_of_band():
    _, half = _score(delta=0.68)
    assert half['delta'] == 5 and half['greeks'] == 2
    _, out = _score(delta=0.95)
    assert out['delta'] == 0 and out['greeks'] == 0


def test_pe_negative_delta_is_scored_on_magnitude():
    """PE deltas are negative; before the fix every PE scored 0 on delta and greeks."""
    _, contrib = _score(delta=-0.52, direction='PE')
    assert contrib['delta'] == WeightedScoreEngine.DEFAULT_WEIGHTS['delta']
    assert contrib['greeks'] == WeightedScoreEngine.DEFAULT_WEIGHTS['greeks']


def test_delta_repair_changes_the_total_score():
    """The repair must actually move the score, otherwise it cannot rank anything."""
    without, _ = _score(delta=None)
    with_delta, _ = _score(delta=0.52)
    assert with_delta > without


# ── the oi repair ─────────────────────────────────────────────────────────
def test_oi_direction_earns_the_oi_component():
    _, neutral = _score(delta=0.5, oi_direction='NEUTRAL')
    _, buildup = _score(delta=0.5, oi_direction='LONG_BUILDUP')
    assert neutral['oi'] == 0
    assert buildup['oi'] == WeightedScoreEngine.DEFAULT_WEIGHTS['oi']


def test_broker_carries_open_interest_only_when_enabled():
    """The websocket parser decodes open_interest; the tick dict used to drop it.

    _on_ws_tick lives in core/trading/tick_feed.py (BrokerInterface composes it in via
    TickFeedMixin) since the 2026-09 broker.py layer split — not in broker.py itself.
    """
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "core", "trading", "tick_feed.py")).read()
    assert "tick_data.get('open_interest'" in src, "tick_feed no longer reads open_interest"
    assert "if TICK_OI_ENABLED:" in src, "the oi repair must stay flag-gated"


def test_oi_chain_produces_a_direction_once_the_tick_carries_oi():
    """End-to-end for the oi repair: tick['oi'] -> update_oi_data -> a non-NEUTRAL direction.

    Without the repair current_oi is 0 on every tick, update_oi_data short-circuits to
    NEUTRAL, and the score's oi component (weight 10) can never be earned.
    """
    from strategies.smart_scalp_v3 import SmartScalpV3
    s = SmartScalpV3.__new__(SmartScalpV3)
    s._last_oi = None
    s._prev_oi = None
    s._last_price = None
    s._oi_change_pct = 0.0

    # no oi on the tick — the state before the repair
    assert s.update_oi_data({'ltp': 120.0})[1] == "NEUTRAL"

    # first tick with oi only seeds the tracker
    assert s.update_oi_data({'ltp': 120.0, 'oi': 1_000_000})[1] == "NEUTRAL"
    # price up + OI up by >1% = long buildup
    pct, direction = s.update_oi_data({'ltp': 121.0, 'oi': 1_050_000})
    assert direction == "LONG_BUILDUP"
    assert pct == pytest.approx(5.0, abs=0.01)
    # price down + OI down by >1% = long unwinding
    assert s.update_oi_data({'ltp': 119.0, 'oi': 1_000_000})[1] == "LONG_UNWINDING"
