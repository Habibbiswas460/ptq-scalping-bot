from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from core.services.database import DB_PATH, get_dvf_reports, get_dvf_signals, get_dvf_trades
from core.validation.validation_report import (
    generate_daily_validation_report,
    generate_monthly_validation_report,
    generate_weekly_validation_report,
    render_daily_validation_report,
)


EXPORT_DIR = Path('logs') / 'dvf_exports'


class DVFExporter:
    def _ensure_export_dir(self) -> Path:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        return EXPORT_DIR

    def export_csv(self, date: str | None = None) -> str:
        export_dir = self._ensure_export_dir()
        target = export_dir / f"dvf_signals_{date or datetime.now().strftime('%Y-%m-%d')}.csv"
        rows = get_dvf_signals(limit=10000)
        if not rows:
            target.write_text('', encoding='utf-8')
            return str(target)
        with target.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return str(target)

    def export_json(self, date: str | None = None) -> str:
        export_dir = self._ensure_export_dir()
        target = export_dir / f"dvf_bundle_{date or datetime.now().strftime('%Y-%m-%d')}.json"
        payload = {
            'signals': get_dvf_signals(limit=10000),
            'trades': get_dvf_trades(limit=10000),
            'reports': get_dvf_reports(limit=100),
        }
        target.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
        return str(target)

    def export_sqlite_snapshot(self, date: str | None = None) -> str:
        export_dir = self._ensure_export_dir()
        target = export_dir / f"dvf_snapshot_{date or datetime.now().strftime('%Y-%m-%d')}.db"
        shutil.copyfile(DB_PATH, target)
        return str(target)

    def export_html(self, date: str | None = None) -> str:
        export_dir = self._ensure_export_dir()
        target = export_dir / f"dvf_report_{date or datetime.now().strftime('%Y-%m-%d')}.html"
        report = generate_daily_validation_report(date)
        body = render_daily_validation_report(report).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        html = f"<html><head><title>DVF Report</title></head><body><pre>{body}</pre></body></html>"
        target.write_text(html, encoding='utf-8')
        return str(target)


_exporter = DVFExporter()


def export_csv(date: str | None = None) -> str:
    return _exporter.export_csv(date)


def export_json(date: str | None = None) -> str:
    return _exporter.export_json(date)


def export_sqlite_snapshot(date: str | None = None) -> str:
    return _exporter.export_sqlite_snapshot(date)


def export_html(date: str | None = None) -> str:
    return _exporter.export_html(date)
