"""
Unit Tests for Analytics Module
Tests trade analytics, reporting, and period analysis
"""

import pytest
import os
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


class TestTradeAnalytics:
    """Test TradeAnalytics class"""
    
    def test_analytics_class_exists(self):
        """Test TradeAnalytics class can be imported"""
        from utils.analytics import TradeAnalytics
        assert TradeAnalytics is not None
    
    def test_analytics_initialization(self):
        """Test TradeAnalytics initializes with default log_dir"""
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()
        assert analytics.log_dir == "logs"
    
    def test_analytics_custom_log_dir(self):
        """Test TradeAnalytics accepts custom log_dir"""
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics(log_dir="/custom/path")
        assert analytics.log_dir == "/custom/path"


class TestMetricsCalculation:
    """Test metrics calculation functions"""
    
    def test_empty_metrics(self):
        """Test _empty_metrics returns proper structure"""
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()
        metrics = analytics._empty_metrics()
        
        assert 'summary' in metrics
        assert 'pnl' in metrics
        assert 'time' in metrics
        assert 'streaks' in metrics
        assert 'exit_reasons' in metrics
        assert 'hourly_pnl' in metrics
    
    def test_empty_metrics_summary_fields(self):
        """Test empty metrics has all summary fields"""
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()
        metrics = analytics._empty_metrics()
        
        summary = metrics['summary']
        assert 'total_trades' in summary
        assert 'winners' in summary
        assert 'losers' in summary
        assert 'win_rate' in summary
        assert 'profit_factor' in summary
    
    def test_calculate_metrics_with_empty_list(self):
        """Test calculate_metrics handles empty trade list"""
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()
        metrics = analytics.calculate_metrics([])
        
        assert metrics['summary']['total_trades'] == 0
        assert metrics['pnl']['total_pnl'] == 0


class TestPeriodAnalysis:
    """Test period analysis functions"""
    
    def test_analyze_period_function_exists(self):
        """Test analyze_period function exists"""
        from utils.analytics import analyze_period
        assert callable(analyze_period)
    
    def test_analyze_weekly_function_exists(self):
        """Test analyze_weekly function exists"""
        from utils.analytics import analyze_weekly
        assert callable(analyze_weekly)
    
    def test_analyze_monthly_function_exists(self):
        """Test analyze_monthly function exists"""
        from utils.analytics import analyze_monthly
        assert callable(analyze_monthly)
    
    def test_get_best_worst_hours_exists(self):
        """Test get_best_worst_hours function exists"""
        from utils.analytics import get_best_worst_hours
        assert callable(get_best_worst_hours)
    
    def test_print_trading_calendar_exists(self):
        """Test print_trading_calendar function exists"""
        from utils.analytics import print_trading_calendar
        assert callable(print_trading_calendar)


class TestReportGeneration:
    """Test report generation"""
    
    def test_generate_report_method_exists(self):
        """Test generate_report method exists"""
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()
        assert hasattr(analytics, 'generate_report')
        assert callable(analytics.generate_report)
    
    def test_save_report_method_exists(self):
        """Test save_report method exists"""
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()
        assert hasattr(analytics, 'save_report')
        assert callable(analytics.save_report)


class TestExitReasonCategorization:
    """Exit reasons are grouped by the label the engine stamps on them.

    These cases used to be written against strings nobody produces -- "Stop Loss hit",
    "TP-1 partial", "Trailing stop hit". None of the six appears in exit_engine.py or in
    any of the 131 recorded trades, so the classifier was being checked against an
    invented vocabulary while its behaviour on the real one went unexamined: it filed 62%
    of trades as "Other", put Early Loss Cut under Stop Loss because the explanation ends
    "(saved 2.8pts vs SL)", and reported trades with no exit as clean market closes.

    Every string below is verbatim from core/data/trades.db. tests/test_exit_reason_
    categories.py covers the edges and pins the table against the engine's own labels.
    """

    def test_categorize_exit_reason_stop_loss(self):
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()

        assert analytics._categorize_exit_reason(
            "\U0001f6d1 HARD SL HIT | PE | -6pts @ \u20b9178.45 | Loss: \u20b9390") == "Hard Stop Loss"

    def test_categorize_exit_reason_take_profit(self):
        # This engine takes profit in one step; the TP-1/TP-2/TP-3 tiers the old cases
        # asserted are not something it can emit.
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()

        assert analytics._categorize_exit_reason(
            "\U0001f3af TAKE PROFIT | CE | +13.8pts @ \u20b9141.32 | Profit: \u20b9894") == "Take Profit"

    def test_categorize_exit_reason_trailing(self):
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()

        assert analytics._categorize_exit_reason(
            "\u2705 TRAILING PROFIT | CE | +9pts | Locked: \u20b9585") == "Trailing Profit"

    def test_categorize_exit_reason_kill_switch(self):
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()

        assert analytics._categorize_exit_reason("Kill switch: Wide spread KILL") == "Kill Switch"

    def test_categorize_exit_reason_rsi(self):
        # The most common exit in the book, and the one the old table could not see.
        from utils.analytics import TradeAnalytics
        analytics = TradeAnalytics()

        assert analytics._categorize_exit_reason(
            "\U0001f504 RSI REVERSAL EXIT | PE | RSI 7\u219255 | Lock: \u20b9107") == "RSI Reversal"


class TestInteractiveAnalytics:
    """Test interactive analytics function"""
    
    def test_interactive_analytics_exists(self):
        """Test interactive_analytics function exists"""
        from utils.analytics import interactive_analytics
        assert callable(interactive_analytics)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
