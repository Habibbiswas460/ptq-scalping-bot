"""
Market Gate — "is the market tradable right now?"

Answers tradability, not "is this a good setup" (that is the Strategy's job — see
pullback_strategy.py). Two pieces live here, both extracted verbatim from
strategies/smart_scalp_v3.py's generate_signal() as part of the Phase C
architecture modularization; no condition, threshold, or evaluation order changed.

Market Quality itself (spread/liquidity/freshness/volatility/execution/greeks/
session scoring) already lived in its own module before this refactor —
core/engines/market_quality_engine.py's MarketQualityEngine — and stays there
unmoved; it needs `self.market_quality_engine`, the live tick, and the evaluation
timestamp, all of which are generate_signal()'s own context, not pure market
context. build_market_quality_details() below is the piece that WAS duplicated
inline in generate_signal() (five details[...] assignments unpacking the MQ
result) and is now a single, reusable, pure function.

The chop filter's ownership was flagged ambiguous in the Phase A/B forensic
report (candle/EMA/ATR/MACD-shaped, but functions as a market-tradability
veto, not a Strategy confirmation) — it is placed here as a Market Gate
component per that report's proposal, with its logic completely unchanged.
"""
from __future__ import annotations

from typing import Dict, List, Tuple


def build_market_quality_details(market_quality: Dict) -> Dict:
    """Unpack a MarketQualityEngine.evaluate() result into the details keys
    generate_signal() has always published. Verbatim extraction — same five
    keys, same fallback values, same source dict.
    """
    return {
        'market_quality': market_quality,
        'market_quality_pass': market_quality.get('passed', False),
        'market_quality_score': market_quality.get('quality_score', 0),
        'market_quality_grade': market_quality.get('grade', 'REJECT'),
        'market_quality_components': market_quality.get('components', {}),
        'hard_reject_reason': market_quality.get('hard_reject_reason'),
    }


def market_quality_rejection_reason(market_quality: Dict) -> str:
    """The rejection message generate_signal() has always produced when MQ fails.
    Verbatim extraction of the three-way fallback chain.
    """
    return (
        market_quality.get('hard_reject_reason')
        or market_quality.get('reason')
        or f"Market quality gate failed: {market_quality.get('quality_score', 0)}"
    )


def evaluate_chop(indicators: Dict, ema9: float, ema21: float) -> Tuple[bool, List[str]]:
    """Enhanced chop detector (v3.2) — verbatim extraction of generate_signal()'s
    inline block. Three independent criteria (EMA squeeze, low ATR, MACD flat);
    blocks only when all three fire simultaneously (unchanged: 'relaxed from 2+').

    Returns (is_choppy, chop_reason) exactly as the original locals were named.
    """
    ema_diff_pts = abs(ema9 - ema21)
    atr = indicators.get('ATR', 50)
    macd_hist = indicators.get('MACD_Hist', 0)
    macd_hist_prev = indicators.get('MACD_Hist_Prev', 0)

    # Chop Detection Criteria:
    # 1. EMA squeeze (basic) - increased threshold
    min_ema_separation = 0.8  # Slightly relaxed to avoid over-blocking valid pullbacks

    # 2. Low ATR = low volatility = choppy
    # Note: Option ATR is much smaller than index (0-10 vs 30-100)
    low_atr_threshold = 3  # Treat only very low ATR as chop for option premium flow

    # 3. MACD histogram flattening (momentum dying)
    macd_flat = abs(macd_hist) < 0.25 and abs(macd_hist - macd_hist_prev) < 0.2

    is_choppy = False
    chop_reason: List[str] = []

    if ema_diff_pts < min_ema_separation:
        is_choppy = True
        chop_reason.append(f"EMA squeeze ({ema_diff_pts:.1f}pts)")

    if atr < low_atr_threshold:
        is_choppy = True
        chop_reason.append(f"Low ATR ({atr:.0f})")

    if macd_flat:
        is_choppy = True
        chop_reason.append("MACD flat")

    # Block only if ALL 3 chop indicators fire (relaxed from 2+)
    return len(chop_reason) >= 3, chop_reason
