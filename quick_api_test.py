"""
Simple API Data Test - Check if live data is coming
"""

import json
from brokers.angel_one.client import AngelOneClient
from live_data_fetcher import LiveDataFetcher
import time

print("=" * 60)
print("🔍 PTQ Bot - API & Live Data Test")
print("=" * 60)

# Test 1: Yahoo Finance (Free - No credentials needed)
print("\n📊 Test 1: Yahoo Finance (Free)")
print("-" * 40)

ldf = LiveDataFetcher()
spot = ldf.get_nifty_spot()
if spot:
    print(f"✅ NIFTY Spot: ₹{spot:,.2f}")
else:
    print("❌ Failed to fetch from Yahoo Finance")

# Test 2: Option price estimation
print("\n📊 Test 2: Option Price Estimation")
print("-" * 40)

if spot:
    strike = round(spot / 50) * 50  # ATM strike
    tick = ldf.get_market_tick(strike=strike, option_type="CE")
    if tick:
        print(f"✅ Strike: {strike}CE")
        print(f"   LTP: ₹{tick['ltp']:.2f}")
        print(f"   Bid/Ask: ₹{tick['bid']:.2f} / ₹{tick['ask']:.2f}")
        print(f"   Spot: ₹{tick['spot_price']:,.2f}")

# Test 3: Angel One API (Optional - needs credentials)
print("\n📊 Test 3: Angel One API")
print("-" * 40)

try:
    # Load credentials
    with open('config/credentials.json', 'r') as f:
        creds = json.load(f)
    angel_creds = creds['angel_one']
    
    # Check if credentials are configured
    if angel_creds.get('api_key', '').startswith('YOUR_'):
        print("⚠️  Angel One credentials not configured")
        print("   Edit config/credentials.json with your API details")
    else:
        print("📡 Connecting to Angel One...")
        client = AngelOneClient(
            api_key=angel_creds['api_key'],
            client_id=angel_creds['client_id'],
            password=angel_creds['password'],
            totp_secret=angel_creds['totp_token']  # Note: totp_secret param
        )
        
        if client.login():
            print("✅ Login successful!")
            
            # Get profile
            profile = client.get_profile()
            if profile:
                print(f"   User: {profile.get('name', 'Unknown')}")
            
            # Get funds
            funds = client.get_funds()
            if funds:
                print(f"   Available: ₹{funds.get('availablecash', 0):,.2f}")
            
            client.logout()
            print("✅ Logout successful!")
        else:
            print("❌ Login failed")
            
except FileNotFoundError:
    print("⚠️  credentials.json not found")
    print("   Copy credentials.json.example to credentials.json")
except Exception as e:
    print(f"❌ Angel One test error: {e}")

# Summary
print("\n" + "=" * 60)
print("📋 Summary")
print("=" * 60)
print(f"✅ Yahoo Finance: Working (NIFTY @ ₹{spot:,.2f})" if spot else "❌ Yahoo Finance: Failed")
print("✅ Option Pricing: Working" if tick else "❌ Option Pricing: Failed")
print("\n💡 The bot can run in Paper Trading mode with Yahoo Finance data!")
print("   Edit app.py: PAPER_TRADING = True, USE_LIVE_DATA = True")

