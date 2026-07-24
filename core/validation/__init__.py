"""Decision Validation Framework (DVF).

Golden Rule:
DVF must never influence trading decisions.
It observes.
It records.
It validates.
It never trades.
"""

from core.validation.signal_logger import build_decision_event, log_decision_event
from core.validation.paper_executor import simulate_entry, simulate_exit
from core.validation.decision_replay import replay_decision, replay_trade
from core.validation.calibration_engine import (
	score_calibration,
	confidence_calibration,
	market_quality_calibration,
	position_size_calibration,
)
from core.validation.validation_report import (
	generate_daily_validation_report,
	render_daily_validation_report,
)
