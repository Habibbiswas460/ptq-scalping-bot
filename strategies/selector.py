"""
Strategy Selector — resolves which strategy's candidate proceeds, when more than
one strategy is active.

Today, exactly one strategy exists (Pullback — see pullback_strategy.py; the
Phase A/B forensic report confirmed zero other strategy implementations, live or
dead, and zero existing priority/conflict-resolution logic anywhere in this
repository). This module is therefore intentionally thin: it resolves CE vs PE
within that one strategy's own result, and stops there. It does NOT invent a
priority or conflict-resolution rule between multiple strategies, because no
such rule currently exists to extract, and Rule 7 of the Phase C rebuild brief
explicitly forbids inventing one.

When a second strategy is added in a future phase, this is the module that
should grow a real selection contract (which strategies are applicable, whether
they agree, how a genuine conflict is resolved) — at that point there will be
real behaviour to extract instead of a rule to invent.
"""
from __future__ import annotations

from typing import Dict, List, Optional


def select_strategy(strategy_results: List[Dict]) -> Optional[Dict]:
    """Given a list of normalized strategy-candidate dicts (the shape
    pullback_strategy.as_candidates() produces — {"strategy", "direction",
    "passed", "score", "reason", "factors"}), return the one candidate that
    should proceed, or None if none passed.

    Phase D, Rule 7's forward-looking interface. Today exactly one strategy
    (pullback) can ever contribute candidates, and CE is listed before PE in
    that list (as_candidates() preserves the same order select_direction()
    below has always used) — so this returns the identical choice
    select_direction() would, by construction, not by a newly invented rule.

    When a second strategy exists, `strategy_results` will genuinely contain
    candidates from more than one strategy, and this is the function that
    should grow real conflict-resolution logic then — there is nothing to
    invent that logic from yet (Phase A/B's forensic audit found zero existing
    priority/conflict rule anywhere in this repository, re-confirmed in Phase D's
    own audit), so none is added here. If more than one candidate ever passes
    simultaneously before that logic exists, this raises rather than silently
    guessing a winner.
    """
    passed = [c for c in strategy_results if c.get("passed")]
    if not passed:
        return None
    if len(passed) > 1:
        raise ValueError(
            "select_strategy(): more than one strategy candidate passed "
            f"simultaneously ({[c.get('strategy') + '/' + c.get('direction', '') for c in passed]}) "
            "and no conflict-resolution rule exists to choose between them. "
            "This should not happen with a single strategy (pullback's CE and "
            "PE trend preconditions are mutually exclusive) — if it does, stop "
            "and report per Phase D Rule 20 rather than picking one."
        )
    return passed[0]


def select_direction(pullback_result: Dict) -> Optional[str]:
    """Given evaluate_pullback_strategy()'s result, return which direction's
    candidate should proceed to weighted-score/exhaustion/confidence, or None
    if neither passed the Strategy's own trigger/confirmation stage.

    CE is checked first — this is the order generate_signal() has always used
    (its CE block runs, and can return, before its PE block is ever reached).
    Documenting rather than inventing: ce_signal and pe_signal are mutually
    exclusive by construction (CE requires EMA9 > EMA21, PE requires
    EMA9 < EMA21 — both cannot hold at once), so this order has never actually
    changed which direction gets selected; it only fixes what happens to be
    checked first in code. No priority rule was added.
    """
    if pullback_result.get("ce_signal"):
        return "CE"
    if pullback_result.get("pe_signal"):
        return "PE"
    return None
