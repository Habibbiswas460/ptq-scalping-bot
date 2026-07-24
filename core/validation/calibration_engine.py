from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from core.services.database import db, save_dvf_calibration


class CalibrationEngine:
    def _date_window(self, days: int, end_date: str | None = None) -> tuple[str, str]:
        anchor = datetime.fromisoformat(end_date) if end_date else datetime.now()
        end = anchor.strftime('%Y-%m-%d')
        start = (anchor - timedelta(days=max(days - 1, 0))).strftime('%Y-%m-%d')
        return start, end

    def score_calibration(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    CASE
                        WHEN weighted_score >= 90 THEN '90+'
                        WHEN weighted_score >= 80 THEN '80-89'
                        WHEN weighted_score >= 70 THEN '70-79'
                        ELSE '<70'
                    END AS score_band,
                    COUNT(*) AS signals,
                    SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) AS accepted,
                    ROUND(AVG(weighted_score), 2) AS avg_score
                FROM dvf_signals
                WHERE date(timestamp) BETWEEN ? AND ?
                  AND weighted_score IS NOT NULL
                GROUP BY score_band
                ORDER BY CASE score_band WHEN '90+' THEN 1 WHEN '80-89' THEN 2 WHEN '70-79' THEN 3 ELSE 4 END
            ''', (start_date, end_date))
            rows = [dict(row) for row in cursor.fetchall()]
        save_dvf_calibration('score', datetime.now().strftime('%Y-%m-%d'), rows)
        return rows

    def confidence_calibration(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    CASE
                        WHEN s.confidence >= 90 THEN '90+'
                        WHEN s.confidence >= 80 THEN '80-89'
                        WHEN s.confidence >= 70 THEN '70-79'
                        ELSE '<70'
                    END AS confidence_band,
                    COUNT(t.id) AS trades,
                    ROUND(AVG(s.confidence), 2) AS avg_confidence_pct,
                    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    ROUND(100.0 * SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(t.id), 0), 2) AS realized_win_rate_pct,
                    ROUND(AVG(s.confidence) - (100.0 * SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(t.id), 0)), 2) AS calibration_error_pct
                FROM dvf_signals s
                JOIN dvf_trades t ON t.decision_id = s.decision_id
                WHERE date(s.timestamp) BETWEEN ? AND ?
                  AND t.status = 'CLOSED'
                  AND s.confidence IS NOT NULL
                GROUP BY confidence_band
                ORDER BY CASE confidence_band WHEN '90+' THEN 1 WHEN '80-89' THEN 2 WHEN '70-79' THEN 3 ELSE 4 END
            ''', (start_date, end_date))
            rows = [dict(row) for row in cursor.fetchall()]
        save_dvf_calibration('confidence', datetime.now().strftime('%Y-%m-%d'), rows)
        return rows

    def market_quality_calibration(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(s.market_quality_grade, 'UNKNOWN') AS grade,
                    COUNT(t.id) AS trades,
                    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    ROUND(100.0 * SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(t.id), 0), 2) AS win_rate_pct,
                    ROUND(AVG(t.pnl), 2) AS avg_pnl
                FROM dvf_signals s
                JOIN dvf_trades t ON t.decision_id = s.decision_id
                WHERE date(s.timestamp) BETWEEN ? AND ?
                  AND t.status = 'CLOSED'
                GROUP BY COALESCE(s.market_quality_grade, 'UNKNOWN')
                ORDER BY CASE COALESCE(s.market_quality_grade, 'UNKNOWN') WHEN 'A+' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END
            ''', (start_date, end_date))
            rows = [dict(row) for row in cursor.fetchall()]
        save_dvf_calibration('market_quality', datetime.now().strftime('%Y-%m-%d'), rows)
        return rows

    def position_size_calibration(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(t.allocation_grade, 'UNKNOWN') AS allocation_grade,
                    COUNT(*) AS trades,
                    ROUND(AVG(t.position_size), 2) AS avg_position_size,
                    ROUND(AVG(t.risk_amount), 2) AS avg_risk_amount,
                    ROUND(AVG(t.pnl), 2) AS avg_pnl,
                    ROUND(AVG(CASE WHEN t.risk_amount > 0 THEN t.pnl / t.risk_amount ELSE 0 END), 4) AS risk_efficiency
                FROM dvf_trades t
                JOIN dvf_signals s ON t.decision_id = s.decision_id
                                WHERE date(s.timestamp) BETWEEN ? AND ?
                  AND t.status = 'CLOSED'
                GROUP BY COALESCE(t.allocation_grade, 'UNKNOWN')
                ORDER BY CASE COALESCE(t.allocation_grade, 'UNKNOWN') WHEN 'A+' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END
                        ''', (start_date, end_date))
            rows = [dict(row) for row in cursor.fetchall()]
        save_dvf_calibration('position_size', datetime.now().strftime('%Y-%m-%d'), rows)
        return rows


_engine = CalibrationEngine()


def score_calibration(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _engine.score_calibration(days, end_date=end_date)


def confidence_calibration(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _engine.confidence_calibration(days, end_date=end_date)


def market_quality_calibration(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _engine.market_quality_calibration(days, end_date=end_date)


def position_size_calibration(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _engine.position_size_calibration(days, end_date=end_date)
