"""
Pullback Strategy — the first, and currently only, real Strategy in this system.

Answers "is this a recognizable trading setup?" — nothing about market
tradability (Market Gate's job, market_gate.py) and nothing about how much size
a setup deserves (Sizing's job, downstream of the Strategy Decision).

Byte-for-byte extraction of SmartScalpV3.evaluate_pullback_strategy() (itself a
byte-for-byte extraction from generate_signal(), Phase 3) as part of the Phase C
architecture modularization. No condition, threshold, or evaluation order
changed — self.min_score / VWAP_ENABLED / OI_CHANGE_ENABLED are now explicit
parameters instead of attribute/module-global reads, which is the only
mechanical change; every comparison and every point value is identical.
"""
from __future__ import annotations

import logging
from typing import Dict, List


def evaluate_pullback_strategy(
    indicators: Dict,
    oi_direction: str,
    min_score: int,
    vwap_enabled: bool,
    oi_change_enabled: bool,
) -> Dict:
    """
    PULLBACK strategy — the explicit Strategy boundary.

    Returns the same six values generate_signal() has always consumed
    (ce_signal/ce_score/ce_factors/pe_signal/pe_score/pe_factors), plus an
    'observability' block that makes the trend/trigger/confirmation breakdown
    inspectable without changing what it decides.
    """
    close = indicators.get('Close', 0)
    prev_close = indicators.get('Prev_Close', 0)
    high = indicators.get('High', 0)
    low = indicators.get('Low', 0)
    ema9 = indicators.get('EMA_9', 0)
    ema21 = indicators.get('EMA_21', 0)
    rsi = indicators.get('RSI', 50)

    # ====== PULLBACK LOGIC FOR CE (BULLISH) ======
    # Balanced scoring - conditions are independent, not nested
    # Score 4+ needed for signal (out of 12 possible with v3.1 additions)

    ce_signal = False
    ce_score = 0
    ce_factors = []
    ce_trend_pass = ema9 > ema21
    ce_trigger_pass = False
    ce_confirmations: Dict[str, bool] = {}

    # Condition 1: Trend UP (EMA9 > EMA21) - Required
    if ce_trend_pass:
        ce_factors.append("EMA9>21")
        ce_score += 2

        # Condition 2: Pullback to EMA9 support (within 0.5%)
        ema9_proximity = abs(low - ema9) / ema9 * 100 if ema9 > 0 else 999
        ce_trigger_pass = ema9_proximity < 0.5 or low <= ema9 <= close
        if ce_trigger_pass:
            ce_factors.append("EMA9_Pullback")
            ce_score += 2

        # Condition 3: Green candle (bullish)
        ce_confirmations['candle'] = close > prev_close
        if ce_confirmations['candle']:
            ce_factors.append("Green_Candle")
            ce_score += 1
            # Extra point if close above EMA9
            if close > ema9:
                ce_factors.append("Close>EMA9")
                ce_score += 1

        # Condition 4: RSI confirmation (relaxed: > 45)
        ce_confirmations['rsi'] = rsi > 45
        if ce_confirmations['rsi']:
            ce_factors.append(f"RSI({rsi:.0f})>45")
            ce_score += 1
            # Extra point for strong momentum
            if rsi > 55:
                ce_score += 1

        # ═══════════════════════════════════════════════════════════════
        # v3.1 NEW FACTORS
        # ═══════════════════════════════════════════════════════════════

        # Factor 5: VWAP Confirmation (price > VWAP = bullish bias)
        ce_confirmations['vwap'] = bool(vwap_enabled and indicators.get('Above_VWAP', False))
        if ce_confirmations['vwap']:
            ce_factors.append("Above_VWAP")
            ce_score += 1

        # Factor 6: Volume Spike (strong interest)
        ce_confirmations['volume'] = bool(indicators.get('Volume_Spike', False) and close > prev_close)
        if ce_confirmations['volume']:
            ce_factors.append(f"Vol_Spike({indicators.get('Vol_Ratio', 1):.1f}x)")
            ce_score += 1

        # Factor 7: OI confirms bullish (Long buildup)
        ce_confirmations['oi'] = bool(oi_change_enabled and oi_direction in ["LONG_BUILDUP", "SHORT_COVERING"])
        if ce_confirmations['oi']:
            ce_factors.append(f"OI_{oi_direction}")
            ce_score += 1

        # Signal if score >= configured threshold (default 4)
        # VWAP/OI/Volume boost confidence for position sizing, not gatekeeping
        if ce_score >= min_score:
            ce_signal = True

    # ====== PULLBACK LOGIC FOR PE (BEARISH) ======
    # Balanced scoring - conditions are independent, not nested
    # Score 4+ needed for signal (v3.4: relaxed from 5)

    pe_signal = False
    pe_score = 0
    pe_factors = []
    pe_trend_pass = ema9 < ema21
    pe_trigger_pass = False
    pe_confirmations: Dict[str, bool] = {}

    # Condition 1: Trend DOWN (EMA9 < EMA21) - Required
    if pe_trend_pass:
        pe_factors.append("EMA9<21")
        pe_score += 2

        # Condition 2: Rejection at EMA9 resistance (within 0.5%)
        ema9_proximity = abs(high - ema9) / ema9 * 100 if ema9 > 0 else 999
        pe_trigger_pass = ema9_proximity < 0.5 or close <= ema9 <= high
        if pe_trigger_pass:
            pe_factors.append("EMA9_Rejection")
            pe_score += 2

        # Condition 3: Red candle (bearish)
        pe_confirmations['candle'] = close < prev_close
        if pe_confirmations['candle']:
            pe_factors.append("Red_Candle")
            pe_score += 1
            # Extra point if close below EMA9
            if close < ema9:
                pe_factors.append("Close<EMA9")
                pe_score += 1

        # Condition 4: RSI confirmation (PHASE 2: stricter RSI < 45)
        pe_confirmations['rsi'] = rsi < 45
        if pe_confirmations['rsi']:
            pe_factors.append(f"RSI({rsi:.0f})<45")
            pe_score += 1
            # Extra point for strong momentum
            if rsi < 35:
                pe_score += 1

        # ═══════════════════════════════════════════════════════════════
        # v3.1 NEW FACTORS
        # ═══════════════════════════════════════════════════════════════

        # Factor 5: VWAP Confirmation (price < VWAP = bearish bias)
        pe_confirmations['vwap'] = bool(vwap_enabled and indicators.get('Below_VWAP', False))
        if pe_confirmations['vwap']:
            pe_factors.append("Below_VWAP")
            pe_score += 1

        # Factor 6: Volume Spike (strong selling interest)
        pe_confirmations['volume'] = bool(indicators.get('Volume_Spike', False) and close < prev_close)
        if pe_confirmations['volume']:
            pe_factors.append(f"Vol_Spike({indicators.get('Vol_Ratio', 1):.1f}x)")
            pe_score += 1

        # Factor 7: OI confirms bearish (Short buildup)
        pe_confirmations['oi'] = bool(oi_change_enabled and oi_direction in ["SHORT_BUILDUP", "LONG_UNWINDING"])
        if pe_confirmations['oi']:
            pe_factors.append(f"OI_{oi_direction}")
            pe_score += 1

        # Signal if score >= configured threshold (default 4)
        if pe_score >= min_score:
            pe_signal = True

    def _reason(trend_pass, trigger_pass, confirmations, signal):
        if not trend_pass:
            return "trend"
        if not trigger_pass:
            return "pullback_trigger"
        if not signal:
            return "confirmation_score"
        return None

    observability = {
        "CE": {
            "trend": "PASS" if ce_trend_pass else "FAIL",
            "trigger": "PASS" if ce_trigger_pass else "FAIL",
            "confirmations": {k: ("PASS" if v else "FAIL") for k, v in ce_confirmations.items()},
            "final": "PASS" if ce_signal else "FAIL",
            "reason": _reason(ce_trend_pass, ce_trigger_pass, ce_confirmations, ce_signal),
        },
        "PE": {
            "trend": "PASS" if pe_trend_pass else "FAIL",
            "trigger": "PASS" if pe_trigger_pass else "FAIL",
            "confirmations": {k: ("PASS" if v else "FAIL") for k, v in pe_confirmations.items()},
            "final": "PASS" if pe_signal else "FAIL",
            "reason": _reason(pe_trend_pass, pe_trigger_pass, pe_confirmations, pe_signal),
        },
    }

    for direction, o in observability.items():
        if o["final"] == "PASS":
            confs = " ".join(f"{k}={v}" for k, v in o["confirmations"].items())
            logging.debug(
                "STRATEGY_PULLBACK direction=%s trend=%s trigger=%s %s result=PASS",
                direction, o["trend"], o["trigger"], confs,
            )
        elif o["trend"] == "PASS":
            # Only log a rejection when the trend precondition at least held —
            # logging every trend=FAIL tick would flood the debug log at the
            # 500ms polling rate with no additional information (trend=FAIL
            # already means neither side of the pullback can fire).
            logging.debug(
                "STRATEGY_PULLBACK direction=%s trend=%s trigger=%s result=FAIL reason=%s",
                direction, o["trend"], o["trigger"], o["reason"],
            )

    return {
        "ce_signal": ce_signal,
        "ce_score": ce_score,
        "ce_factors": ce_factors,
        "pe_signal": pe_signal,
        "pe_score": pe_score,
        "pe_factors": pe_factors,
        "observability": observability,
    }


