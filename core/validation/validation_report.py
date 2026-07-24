from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from core.services.database import db, save_dvf_report
from core.validation.analytics import allocation_analytics, reject_reason_stats, regime_stats, session_stats
from core.validation.calibration_engine import (
    confidence_calibration,
    market_quality_calibration,
    position_size_calibration,
    score_calibration,
)


class ValidationReportEngine:
    def _report_window(self, report_type: str) -> int:
        return {
            'daily': 1,
            'weekly': 7,
            'monthly': 30,
        }.get(report_type, 1)

    def _parse_date(self, value: str | None) -> datetime:
        if not value:
            return datetime.now()
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.now()

    def _signal_summary(self, days: int, report_date: str) -> Dict:
        anchor = self._parse_date(report_date)
        start_date = (anchor - timedelta(days=max(days - 1, 0))).strftime('%Y-%m-%d')
        end_date = anchor.strftime('%Y-%m-%d')
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT
                    COUNT(*) AS total_signals,
                    SUM(CASE WHEN accepted = 1 THEN 1 ELSE 0 END) AS accepted,
                    SUM(CASE WHEN rejected = 1 THEN 1 ELSE 0 END) AS rejected
                FROM dvf_signals
                WHERE date(timestamp) BETWEEN ? AND ?
            ''', (start_date, end_date))
            row = cursor.fetchone()
            return dict(row) if row else {"total_signals": 0, "accepted": 0, "rejected": 0}

    def generate_report(self, report_type: str = 'daily', date: str | None = None) -> Dict:
        days = self._report_window(report_type)
        report_date = date or datetime.now().strftime('%Y-%m-%d')
        report = {
            'report_type': report_type,
            'report_date': report_date,
            'generated_at': datetime.now().isoformat(timespec='seconds'),
            'signal_summary': self._signal_summary(days, report_date),
            'reject_reasons': reject_reason_stats(days, end_date=report_date),
            'score_calibration': score_calibration(days, end_date=report_date),
            'confidence_calibration': confidence_calibration(days, end_date=report_date),
            'market_quality_calibration': market_quality_calibration(days, end_date=report_date),
            'position_size_calibration': position_size_calibration(days, end_date=report_date),
            'session_stats': session_stats(days, end_date=report_date),
            'regime_stats': regime_stats(days, end_date=report_date),
            'allocation_analytics': allocation_analytics(days, end_date=report_date),
        }
        save_dvf_report(report_type, report_date, report)
        return report

    def render_report(self, report: Dict) -> str:
        lines: List[str] = []
        lines.append('=' * 72)
        lines.append(f"DVF {report['report_type'].upper()} REPORT")
        lines.append('=' * 72)
        lines.append(f"Date: {report['report_date']}")
        lines.append(f"Generated: {report['generated_at']}")
        lines.append('')

        summary = report['signal_summary']
        lines.append('[1] Signal Summary')
        lines.append(f"Total: {summary.get('total_signals', 0)}")
        lines.append(f"Accepted: {summary.get('accepted', 0)}")
        lines.append(f"Rejected: {summary.get('rejected', 0)}")
        lines.append('')

        lines.append('[2] Top Reject Reasons')
        if not report['reject_reasons']:
            lines.append('(no data)')
        else:
            for row in report['reject_reasons'][:10]:
                lines.append(f"{row.get('count', 0):>6}  {row.get('reason', 'UNKNOWN')}")
        lines.append('')

        for title, key in [
            ('[3] Score Calibration', 'score_calibration'),
            ('[4] Confidence Calibration', 'confidence_calibration'),
            ('[5] Market Quality Calibration', 'market_quality_calibration'),
            ('[6] Position Size Calibration', 'position_size_calibration'),
            ('[7] Session Stats', 'session_stats'),
            ('[8] Regime Stats', 'regime_stats'),
            ('[9] Allocation Analytics', 'allocation_analytics'),
        ]:
            lines.append(title)
            rows = report.get(key, [])
            if not rows:
                lines.append('(no data)')
            else:
                for row in rows:
                    lines.append(str(row))
            lines.append('')

        return '\n'.join(lines)


_engine = ValidationReportEngine()


def generate_daily_validation_report(date: str | None = None) -> Dict:
    return _engine.generate_report('daily', date)


def generate_weekly_validation_report(date: str | None = None) -> Dict:
    return _engine.generate_report('weekly', date)


def generate_monthly_validation_report(date: str | None = None) -> Dict:
    return _engine.generate_report('monthly', date)


def render_daily_validation_report(report: Dict) -> str:
    return _engine.render_report(report)
