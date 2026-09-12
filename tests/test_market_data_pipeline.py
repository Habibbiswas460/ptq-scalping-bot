"""core/market_data/: broker-agnostic tick validation, routing, caching, enrichment."""

from core.market_data.tick_cache import TickCache
from core.market_data.tick_enricher import enrich_tick
from core.market_data.tick_router import TickRouter
from core.market_data.tick_validator import SequenceTracker, validate_tick


# -- tick_validator ----------------------------------------------------------

def test_a_normal_tick_validates_clean():
    result = validate_tick({"token": "123", "ltp": 100.5})
    assert result.ok
    assert result.reasons == []


def test_missing_token_and_missing_ltp_are_both_flagged():
    result = validate_tick({})
    assert not result.ok
    assert "missing token" in result.reasons
    assert "missing ltp" in result.reasons


def test_non_positive_ltp_is_flagged():
    result = validate_tick({"token": "123", "ltp": 0})
    assert not result.ok
    assert any("non-positive ltp" in r for r in result.reasons)


def test_crossed_book_is_flagged():
    result = validate_tick({
        "token": "123", "ltp": 100,
        "best_bid_price": 105, "best_ask_price": 100,
    })
    assert not result.ok
    assert any("crossed book" in r for r in result.reasons)


def test_sequence_tracker_accepts_increasing_and_rejects_non_increasing():
    tracker = SequenceTracker()
    assert tracker.check("T1", 10) is None
    assert tracker.check("T1", 11) is None
    reason = tracker.check("T1", 11)
    assert reason is not None and "sequence 11 <= last seen 11" in reason
    reason2 = tracker.check("T1", 5)
    assert reason2 is not None


def test_sequence_tracker_is_independent_per_token():
    tracker = SequenceTracker()
    tracker.check("T1", 100)
    # A different token starting at a lower sequence must not be rejected.
    assert tracker.check("T2", 1) is None


def test_sequence_tracker_reset_clears_high_water_mark():
    tracker = SequenceTracker()
    tracker.check("T1", 100)
    tracker.reset("T1")
    assert tracker.check("T1", 1) is None


def test_sequence_reset_with_no_token_clears_everything():
    tracker = SequenceTracker()
    tracker.check("T1", 100)
    tracker.check("T2", 100)
    tracker.reset()
    assert tracker.check("T1", 1) is None
    assert tracker.check("T2", 1) is None


def test_validate_tick_uses_the_shared_sequence_tracker_when_given_one():
    tracker = SequenceTracker()
    tracker.check("T1", 50)
    result = validate_tick({"token": "T1", "ltp": 100, "sequence": 10}, tracker)
    assert not result.ok
    assert any("sequence" in r for r in result.reasons)


def test_missing_sequence_field_is_not_an_error():
    tracker = SequenceTracker()
    result = validate_tick({"token": "T1", "ltp": 100}, tracker)
    assert result.ok


# -- tick_router ---------------------------------------------------------------

def test_router_dispatches_to_the_registered_handler_for_that_token():
    router = TickRouter()
    seen = []
    router.register("SPOT", lambda tick: seen.append(("spot", tick)))
    router.register("OPT", lambda tick: seen.append(("opt", tick)))

    delivered = router.route({"token": "OPT", "ltp": 100})
    assert delivered is True
    assert seen == [("opt", {"token": "OPT", "ltp": 100})]


def test_router_falls_back_to_default_handler_for_an_unregistered_token():
    router = TickRouter()
    seen = []
    router.set_default(lambda tick: seen.append(tick))
    delivered = router.route({"token": "UNKNOWN", "ltp": 1})
    assert delivered is True
    assert seen == [{"token": "UNKNOWN", "ltp": 1}]


def test_router_drops_silently_with_no_handler_and_no_default():
    router = TickRouter()
    delivered = router.route({"token": "UNKNOWN", "ltp": 1})
    assert delivered is False


def test_router_unregister_removes_the_handler():
    router = TickRouter()
    seen = []
    router.register("T1", lambda tick: seen.append(tick))
    router.unregister("T1")
    delivered = router.route({"token": "T1", "ltp": 1})
    assert delivered is False
    assert seen == []


# -- tick_cache -----------------------------------------------------------------

def test_cache_get_returns_the_latest_tick_for_a_token():
    cache = TickCache()
    cache.update({"token": "T1", "ltp": 100})
    cache.update({"token": "T1", "ltp": 101})
    assert cache.get("T1") == {"token": "T1", "ltp": 101}


def test_cache_get_is_a_copy_not_a_live_reference():
    cache = TickCache()
    cache.update({"token": "T1", "ltp": 100})
    fetched = cache.get("T1")
    fetched["ltp"] = 999
    assert cache.get("T1")["ltp"] == 100


def test_cache_ignores_a_tick_with_no_token():
    cache = TickCache()
    cache.update({"ltp": 100})
    assert cache.all_tokens() == {}


def test_cache_get_missing_token_returns_none():
    cache = TickCache()
    assert cache.get("nope") is None


def test_cache_clear_one_token_leaves_others():
    cache = TickCache()
    cache.update({"token": "T1", "ltp": 1})
    cache.update({"token": "T2", "ltp": 2})
    cache.clear("T1")
    assert cache.get("T1") is None
    assert cache.get("T2") == {"token": "T2", "ltp": 2}


def test_cache_clear_all():
    cache = TickCache()
    cache.update({"token": "T1", "ltp": 1})
    cache.clear()
    assert cache.all_tokens() == {}


# -- tick_enricher ---------------------------------------------------------------

def test_enrich_computes_mid_spread_and_spread_bps():
    out = enrich_tick({"token": "T1", "ltp": 100, "best_bid_price": 99, "best_ask_price": 101})
    assert out["mid_price"] == 100.0
    assert out["spread"] == 2.0
    assert out["spread_bps"] == 200.0


def test_enrich_computes_change_pct_from_explicit_prev_close():
    out = enrich_tick({"token": "T1", "ltp": 110}, prev_close=100)
    assert out["change_pct"] == 10.0


def test_enrich_falls_back_to_the_ticks_own_close_field():
    out = enrich_tick({"token": "T1", "ltp": 105, "close": 100})
    assert out["change_pct"] == 5.0


def test_enrich_without_bid_ask_or_reference_adds_nothing_extra():
    out = enrich_tick({"token": "T1", "ltp": 100})
    assert "mid_price" not in out
    assert "spread_bps" not in out
    assert "change_pct" not in out


def test_enrich_never_mutates_the_input_dict():
    original = {"token": "T1", "ltp": 100, "best_bid_price": 99, "best_ask_price": 101}
    snapshot = dict(original)
    enrich_tick(original)
    assert original == snapshot
