"""
PTQ Scalping Bot - Broker Interface
All broker I/O operations (connect, tick, orders)
Pure broker-based data - NO Yahoo Finance
"""

import json
import time
import math
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from brokers.angel_one import AngelOneClient
from utils.logger import BotLogger

from config.constants import (
    PAPER_TRADING, USE_LIVE_DATA, STOP_LOSS_AMOUNT,
    OPTION_TYPE, EXCHANGE, STOP_LOSS_PCT,
    LOG_DIRECTORY, LOG_CONSOLE
)
from utils.helpers import current_time_ms


class BrokerInterface:
    """Broker interface for Angel One"""
    
    def __init__(self):
        self.broker_client: Optional[AngelOneClient] = None
        self.logger: Optional[BotLogger] = None
        
        # Trading state
        self.current_symbol: Optional[str] = None
        self.current_strike: int = 0
        self.spot_price: float = 0.0
        
        # Tick tracking
        self.last_valid_tick_time: Optional[datetime] = None
        
        # Simulation state (for paper trading)
        self._simulated_premium: Optional[float] = None
        self._premium_trend: int = 1
        self._trend_ticks: int = 0
        self._simulated_spot: float = 25200.0  # Starting spot price
    
    def connect(self) -> bool:
        """Initialize and connect to Angel One broker"""
        # Initialize logger
        self.logger = BotLogger(
            log_dir=LOG_DIRECTORY,
            enable_console=LOG_CONSOLE
        )
        
        self.logger.info("=" * 50)
        self.logger.info("PTQ Scalping Bot v2.0 - Angel One")
        self.logger.info("=" * 50)
        self.logger.info(f"Mode: {'PAPER TRADING' if PAPER_TRADING else 'LIVE TRADING'}")
        
        # Set initial values (will be updated after login with real spot)
        self.current_strike = 25200
        self.spot_price = 25200.0
        self._simulated_spot = 25200.0
        self._current_expiry = None  # Will be set after broker connects
        self.current_symbol = None   # Will be set after expiry is found
        
        # Always try to connect to Angel One for real NIFTY spot data
        try:
            # First try to get credentials from .env (via constants)
            from config.constants import (
                ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_API_KEY, ANGEL_TOTP_SECRET
            )
            
            angel_creds = {
                'api_key': ANGEL_API_KEY,
                'client_id': ANGEL_CLIENT_ID,
                'password': ANGEL_PASSWORD,
                'totp_token': ANGEL_TOTP_SECRET
            }
            
            # Check if .env credentials are set (not empty placeholders)
            if not ANGEL_API_KEY or ANGEL_API_KEY == "your_api_key_here":
                # Fallback to credentials.json
                self.logger.debug("📂 Falling back to credentials.json")
                with open('config/credentials.json', 'r') as f:
                    creds = json.load(f)
                    angel_creds = {
                        'api_key': creds['angel_one']['api_key'],
                        'client_id': creds['angel_one']['client_id'],
                        'password': creds['angel_one']['password'],
                        'totp_token': creds['angel_one']['totp_token']
                    }
            else:
                self.logger.debug("✓ Using credentials from .env")
            
            self.broker_client = AngelOneClient(
                api_key=angel_creds['api_key'],
                client_id=angel_creds['client_id'],
                password=angel_creds['password'],
                totp_secret=angel_creds['totp_token']
            )
            
            if self.broker_client.login():
                # Get real NIFTY spot price
                real_spot = self.broker_client.get_ltp("NSE", "NIFTY", "99926000")
                if real_spot and real_spot > 10000:
                    self.spot_price = real_spot
                    self._simulated_spot = real_spot
                    self.current_strike = round(real_spot / 50) * 50
                    self.logger.info(f"✅ Angel One connected - Real NIFTY: ₹{real_spot:,.2f}")
                    self.logger.info(f"✓ Using Strike: {self.current_strike}")
                
                # Find nearest expiry and build symbol (after broker is connected)
                self._current_expiry = self._find_nearest_expiry()
                self.current_symbol = self._build_option_symbol(self.current_strike, OPTION_TYPE)
                self.logger.info(f"✓ Expiry: {self._current_expiry} | Symbol: {self.current_symbol}")
                
                if PAPER_TRADING:
                    if USE_LIVE_DATA:
                        self.logger.info("📊 Paper trading mode - Using REAL NIFTY + REAL Options data")
                    else:
                        self.logger.info("📊 Paper trading mode - Using real NIFTY + simulated options")
                    return True
                else:
                    # Live trading
                    try:
                        profile = self.broker_client.get_profile()
                        if profile:
                            name = profile.get('name', 'Trader')
                            self.logger.info(f"✓ Connected as: {name}")
                    except Exception as e:
                        self.logger.debug(f"Profile fetch skipped: {e}")
                    self.logger.info(f"✓ Live trading mode enabled")
                    return True
            else:
                self.logger.warning("⚠ Angel One login failed")
                
        except FileNotFoundError:
            self.logger.warning("⚠ credentials.json not found and .env not configured")
        except ImportError:
            self.logger.warning("⚠ Could not import credentials from constants")
        except Exception as e:
            self.logger.warning(f"⚠ Angel One connection error: {e}")
        
        # Fallback to simulated data if Angel One fails
        if PAPER_TRADING:
            self.logger.info("✓ Paper trading mode - Pure simulation")
            self.logger.info(f"✓ Starting Spot: ₹{self.spot_price:,.2f}")
            self.logger.info(f"✓ Using Strike: {self.current_strike}")
            return True
        
        self.logger.error("✗ Broker connection failed")
        return False
    
    def _find_nearest_expiry(self) -> str:
        """
        Find the nearest available NIFTY expiry date by searching Angel One.
        Returns expiry string in DDMMMYY format (e.g., "03FEB26").
        Handles holiday-shifted expiries (not always Thursday).
        """
        if not self.broker_client:
            # Fallback: assume next Thursday
            today = datetime.now()
            days_ahead = 3 - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            expiry_date = today + timedelta(days=days_ahead)
            return expiry_date.strftime("%d%b%y").upper()
        
        # Suppress SmartAPI verbose stdout during expiry search
        import sys
        import io
        
        # Search for contracts day by day for the next 14 days
        today = datetime.now()
        import time as t
        
        for days_ahead in range(1, 15):  # Check next 14 days
            check_date = today + timedelta(days=days_ahead)
            expiry_str = check_date.strftime("%d%b%y").upper()
            
            # Search for contracts with this expiry (with suppressed output)
            try:
                search_term = f"NIFTY{expiry_str}"
                
                # Capture any SDK print output
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                try:
                    results = self.broker_client.search_symbol(search_term, "NFO")
                finally:
                    sys.stdout = old_stdout
                
                if results and len(results) > 10:  # Need significant contracts
                    if self.logger:
                        self.logger.info(f"✓ Found expiry: {expiry_str} ({len(results)} contracts)")
                    return expiry_str
                t.sleep(0.3)  # Rate limit
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Expiry search error: {e}")
                t.sleep(1)
        
        # Fallback to next Thursday
        days_ahead = 3 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        expiry_date = today + timedelta(days=days_ahead)
        return expiry_date.strftime("%d%b%y").upper()
    
    def _build_option_symbol(self, strike: int, option_type: str = "CE") -> str:
        """
        Build NIFTY option symbol in Angel One format.
        Format: NIFTY{DDMMMYY}{STRIKE}{CE/PE}
        Example: NIFTY03FEB2625400CE
        """
        # Use cached expiry or find nearest
        if not hasattr(self, '_current_expiry') or self._current_expiry is None:
            self._current_expiry = self._find_nearest_expiry()
        
        return f"NIFTY{self._current_expiry}{strike}{option_type}"
    
    def _update_option_symbol(self):
        """Update option symbol and token based on current strike"""
        if not self.broker_client:
            return
        
        try:
            # Build correct symbol format: NIFTY03FEB2625400CE
            symbol = self._build_option_symbol(self.current_strike, OPTION_TYPE)
            
            # Search for symbol to get token
            symbols = self.broker_client.search_symbol(symbol, "NFO")
            if symbols:
                for sym in symbols:
                    name = sym.get('tradingsymbol', '') or sym.get('symbol', '')
                    token = sym.get('symboltoken', '') or sym.get('token', '')
                    if name == symbol or (str(self.current_strike) in name and option_type in name):
                        self._option_symbol = name
                        self._option_token = token
                        if self.logger:
                            self.logger.info(f"📊 Option: {name} (Token: {token})")
                        return
            
            # Fallback: just use the built symbol
            self._option_symbol = symbol
            if self.logger:
                self.logger.info(f"📊 Option symbol: {symbol}")
        except Exception as e:
            if self.logger:
                self.logger.warning(f"⚠ Option symbol search failed: {e}")
    
    def get_tick(self) -> Optional[Dict[str, Any]]:
        """
        Get current market tick data
        Returns: {'timestamp': int, 'bid': float, 'ask': float, 'ltp': float, 'volume': int, 'spot_price': float}
        """
        if PAPER_TRADING and not USE_LIVE_DATA:
            # === PAPER TRADING: Real NIFTY spot + Simulated option price ===
            
            # Initialize simulation state if not set
            if self._simulated_premium is None:
                self._simulated_premium = 125.0
            if not hasattr(self, '_wave_position'):
                self._wave_position = 0.0
                self._wave_speed = random.uniform(0.005, 0.02)
                self._wave_amplitude = random.uniform(15, 40)
                self._base_price = self._simulated_spot
            
            # Try to get real NIFTY spot from Angel One (every 5 MINUTES to avoid rate limits)
            if self.broker_client and (not hasattr(self, '_last_spot_fetch') or 
                                       time.time() - self._last_spot_fetch > 300):
                try:
                    real_spot = self.broker_client.get_ltp("NSE", "NIFTY", "99926000")
                    if real_spot and real_spot > 10000:
                        self._simulated_spot = real_spot
                        self._base_price = real_spot
                        self._last_spot_fetch = time.time()
                except Exception:
                    pass  # Use cached spot on API error
            
            # === REALISTIC SPOT MOVEMENT (Sinusoidal + Trend + Noise) ===
            import math
            self._wave_position += self._wave_speed
            
            # Base wave movement (creates EMA crossovers)
            wave = math.sin(self._wave_position) * self._wave_amplitude
            
            # Trend component (slow drift)
            trend = math.sin(self._wave_position * 0.1) * 30
            
            # Random walk component
            if not hasattr(self, '_random_walk'):
                self._random_walk = 0
            self._random_walk += random.gauss(0, 2)
            self._random_walk = max(-50, min(50, self._random_walk))  # Limit drift
            
            # Combine all components
            self.spot_price = round(self._base_price + wave + trend + self._random_walk + random.gauss(0, 1), 2)
            
            # Update strike if spot moved significantly
            new_strike = round(self.spot_price / 50) * 50
            if new_strike != self.current_strike:
                self.current_strike = new_strike
            
            # === REALISTIC OPTION PREMIUM (correlated with spot) ===
            # Premium follows spot direction with delta-like behavior
            spot_change = self.spot_price - (self._base_price + wave + trend)  # Relative movement
            delta_effect = spot_change * 0.5  # Simplified delta
            
            # Trend component in premium
            self._trend_ticks += 1
            if random.random() < 0.02:  # 2% chance of trend reversal
                self._premium_trend *= -1
            
            trend_move = self._premium_trend * random.uniform(0.1, 0.3)
            noise = random.gauss(0, 0.5)
            
            # Calculate new premium with REALISTIC timing constraint
            # Price can only move max 2 points per tick (prevents instant SL hits)
            target_premium = 125 + delta_effect + self._premium_trend * 10 + noise
            target_premium = max(40, min(300, target_premium))
            
            # Limit price change per tick to max 2 points (realistic market behavior)
            max_change_per_tick = 2.0
            if abs(target_premium - self._simulated_premium) > max_change_per_tick:
                if target_premium > self._simulated_premium:
                    self._simulated_premium += max_change_per_tick
                else:
                    self._simulated_premium -= max_change_per_tick
            else:
                self._simulated_premium = target_premium
            
            self._simulated_premium = max(40, min(300, self._simulated_premium))
            
            ltp = round(self._simulated_premium, 2)
            spread = 0.50
            
            # Volume variation (higher at extremes)
            base_volume = 400000
            volume_spike = abs(wave) / self._wave_amplitude * 200000
            volume = int(base_volume + volume_spike + random.uniform(-50000, 50000))
            
            self.last_valid_tick_time = datetime.now()
            
            return {
                'timestamp': current_time_ms(),
                'bid': round(ltp - spread/2, 2),
                'ask': round(ltp + spread/2, 2),
                'ltp': ltp,
                'volume': volume,
                'spot_price': self.spot_price
            }
        
        # === REAL DATA MODE: Get from Angel One broker (Paper Trading or Live) ===
        if self.broker_client:
            # Get real NIFTY spot (every 3 MINUTES to avoid rate limits - was 60s)
            spot_fetch_interval = 180  # 3 minutes
            if not hasattr(self, '_last_spot_fetch') or time.time() - self._last_spot_fetch > spot_fetch_interval:
                try:
                    real_spot = self.broker_client.get_ltp("NSE", "NIFTY", "99926000")
                    if real_spot and real_spot > 10000:
                        self.spot_price = real_spot
                        self._last_spot_fetch = time.time()
                        
                        # Update strike if spot moved significantly (100+ points)
                        new_strike = round(self.spot_price / 50) * 50
                        if abs(new_strike - self.current_strike) >= 100:
                            self.current_strike = new_strike
                            # Rebuild symbol with new strike
                            self.current_symbol = self._build_option_symbol(self.current_strike, OPTION_TYPE)
                            if self.logger:
                                self.logger.info(f"📊 Strike updated: {self.current_strike} | Symbol: {self.current_symbol}")
                except Exception as e:
                    # Only log every 5 minutes to avoid spam
                    if not hasattr(self, '_last_spot_error') or time.time() - self._last_spot_error > 300:
                        if self.logger:
                            self.logger.warning(f"⚠ NIFTY spot fetch failed: {e}")
                        self._last_spot_error = time.time()
            
            # Get real OPTION data (every 3 MINUTES to avoid rate limits - was 60s)
            option_fetch_interval = 180  # 3 minutes
            if not hasattr(self, '_last_option_fetch') or time.time() - self._last_option_fetch > option_fetch_interval:
                if self.current_symbol:
                    try:
                        tick = self.broker_client.get_market_tick(
                            symbol=self.current_symbol,
                            exchange=EXCHANGE
                        )
                        if tick:
                            self.last_valid_tick_time = datetime.now()
                            # Ensure spot_price is included
                            tick['spot_price'] = self.spot_price
                            self._last_option_fetch = time.time()
                            self._cached_option_tick = tick  # Cache the successful tick
                            return tick
                    except Exception as e:
                        # Only log every 5 minutes to avoid spam
                        if not hasattr(self, '_last_option_error') or time.time() - self._last_option_error > 300:
                            if self.logger:
                                self.logger.warning(f"⚠ Option tick fetch failed: {e}")
                            self._last_option_error = time.time()
                        # Fallback to simulated data if option fetch fails
                        pass
            
            # Return cached option tick if available (with simulated premium movement)
            if hasattr(self, '_cached_option_tick') and self._cached_option_tick:
                cached_tick = self._cached_option_tick.copy()
                cached_tick['spot_price'] = self.spot_price
                # Add small variation to make it more realistic
                base_ltp = cached_tick.get('ltp', 125.0)
                noise = random.gauss(0, 0.3)  # Small noise
                cached_tick['ltp'] = round(base_ltp + noise, 2)
                cached_tick['bid'] = round(cached_tick['ltp'] - 0.25, 2)
                cached_tick['ask'] = round(cached_tick['ltp'] + 0.25, 2)
                cached_tick['timestamp'] = current_time_ms()
                self.last_valid_tick_time = datetime.now()
                return cached_tick
        
        # Fallback: Return basic simulated tick if everything fails
        if self.logger:
            self.logger.warning("⚠ Using fallback simulated tick data")
        
        ltp = 125.0 if not hasattr(self, '_simulated_premium') or self._simulated_premium is None else self._simulated_premium
        return {
            'timestamp': current_time_ms(),
            'bid': round(ltp - 0.25, 2),
            'ask': round(ltp + 0.25, 2),
            'ltp': ltp,
            'volume': 300000,
            'spot_price': self.spot_price
        }
    
    def place_order(self, side: str, qty: int, trades_this_hour: int, 
                     direction: str = "CE", signal_params: Dict = None) -> Optional[Dict]:
        """
        Place order through Angel One
        Args: 
            side ('BUY' or 'SELL'), 
            qty (quantity)
            direction: 'CE' or 'PE' from SMART SCALP
            signal_params: dict with sl_points, tp_points, confidence, etc
        Returns: Trade object or None
        """
        if signal_params is None:
            signal_params = {}
        
        # === AUTO STRIKE SELECTION - Use current simulated/broker spot ===
        # Strike is already updated in get_tick()
            
        self.logger.info(f"📋 Placing {side} order for {qty} {direction} contracts")
        
        # Build correct option symbol: NIFTY{DDMMMYY}{STRIKE}{CE/PE}
        option_symbol = self._build_option_symbol(self.current_strike, direction)
        
        self.logger.info(f"   Strike: {self.current_strike} | Symbol: {option_symbol}")
        
        if PAPER_TRADING:
            tick = self.get_tick()
            entry_price = tick['ask'] if side == 'BUY' else tick['bid']
            
            # Use dynamic SL/TP from signal params if available
            sl_points = signal_params.get('sl_points', 9)
            tp_points = signal_params.get('tp_points', 18)
            confidence = signal_params.get('confidence', 60)
            
            # Calculate SL price based on points
            sl_price_diff = sl_points
            
            trade = {
                'order_id': f"PAPER_{int(time.time())}_{trades_this_hour}",
                'entry_price': entry_price,
                'entry_time': datetime.now(),
                'qty': qty,
                'side': side,
                'direction': direction,
                'symbol': option_symbol,
                'strike': self.current_strike,
                'spot_at_entry': self.spot_price,
                'highest_price': entry_price,
                'fixed_sl_price': entry_price - sl_price_diff if side == 'BUY' else entry_price + sl_price_diff,
                'trailing_sl_price': entry_price - sl_price_diff if side == 'BUY' else entry_price + sl_price_diff,
                'sl_points': sl_points,
                'tp_points': tp_points,
                'tp_price': entry_price + tp_points if side == 'BUY' else entry_price - tp_points,
                'confidence': confidence,
                'initial_sl_amount': sl_points * qty,
                'tp1_hit': False,
                'tp2_hit': False,
                'signal_params': signal_params
            }
            
            self.logger.info(f"✓ Paper order: {trade['order_id']} @ ₹{entry_price:.2f}")
            self.logger.info(f"   {direction} {self.current_strike} | SL: -{sl_points}pts | TP: +{tp_points}pts | Conf: {confidence}%")
            return trade
        
        # Live trading
        try:
            symbol_token = self.broker_client.get_symbol_token(self.current_symbol, EXCHANGE)
            
            # qty is already in contracts (260 for CE, 156 for PE)
            # No need to multiply by lot_size
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": self.current_symbol,
                "symboltoken": symbol_token,
                "transactiontype": side,
                "exchange": EXCHANGE,
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(qty)  # qty is already contracts
            }
            
            response = self.broker_client.smart_api.placeOrder(order_params)
            
            if response and response.get('status'):
                order_id = response['data']['orderid']
                
                time.sleep(0.5)
                tick = self.get_tick()
                entry_price = tick['ltp']
                
                trade = {
                    'order_id': order_id,
                    'entry_price': entry_price,
                    'entry_time': datetime.now(),
                    'qty': qty,
                    'side': side,
                    'symbol': self.current_symbol,
                    'highest_price': entry_price,
                    'trailing_sl_price': entry_price * (1 - STOP_LOSS_PCT / 100)
                }
                
                self.logger.info(f"✓ Live order placed: {order_id} @ {entry_price}")
                return trade
            else:
                self.logger.error(f"Order placement failed: {response}")
                return None
                
        except Exception as e:
            self.logger.error("Order placement error", e)
            return None
    
    def exit_position(self, trade: Dict, exit_reason: str, daily_pnl_inr: float, 
                      total_capital: float) -> Dict[str, Any]:
        """
        Exit current position
        Returns: {'pnl_inr': float, 'pnl_pct': float, 'hold_time': float}
        """
        if trade is None:
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0}
        
        self.logger.info(f"🚪 Exiting position: {trade['order_id']} | Reason: {exit_reason}")
        
        tick = self.get_tick()
        if not tick:
            self.logger.error("Cannot exit: No tick data")
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0}
        
        exit_price = tick['bid'] if trade['side'] == 'BUY' else tick['ask']
        entry_price = trade['entry_price']
        qty = trade['qty']
        # NOTE: qty is already number of contracts, NOT number of lots
        # So we don't multiply by lot_size
        
        # Calculate PnL
        # pnl = (exit - entry) * qty_contracts
        if trade['side'] == 'BUY':
            price_diff = exit_price - entry_price
        else:
            price_diff = entry_price - exit_price
        
        pnl_inr = price_diff * qty  # qty is contracts, not lots
        pnl_pct = (pnl_inr / total_capital) * 100
        hold_time = (datetime.now() - trade['entry_time']).total_seconds()
        
        new_daily_pnl = daily_pnl_inr + pnl_inr
        new_daily_pnl_pct = (new_daily_pnl / total_capital) * 100
        
        # Log trade exit
        self.logger.trade_exit({
            'order_id': trade['order_id'],
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time_sec': hold_time
        })
        
        self.logger.info(f"💰 Trade PnL: ₹{pnl_inr:+.2f} ({pnl_pct:+.2f}%) | Daily: ₹{new_daily_pnl:+.2f} ({new_daily_pnl_pct:+.2f}%)")
        
        # Execute actual exit if live trading
        if not PAPER_TRADING and self.broker_client:
            try:
                exit_side = "SELL" if trade['side'] == "BUY" else "BUY"
                symbol_token = self.broker_client.get_symbol_token(trade['symbol'], EXCHANGE)
                
                # trade['qty'] is already in contracts
                order_params = {
                    "variety": "NORMAL",
                    "tradingsymbol": trade['symbol'],
                    "symboltoken": symbol_token,
                    "transactiontype": exit_side,
                    "exchange": EXCHANGE,
                    "ordertype": "MARKET",
                    "producttype": "INTRADAY",
                    "duration": "DAY",
                    "price": "0",
                    "squareoff": "0",
                    "stoploss": "0",
                    "quantity": str(trade['qty'])  # qty is already contracts
                }
                
                self.broker_client.smart_api.placeOrder(order_params)
                
            except Exception as e:
                self.logger.error("Exit order placement error", e)
        
        return {
            'pnl_inr': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time': hold_time
        }
    
    def logout(self):
        """Logout from broker"""
        if self.broker_client and not PAPER_TRADING:
            self.broker_client.logout()


# Singleton instance
broker = BrokerInterface()
