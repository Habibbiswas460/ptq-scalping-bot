from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

import core.services.database as database_module


def _coerce_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class DVFAnalytics:
    def _date_window(self, days: int, end_date: str | None = None) -> tuple[str, str]:
        anchor = datetime.fromisoformat(end_date) if end_date else datetime.now()
        end = anchor.strftime('%Y-%m-%d')
        start = (anchor - timedelta(days=max(days - 1, 0))).strftime('%Y-%m-%d')
        return start, end

    def reject_reason_stats(self, days: int = 30, end_date: str | None = None) -> List[Dict]:
        start_date, end_date = self._date_window(days, end_date)
        with database_module.db._get_connection() as conn:
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
        with database_module.db._get_connection() as conn:
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
        with database_module.db._get_connection() as conn:
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
        with database_module.db._get_connection() as conn:
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

    def mfe_mae_summary(self, days: int = 30, end_date: str | None = None) -> Dict:
        start_date, end_date = self._date_window(days, end_date)
        with database_module.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) AS trades,
                    ROUND(AVG(COALESCE(mfe, 0)), 2) AS avg_mfe,
                    ROUND(AVG(COALESCE(mae, 0)), 2) AS avg_mae,
                    ROUND(MAX(COALESCE(mfe, 0)), 2) AS best_mfe,
                    ROUND(MIN(COALESCE(mae, 0)), 2) AS worst_mae
                FROM dvf_trades
                WHERE date(virtual_entry_time) BETWEEN ? AND ?
                  AND status = 'CLOSED'
            ''', (start_date, end_date))
            row = cursor.fetchone()
            if not row:
                return {"trades": 0, "avg_mfe": 0.0, "avg_mae": 0.0, "best_mfe": 0.0, "worst_mae": 0.0}
            return {
                "trades": int(row[0] or 0),
                "avg_mfe": float(row[1] or 0),
                "avg_mae": float(row[2] or 0),
                "best_mfe": float(row[3] or 0),
                "worst_mae": float(row[4] or 0),
            }

    def recent_sessions_trade_mfe_mae_summary(self, days: int = 7, end_date: str | None = None) -> List[Dict]:
        anchor = datetime.fromisoformat(end_date) if end_date else datetime.now()
        start_date = (anchor - timedelta(days=max(days - 1, 0))).strftime('%Y-%m-%d')
        end = anchor.strftime('%Y-%m-%d')
        with database_module.db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    date(entry_time) AS session_date,
                    COUNT(*) AS trade_count,
                    ROUND(MAX(COALESCE(mfe, 0)), 2) AS max_mfe,
                    ROUND(ABS(MIN(COALESCE(mae, 0))), 2) AS max_adverse_move
                FROM trades
                WHERE status = 'CLOSED'
                  AND date(entry_time) BETWEEN ? AND ?
                GROUP BY date(entry_time)
                ORDER BY session_date DESC
            ''', (start_date, end))
            rows = cursor.fetchall()

        row_map = {
            row["session_date"]: {
                "trade_count": int(row["trade_count"] or 0),
                "max_mfe": _coerce_float(row["max_mfe"]),
                "max_adverse_move": _coerce_float(row["max_adverse_move"]),
            }
            for row in rows
        }

        summary: List[Dict] = []
        current = datetime.fromisoformat(end)
        while current >= datetime.fromisoformat(start_date):
            day_key = current.strftime('%Y-%m-%d')
            details = row_map.get(day_key, {"trade_count": 0, "max_mfe": 0.0, "max_adverse_move": 0.0})
            summary.append({
                "session_date": day_key,
                "trade_count": details["trade_count"],
                "max_mfe": details["max_mfe"],
                "max_adverse_move": details["max_adverse_move"],
            })
            current -= timedelta(days=1)
        return summary


_analytics = DVFAnalytics()


def reject_reason_stats(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.reject_reason_stats(days, end_date=end_date)


def session_stats(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.session_stats(days, end_date=end_date)


def regime_stats(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.regime_stats(days, end_date=end_date)


def allocation_analytics(days: int = 30, end_date: str | None = None) -> List[Dict]:
    return _analytics.allocation_analytics(days, end_date=end_date)


def mfe_mae_summary(days: int = 30, end_date: str | None = None) -> Dict:
    return _analytics.mfe_mae_summary(days, end_date=end_date)


def recent_sessions_trade_mfe_mae_summary(days: int = 7, end_date: str | None = None) -> List[Dict]:
    return _analytics.recent_sessions_trade_mfe_mae_summary(days, end_date=end_date)


def compute_trade_mfe_mae_from_ticks(trade: Dict, ticks: List[Dict]) -> Dict:
    entry_price = float(trade.get("entry_price") or 0)
    if entry_price <= 0:
        return {"mfe": 0.0, "mae": 0.0}

    direction = str(trade.get("direction", "CE")).upper()
    qty = int(trade.get("qty") or 1)
    if qty <= 0:
        qty = 1

    best = 0.0
    worst = 0.0
    for tick in ticks or []:
        price = float(tick.get("ltp") or tick.get("price") or 0)
        if price <= 0:
            continue
        if direction == "PE":
            move = (entry_price - price) * qty
        else:
            move = (price - entry_price) * qty
        if move > best:
            best = move
        if move < worst:
            worst = move

    return {"mfe": round(best, 2), "mae": round(worst, 2)}
