"""
Market Context — "what is the market doing right now?"

Pure indicator computation extracted from SmartScalpV3.calculate_indicators()
(strategies/smart_scalp_v3.py) as part of the Phase C architecture modularization.
This module makes no trade decision — it produces EMA/RSI/MACD/VWAP/ATR/Bollinger/
Keltner/volume/squeeze values from a tick buffer and nothing else. No PASS/FAIL,
no BUY/SELL, no threshold comparison against a trading rule lives here.

Byte-for-byte extraction: every line below is the original method body, with
self.<config_value> replaced by an explicit cfg[...] lookup and self._ema/_rsi/_std
replaced by the module-level ema()/rsi()/std() functions defined here. No
calculation, no formula, and no threshold was changed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional


def ema(prices: List[float], period: int) -> float:
    """Calculate EMA. Verbatim extraction of SmartScalpV3._ema()."""
    if len(prices) < period:
        return prices[-1] if prices else 0

    multiplier = 2 / (period + 1)
    result = sum(prices[:period]) / period

    for price in prices[period:]:
        result = (price - result) * multiplier + result

    return result


def rsi(prices: List[float], period: int) -> float:
    """Calculate RSI using Wilder's smoothed moving average.

    Verbatim extraction of SmartScalpV3._rsi(). Uses EMA smoothing (alpha =
    1/period) instead of SMA, matching TradingView/MetaTrader/standard TA
    libraries.
    """
    if len(prices) < period + 1:
        return 50

    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    if len(changes) < period:
        return 50

    gains = [max(c, 0) for c in changes]
    losses = [abs(min(c, 0)) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100 if avg_gain > 0 else 50

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def std(values: List[float]) -> float:
    """Calculate standard deviation. Verbatim extraction of SmartScalpV3._std()."""
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5


def compute_indicators(
    ticks: List[Dict],
    cfg: Dict,
    runtime_state=None,
    volume_spike_multiplier: float = 1.5,
) -> Dict:
    """Calculate all technical indicators from tick data.

    Verbatim extraction of SmartScalpV3.calculate_indicators()'s body. `cfg` carries
    the indicator periods the caller previously read off `self` (ema_fast,
    ema_signal, ema_medium, ema_slow, rsi_period, macd_fast, macd_slow,
    macd_signal_period, bb_period, bb_std, atr_period, kc_period, kc_atr_mult,
    vol_sma) — unchanged values, just passed explicitly instead of through `self`.

    Does not set caller-owned instance state (e.g. `_last_calc_time`) — that side
    effect stays with the caller, which still owns it. `runtime_state.set_indicators()`
    is preserved here as the original code called it inline, immediately before
    returning the indicators.
    """
    prices, highs, lows, volumes = [], [], [], []

    # P0 FIX: Prioritize true 5-min OHLC canonical candles if available in live/paper mode.
    chunk_size = 1
    try:
        from core.runtime.state import runtime_state as _rs
        canonical = _rs.get_canonical_candles(interval_min=5)
        # We need at least 15 canonical candles to get a functional EMA
        if len(canonical) >= 15:
            prices = [c["close"] for c in canonical]
            highs = [c["high"] for c in canonical]
            lows = [c["low"] for c in canonical]
            volumes = [c.get("volume", 0) for c in canonical]
            # NOTE: chunk_size stays 1 here (its initializer above) -
            # prices/highs/lows are already one entry per candle, unlike
            # the legacy tick-chunking fallback below where chunk_size
            # maps a chunk index back into a raw per-tick prices array.
            # Overriding it to len(prices)//60 (as the legacy path does)
            # would misalign highs[i]/lows[i] against prices[i*chunk_size]
            # once there are more than ~120 canonical candles cached.
    except Exception:
        pass

    # Fallback to legacy tick chunking for backtester or empty state
    if not prices:
        # Need at least 60 ticks for reliable indicators
        if len(ticks) < 60:
            return {}

        # Use spot_price for indicators (NIFTY spot), ltp for option premium
        prices = [t.get('spot_price', t.get('ltp', 0)) for t in ticks]
        volumes = [t.get('volume', 10000) for t in ticks]

        # Validate prices - use ltp if spot_price is invalid
        if prices and prices[-1] < 1000:
            prices = [t['ltp'] for t in ticks]

        # Calculate high/low from prices
        chunk_size = max(1, len(prices) // 60)  # ~1 minute chunks

        for i in range(0, len(prices), chunk_size):
            chunk_prices = prices[i:i + chunk_size]
            if chunk_prices:
                highs.append(max(chunk_prices))
                lows.append(min(chunk_prices))

        if len(highs) < 30:
            return {}

    indicators = {}

    # EMAs
    indicators['EMA_5'] = ema(prices, cfg['ema_fast'])
    indicators['EMA_9'] = ema(prices, cfg['ema_signal'])
    indicators['EMA_21'] = ema(prices, cfg['ema_medium'])
    indicators['EMA_50'] = ema(prices, cfg['ema_slow'])

    # RSI
    indicators['RSI'] = rsi(prices, cfg['rsi_period'])

    # MACD - O(n) optimized version
    # Calculate EMAs incrementally instead of recalculating for each point
    if len(prices) >= cfg['macd_slow']:
        fast_ema = ema(prices, cfg['macd_fast'])
        slow_ema = ema(prices, cfg['macd_slow'])
        macd_line = fast_ema - slow_ema

        # For signal line, we need MACD history - calculate efficiently
        # Use last N MACD values where N = signal period * 3 for accuracy
        lookback = min(len(prices) - cfg['macd_slow'], cfg['macd_signal_period'] * 3)
        if lookback >= cfg['macd_signal_period']:
            # Calculate recent MACD values for signal line
            macd_values = []
            for i in range(lookback, 0, -1):
                idx = len(prices) - i
                f_ema = ema(prices[:idx + 1], cfg['macd_fast'])
                s_ema = ema(prices[:idx + 1], cfg['macd_slow'])
                macd_values.append(f_ema - s_ema)
            macd_values.append(macd_line)

            signal_line = ema(macd_values, cfg['macd_signal_period'])
            indicators['MACD'] = macd_line
            indicators['MACD_Signal'] = signal_line
            indicators['MACD_Hist'] = macd_line - signal_line
            # Previous histogram
            if len(macd_values) > 1:
                prev_signal = ema(macd_values[:-1], cfg['macd_signal_period'])
                indicators['MACD_Hist_Prev'] = macd_values[-2] - prev_signal
            else:
                indicators['MACD_Hist_Prev'] = indicators['MACD_Hist']
        else:
            indicators['MACD'] = macd_line
            indicators['MACD_Signal'] = macd_line
            indicators['MACD_Hist'] = 0
            indicators['MACD_Hist_Prev'] = 0
    else:
        indicators['MACD'] = 0
        indicators['MACD_Signal'] = 0
        indicators['MACD_Hist'] = 0
        indicators['MACD_Hist_Prev'] = 0

    # Bollinger Bands
    sma_20 = sum(prices[-cfg['bb_period']:]) / cfg['bb_period'] if len(prices) >= cfg['bb_period'] else prices[-1]
    std_20 = std(prices[-cfg['bb_period']:]) if len(prices) >= cfg['bb_period'] else 0
    indicators['BB_Mid'] = sma_20
    indicators['BB_Upper'] = sma_20 + cfg['bb_std'] * std_20
    indicators['BB_Lower'] = sma_20 - cfg['bb_std'] * std_20

    # ATR (simplified from highs/lows)
    atr_values = []
    for i in range(1, min(len(highs), len(lows), cfg['atr_period'] + 1)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - prices[min(i * chunk_size, len(prices) - 1)]),
            abs(lows[i] - prices[min(i * chunk_size, len(prices) - 1)])
        )
        atr_values.append(tr)
    indicators['ATR'] = sum(atr_values) / len(atr_values) if atr_values else 50

    # Keltner Channel
    kc_ema = ema(prices, cfg['kc_period'])
    indicators['KC_Mid'] = kc_ema
    indicators['KC_Upper'] = kc_ema + cfg['kc_atr_mult'] * indicators['ATR']
    indicators['KC_Lower'] = kc_ema - cfg['kc_atr_mult'] * indicators['ATR']

    # NOTE (Phase C): the Supertrend proxy that previously lived here was deleted —
    # zero consumers repo-wide, re-verified immediately before deletion. See
    # claude_code/report/strategy_rebuild_phaseC_20260909.md.

    # Squeeze Detection (BB inside KC)
    indicators['Squeeze'] = (
        indicators['BB_Lower'] > indicators['KC_Lower'] and
        indicators['BB_Upper'] < indicators['KC_Upper']
    )

    # Check if was in squeeze recently
    indicators['Was_Squeeze'] = False  # Will be updated with historical data

    # Volume
    vol_sma = sum(volumes[-cfg['vol_sma']:]) / cfg['vol_sma'] if len(volumes) >= cfg['vol_sma'] else sum(volumes) / len(volumes)
    indicators['Vol_SMA'] = vol_sma
    indicators['Vol_Ratio'] = volumes[-1] / vol_sma if vol_sma > 0 else 1

    # Volume Spike Detection (>1.5x average)
    indicators['Volume_Spike'] = indicators['Vol_Ratio'] > volume_spike_multiplier

    # VWAP Calculation (Volume Weighted Average Price)
    # VWAP = Σ(Price × Volume) / Σ(Volume)
    if len(prices) >= 20 and len(volumes) >= 20:
        total_vol = sum(volumes[-60:]) if len(volumes) >= 60 else sum(volumes)
        if total_vol > 0:
            vwap_sum = sum(p * v for p, v in zip(prices[-60:], volumes[-60:])) if len(prices) >= 60 else sum(p * v for p, v in zip(prices, volumes))
            indicators['VWAP'] = vwap_sum / total_vol
        else:
            indicators['VWAP'] = prices[-1]
    else:
        indicators['VWAP'] = prices[-1]

    # VWAP trend (price vs VWAP)
    indicators['Above_VWAP'] = prices[-1] > indicators['VWAP']
    indicators['Below_VWAP'] = prices[-1] < indicators['VWAP']
    indicators['VWAP_Distance_Pct'] = ((prices[-1] - indicators['VWAP']) / indicators['VWAP'] * 100) if indicators['VWAP'] > 0 else 0

    # Momentum (5-period ROC)
    if len(prices) >= 6:
        indicators['MOM'] = (prices[-1] - prices[-6]) / prices[-6] * 100
    else:
        indicators['MOM'] = 0

    # Current price data
    indicators['Close'] = prices[-1]
    indicators['Prev_Close'] = prices[-2] if len(prices) >= 2 else prices[-1]
    indicators['High'] = max(prices[-chunk_size:]) if chunk_size > 0 else prices[-1]
    indicators['Low'] = min(prices[-chunk_size:]) if chunk_size > 0 else prices[-1]

    if runtime_state is not None:
        runtime_state.set_indicators(indicators)

    return indicators


def candle_structure(indicators: Dict) -> Dict:
    """Expose candle shape from the data compute_indicators() already produces
    (Phase D, Rule 11). Additive and read-only: takes an already-built
    indicators dict, computes nothing that feeds back into it, and is not
    called by anything in the live decision path — a Strategy may read it as
    additional evidence, but nothing here gates, scores, or decides.

    IMPORTANT LIMITATIONS, stated rather than worked around:

    This project has no per-candle Open price. compute_indicators()'s chunking
    loop tracks only each chunk's max (High) and min (Low), never its first
    value, so a true body/wick (Open-to-Close, High-to-Open, Open-to-Low)
    cannot be computed from existing data without adding new collection —
    which Rule 11 does not authorize ("existing data থেকে সম্ভব হলে"/"if
    possible from existing data"). Prev_Close was tried as an Open stand-in and
    rejected during implementation: verified empirically that Prev_Close can
    fall outside the current chunk's own [Low, High] band (it belongs to the
    *previous* chunk, computed from a different, non-overlapping price window),
    which produces a negative "wick" — a value with no sensible reading as a
    candle shape. Rather than ship an approximation proven to break, body and
    wick are not exposed at all.

    "Recent candle sequence" (Rule 11's last requested field) is not exposed
    either: compute_indicators() produces one snapshot per call and retains no
    history of prior snapshots, so a sequence cannot be read from existing data
    — it would require new state-tracking, the same "not existing data"
    limitation as Open.

    What IS exposed below is exact, needs no Open, and cannot produce a
    nonsensical value: direction (from Close vs Prev_Close, the same
    comparison pullback_strategy.py already uses for its own Green/Red_Candle
    confirmation — not a new rule, a re-exposure of an existing one), the
    High-Low range, and where Close sits within that range.
    """
    close = indicators.get('Close', 0)
    prev_close = indicators.get('Prev_Close', close)
    high = indicators.get('High', close)
    low = indicators.get('Low', close)

    if close > prev_close:
        direction = 'bullish'
    elif close < prev_close:
        direction = 'bearish'
    else:
        direction = 'neutral'

    candle_range = high - low

    return {
        'direction': direction,
        'range': candle_range,
        # Where Close sits within [Low, High]: 0.0 = at the Low, 1.0 = at the
        # High. Exact — no Open needed. (Same normalization range_position.py
        # already uses for its own, differently-scoped, tick-range measure —
        # this one is per-candle, not per-60-second-tick-window.)
        'close_position_in_range': ((close - low) / candle_range) if candle_range > 0 else 0.5,
        'body_approx': None,        # not exposed — see docstring
        'recent_sequence': None,    # not exposed — see docstring
    }
