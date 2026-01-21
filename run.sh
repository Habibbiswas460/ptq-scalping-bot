#!/bin/bash
# Quick Start - PTQ Bot (Paper Trading)

clear
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🚀 PTQ SCALPING BOT - LIGHTWEIGHT VERSION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  📊 Mode: PAPER TRADING (Safe Testing)"
echo "  💰 Capital: ₹30,000"
echo "  🎯 Strategy: Multi-Level PTQ"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check venv
if [ ! -d "venv" ]; then
    echo "❌ Virtual environment not found!"
    exit 1
fi

# Activate and run
source venv/bin/activate
echo "▶ Starting bot..."
echo ""
python app.py
