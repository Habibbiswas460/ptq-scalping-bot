from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from core.services.database import db


class DVFAnalytics:
    def _date_window(self, days: int, end_date: str | None = None) -> tuple[str, str]:
        anchor = datetime.fromisoformat(end_date) if end_date else datetime.now()
        end = anchor.strftime('%Y-%m-%d')
        start = (anchor - timedelta(days=max(days - 1, 0))).strftime('%Y-%m-%d')
        return start, end

    def reject_reason_stats(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COALESCE(reject_reason, 'UNKNOWN') AS reason, COUNT(*) AS count
                FROM dvf_signals
                WHERE date(timestamp) BETWEEN ? AND ?
                  AND rejected = 1
                GROUP BY COALESCE(reject_reason, 'UNKNOWN')
                ORDER BY count DESC
            ''', (start_date, end_date))
            return [dict(row) for row in cursor.fetchall()]

    def session_stats(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(s.session_type, 'UNKNOWN') AS session_type,
                    COUNT(t.id) AS trades,
                    SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    ROUND(AVG(t.pnl), 2) AS avg_pnl,
                    ROUND(100.0 * SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(t.id), 0), 2) AS win_rate_pct
                FROM dvf_signals s
                LEFT JOIN dvf_trades t ON t.decision_id = s.decision_id AND t.status = 'CLOSED'
                WHERE date(s.timestamp) BETWEEN ? AND ?
                GROUP BY COALESCE(s.session_type, 'UNKNOWN')
            ''', (start_date, end_date))
            return [dict(row) for row in cursor.fetchall()]

    def regime_stats(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(regime, 'UNKNOWN') AS regime,
                    COUNT(t.id) AS trades,
                    ROUND(AVG(t.pnl), 2) AS avg_pnl,
                    ROUND(100.0 * SUM(CASE WHEN t.pnl > 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(t.id), 0), 2) AS win_rate_pct
                FROM dvf_signals s
                LEFT JOIN dvf_trades t ON t.decision_id = s.decision_id AND t.status = 'CLOSED'
                WHERE date(s.timestamp) BETWEEN ? AND ?
                GROUP BY COALESCE(regime, 'UNKNOWN')
            ''', (start_date, end_date))
            return [dict(row) for row in cursor.fetchall()]

    def allocation_analytics(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COALESCE(allocation_grade, 'UNKNOWN') AS allocation_grade,
                    COUNT(*) AS trades,
                    ROUND(AVG(pnl), 2) AS avg_pnl,
                    ROUND(AVG(CASE WHEN risk_amount > 0 THEN pnl / risk_amount ELSE 0 END), 4) AS avg_risk_efficiency
                FROM dvf_trades
                                WHERE date(virtual_entry_time) BETWEEN ? AND ?
                  AND status = 'CLOSED'
                GROUP BY COALESCE(allocation_grade, 'UNKNOWN')
                ORDER BY CASE COALESCE(allocation_grade, 'UNKNOWN') WHEN 'A+' THEN 1 WHEN 'A' THEN 2 WHEN 'B' THEN 3 WHEN 'C' THEN 4 ELSE 5 END
                        ''', (start_date, end_date))
            return [dict(row) for row in cursor.fetchall()]


_analytics = DVFAnalytics()


def reject_reason_stats(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.reject_reason_stats(days, end_date=end_date)


def session_stats(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.session_stats(days, end_date=end_date)


def regime_stats(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.regime_stats(days, end_date=end_date)


def allocation_analytics(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.allocation_analytics(days, end_date=end_date)
