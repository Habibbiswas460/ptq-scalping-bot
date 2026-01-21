#!/usr/bin/env python3
"""
Test Live Data Connection
Quick test to verify if live data is working
"""

import json
from brokers.angel_one import AngelOneClient

def test_connection():
    """Test Angel One connection and live data"""
    
    print("=" * 60)
    print("Testing Angel One Live Data Connection")
    print("=" * 60)
    
    # Load credentials
    try:
        with open('config/credentials.json', 'r') as f:
            creds = json.load(f)
            angel_creds = creds['angel_one']
    except Exception as e:
        print(f"❌ Error loading credentials: {e}")
        print("\n💡 Make sure config/credentials.json has valid Angel One credentials")
        return False
    
    # Check if credentials are filled
    if angel_creds['api_key'] == "YOUR_API_KEY_HERE":
        print("⚠️  Using dummy credentials (won't connect to live data)")
        print("\n📝 To enable live data:")
        print("   1. Get API credentials from Angel One")
        print("   2. Update config/credentials.json with real values")
        print("   3. Run this test again")
        print("\n✅ Bot will run with SIMULATED data (safe for testing)")
        return False
    
    # Try to connect
    print("\n🔌 Attempting to connect...")
    try:
        client = AngelOneClient(
            api_key=angel_creds['api_key'],
            client_id=angel_creds['client_id'],
            password=angel_creds['password'],
            totp_token=angel_creds['totp_token']
        )
        
        if client.login():
            print("✅ Login successful!")
            
            # Test fetching live data
            print("\n📊 Testing live market data fetch...")
            
            # Example: NIFTY option (update symbol as needed)
            test_symbol = "NIFTY2401724800CE"
            tick = client.get_market_tick(test_symbol, "NFO")
            
            if tick:
                print(f"✅ Live data received!")
                print(f"\n📈 Live Tick Data:")
                print(f"   Symbol: {tick.get('symbol', 'N/A')}")
                print(f"   LTP: ₹{tick.get('ltp', 0):.2f}")
                print(f"   Bid: ₹{tick.get('bid', 0):.2f}")
                print(f"   Ask: ₹{tick.get('ask', 0):.2f}")
                print(f"   Volume: {tick.get('volume', 0):,}")
                print(f"\n🎉 Live data connection working!")
                return True
            else:
                print("⚠️  Could not fetch live data (symbol might be invalid)")
                print("   Bot will use simulated data")
                return False
        else:
            print("❌ Login failed!")
            print("   Check credentials in config/credentials.json")
            print("   Bot will use simulated data")
            return False
            
    except Exception as e:
        print(f"❌ Error: {e}")
        print("   Bot will use simulated data")
        return False


if __name__ == "__main__":
    print()
    success = test_connection()
    print("\n" + "=" * 60)
    if success:
        print("✅ Ready to run bot with LIVE DATA (paper trading mode)")
    else:
        print("ℹ️  Bot will run with SIMULATED DATA (safe testing mode)")
    print("=" * 60)
    print()