def as_candidates(pullback_result: Dict) -> List[Dict]:
    """Reshape evaluate_pullback_strategy()'s result into the normalized
    "strategy candidate" shape (Phase D, Rule 5): one entry per direction that
    reached at least the trend precondition, so a future Strategy Selector
    handling multiple strategies has one common format to compare across them.

    Purely additive and purely a reshaping — every field here is read directly
    from what evaluate_pullback_strategy() already computed; nothing is
    recalculated, no threshold is re-applied, and ce_signal/pe_signal (the
    actual gating booleans) are unchanged by this function's existence. Callers
    that already use the dict returned by evaluate_pullback_strategy() directly
    are unaffected — this is a second view of the same data, not a replacement.

    Only directions whose trend precondition held are included (an entry whose
    trend failed carries no score, no factors, and no confirmation detail worth
    comparing — evaluate_pullback_strategy() itself never scored it beyond the
    fixed 0). A direction is included regardless of whether it ultimately
    passed, so a Selector can see *why* a candidate lost, not just that it did.
    """
    candidates: List[Dict] = []
    for direction, score_key, factors_key in (
        ("CE", "ce_score", "ce_factors"),
        ("PE", "pe_score", "pe_factors"),
    ):
        obs = pullback_result["observability"][direction]
        if obs["trend"] != "PASS":
            continue
        candidates.append({
            "strategy": "pullback",
            "direction": direction,
            "passed": obs["final"] == "PASS",
            "score": pullback_result[score_key],
            "reason": obs["reason"],
            "factors": {
                "trend": obs["trend"],
                "trigger": obs["trigger"],
                "confirmations": obs["confirmations"],
                "factor_list": pullback_result[factors_key],
            },
        })
    return candidates
