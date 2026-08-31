from core.engines import exit_engine


def test_tsl_step_levels_lock_expected_level(monkeypatch):
    """TSL must lock to the highest configured step that max profit has reached."""
    monkeypatch.setattr(exit_engine, 'TRAILING_ENABLED', True)
    monkeypatch.setattr(exit_engine, 'TSL_STEP_LEVELS', [(8, 4), (12, 7), (16, 11)])

    trade = {
        'max_profit_points': 0,
        'highest_sl': -6,
    }

    sl, status = exit_engine.get_step_trailing_sl(trade, 13.0)

    assert sl == 7.0
    assert status == 'STEP_TSL(+7.0)'
    assert trade.get('max_profit_points') == 13.0
    assert trade.get('highest_sl') == 7.0


def test_tsl_never_decreases_on_pullback(monkeypatch):
    """After locking a higher SL, pullback ticks must not reduce it."""
    monkeypatch.setattr(exit_engine, 'TRAILING_ENABLED', True)
    monkeypatch.setattr(exit_engine, 'TSL_STEP_LEVELS', [(8, 4), (12, 7), (16, 11)])

    trade = {
        'max_profit_points': 0,
        'highest_sl': -6,
    }

    sl_up, _ = exit_engine.get_step_trailing_sl(trade, 16.0)
    sl_pullback, status_pullback = exit_engine.get_step_trailing_sl(trade, 10.0)

    assert sl_up == 11.0
    assert sl_pullback == 11.0
    assert status_pullback == 'LOCKED(+11.0)'


def test_tsl_disabled_stays_hard_sl(monkeypatch):
    """When trailing is disabled, SL remains hard-SL baseline."""
    monkeypatch.setattr(exit_engine, 'TRAILING_ENABLED', False)
    monkeypatch.setattr(exit_engine, 'TSL_STEP_LEVELS', [(8, 4), (12, 7)])

    trade = {
        'max_profit_points': 0,
        'highest_sl': -7,
    }

    sl, status = exit_engine.get_step_trailing_sl(trade, 20.0)

    assert sl == -7.0
    assert status == 'TRAILING_DISABLED'
