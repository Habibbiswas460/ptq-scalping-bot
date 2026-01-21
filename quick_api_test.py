"""
Simple API Data Test - Check if live data is coming
"""

import json
from brokers.angel_one.client import AngelOneClient
import time

print("=" * 60)
print("🔍 Angel One API - Live Data Test")
print("=" * 60)

# Load credentials
with open('config/credentials.json', 'r') as f:
    creds = json.load(f)
angel_creds = creds['angel_one']

# Initialize and login
print("\n📡 Connecting to Angel One...")
client = AngelOneClient(
    api_key=angel_creds['api_key'],
    client_id=angel_creds['client_id'],
    password=angel_creds['password'],
    totp_token=angel_creds['totp_token']
)

if not client.login():
    print("❌ Login failed")
    exit(1)

print("✅ Login successful!")

# Test with NIFTY index (NSE exchange)
print("\n" + "=" * 60)
print("Test 1: NIFTY Index (NSE)")
print("=" * 60)

# NIFTY 50 index token
nifty_token = "99926000"  # NIFTY 50 symbol token
exchange = "NSE"

try:
    print(f"Fetching LTP for NIFTY (token: {nifty_token})...")
    ltp = client.get_ltp(exchange=exchange, symbol_token=nifty_token)
    
    if ltp:
        print(f"✅ NIFTY LTP: ₹{ltp:.2f}")
        print("\n✓ API is returning LIVE data successfully!")
    else:
        print("❌ No LTP data received")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("✅ Test Complete!")
print("=" * 60)
print("\nConclusion:")
print("- API connection: Working ✓")
print("- Authentication: Working ✓")
print("- Live data fetch: ", end="")
if ltp:
    print("Working ✓")
    print(f"\nCurrent NIFTY price: ₹{ltp:.2f}")
    print("\nYou can now run the bot with USE_LIVE_DATA = True")
else:
    print("Need to verify symbol/token")
