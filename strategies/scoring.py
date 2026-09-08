"""
Scoring / Quality boundary — documentation and integration point only.

No new scoring engine lives here. WeightedScoreEngine and AdaptiveConfidenceEngine
already exist as clean, separate classes in core/engines/ and are not moved by
this module — this file exists only to name the boundary explicitly and re-export
them from the one place strategies/ code should reach for them, so the Strategy
layer's own files don't need to know the engines' exact package path.

The numbers these two engines produce (weighted_score, confidence) are NOT
Strategy PASS/FAIL by themselves — see pullback_strategy.py for the Strategy
Decision and strategies/smart_scalp_v3.py's `sizing_inputs` contract (Phase 6)
for how these numbers reach PositionSizeEngine as quality/sizing inputs, kept
explicitly separate from the Strategy's own PASS/FAIL. Whether weighted_score's
or confidence's threshold check should also continue to gate the Strategy
decision is a trading-rule question flagged, not resolved, in
claude_code/report/strategy_rebuild_phaseA_B_20260909.md's Phase B section —
this module does not change that either way.

No numeric calculation, weight, or formula in either engine was touched.
"""
from __future__ import annotations

from core.engines.weighted_score_engine import WeightedScoreEngine
from core.engines.adaptive_confidence_engine import AdaptiveConfidenceEngine

__all__ = ["WeightedScoreEngine", "AdaptiveConfidenceEngine"]
