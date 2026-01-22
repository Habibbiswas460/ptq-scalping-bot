"""
PTQ Scalping Bot - Broker Interface
All broker I/O operations (connect, tick, orders)
"""

import json
import time
from datetime import datetime
from typing import Optional, Dict, Any

from brokers.angel_one import AngelOneClient
from utils.logger import BotLogger
from live_data_fetcher import LiveDataFetcher

from config.constants import (
    CONFIG, PAPER_TRADING, USE_LIVE_DATA,
    STOP_LOSS_AMOUNT
)
from utils.helpers import current_time_ms


class BrokerInterface:
    """Broker interface for Angel One"""
    
    def __init__(self):
        self.broker_client: Optional[AngelOneClient] = None
        self.logger: Optional[BotLogger] = None
        self.live_data_fetcher: Optional[LiveDataFetcher] = None
        
        # Trading state
        self.current_symbol: Optional[str] = None
        self.current_strike: int = 0
        self.spot_price: float = 0.0
        
        # Tick tracking
        self.last_valid_tick_time: Optional[datetime] = None
        
        # Trend simulation (for paper trading)
        self._trend_counter = 0
        self._trend_direction = 1
    
    def connect(self) -> bool:
        """Initialize and connect to Angel One broker"""
        # Initialize logger
        self.logger = BotLogger(
            log_dir=CONFIG['logging']['log_directory'],
            enable_console=CONFIG['logging']['console_output']
        )
        
        self.logger.info("=" * 50)
        self.logger.info("PTQ Scalping Bot v2.0 - Angel One")
        self.logger.info("=" * 50)
        self.logger.info(f"Mode: {'PAPER TRADING' if PAPER_TRADING else 'LIVE TRADING'}")
        
        # Set current symbol
        self.current_symbol = f"{CONFIG['trading']['symbol']}2401724800{CONFIG['trading']['option_type']}"
        self.current_strike = 24800
        self.spot_price = 24800
        
        # Initialize NSE free data fetcher
        try:
            self.live_data_fetcher = LiveDataFetcher()
            self.logger.info("✓ NSE Live Data fetcher initialized")
            
            # Get real spot price
            real_spot = self.live_data_fetcher.get_nifty_spot()
            if real_spot:
                self.spot_price = real_spot
                self.current_strike = round(real_spot / 100) * 100
                self.logger.info(f"✓ Live NIFTY Spot: ₹{real_spot:,.2f}")
                self.logger.info(f"✓ Using Strike: {self.current_strike}")
        except Exception as e:
            self.logger.warning(f"⚠ NSE data fetcher failed: {e}")
            self.live_data_fetcher = None
        
        if PAPER_TRADING:
            self.logger.info("✓ Paper trading mode")
            self.logger.info("📊 Using Yahoo Finance for live NIFTY data")
            return True
        
        # Live trading - connect to Angel One
        try:
            with open('config/credentials.json', 'r') as f:
                creds = json.load(f)
                angel_creds = creds['angel_one']
        except FileNotFoundError:
            self.logger.error("⚠ credentials.json not found!")
            self.logger.info("Copy config/credentials.json.example to config/credentials.json")
            return False
        
        self.broker_client = AngelOneClient(
            api_key=angel_creds['api_key'],
            client_id=angel_creds['client_id'],
            password=angel_creds['password'],
            totp_token=angel_creds['totp_token']
        )
        
        if self.broker_client.login():
            profile = self.broker_client.get_profile()
            if profile and profile.get('status'):
                name = profile.get('data', {}).get('name', 'Trader')
                self.logger.info(f"✓ Connected as: {name}")
                self.logger.info(f"Symbol: {self.current_symbol}")
                return True
        
        self.logger.error("✗ Broker connection failed")
        return False
    
    def get_tick(self) -> Optional[Dict[str, Any]]:
        """
        Get current market tick data
        Returns: {'timestamp': int, 'bid': float, 'ask': float, 'ltp': float, 'volume': int}
        """
        import random
        
        if PAPER_TRADING:
            # Try NSE free data first
            if USE_LIVE_DATA and self.live_data_fetcher:
                try:
                    tick = self.live_data_fetcher.get_market_tick(
                        strike=self.current_strike,
                        option_type=CONFIG['trading']['option_type']
                    )
                    if tick:
                        self.last_valid_tick_time = datetime.now()
                        self.spot_price = tick['ltp']
                        return tick
                except Exception:
                    pass
            
            # Try Angel One broker data
            if USE_LIVE_DATA and self.broker_client:
                try:
                    tick = self.broker_client.get_market_tick(
                        symbol=self.current_symbol,
                        exchange=CONFIG['trading']['exchange']
                    )
                    if tick:
                        self.last_valid_tick_time = datetime.now()
                        return tick
                except Exception:
                    pass
            
            # Simulated tick data with trends
            self._trend_counter += 1
            
            if self._trend_counter % 100 == 0:
                self._trend_direction *= -1
            
            trend_strength = 0.0003 * self._trend_direction
            volatility = self.spot_price * 0.0005
            price_change = trend_strength * self.spot_price + random.gauss(0, volatility)
            
            self.spot_price = self.spot_price * 0.999 + (self.spot_price + price_change) * 0.001
            current_ltp = self.spot_price + price_change
            
            base_volume = 10000
            if random.random() < 0.15:
                volume = int(base_volume * random.uniform(1.1, 1.5))
            else:
                volume = int(base_volume * random.uniform(0.9, 1.05))
            
            return {
                'timestamp': current_time_ms(),
                'bid': round(current_ltp - 0.25, 2),
                'ask': round(current_ltp + 0.25, 2),
                'ltp': round(current_ltp, 2),
                'volume': volume
            }
        
        # Live trading: get from broker
        if self.broker_client and self.current_symbol:
            tick = self.broker_client.get_market_tick(
                symbol=self.current_symbol,
                exchange=CONFIG['trading']['exchange']
            )
            if tick:
                self.last_valid_tick_time = datetime.now()
            return tick
        
        return None
    
    def place_order(self, side: str, qty: int, trades_this_hour: int) -> Optional[Dict]:
        """
        Place order through Angel One
        Args: side ('BUY' or 'SELL'), qty (quantity)
        Returns: Trade object or None
        """
        self.logger.info(f"📋 Placing {side} order for {qty} contracts")
        
        if PAPER_TRADING:
            tick = self.get_tick()
            entry_price = tick['ask'] if side == 'BUY' else tick['bid']
            
            # Dynamic stop loss based on config
            if CONFIG['risk_management'].get('dynamic_sl_enabled', False):
                estimated_vix = 15.0  # Default VIX
                vix_factor = estimated_vix / 15.0
                sl_amount = STOP_LOSS_AMOUNT * max(0.8, min(1.5, vix_factor))
            else:
                sl_amount = STOP_LOSS_AMOUNT
            
            sl_price_diff = sl_amount / (qty * CONFIG['trading']['lot_size'])
            
            trade = {
                'order_id': f"PAPER_{int(time.time())}_{trades_this_hour}",
                'entry_price': entry_price,
                'entry_time': datetime.now(),
                'qty': qty,
                'side': side,
                'symbol': self.current_symbol,
                'highest_price': entry_price,
                'fixed_sl_price': entry_price - sl_price_diff if side == 'BUY' else entry_price + sl_price_diff,
                'trailing_sl_price': entry_price - sl_price_diff if side == 'BUY' else entry_price + sl_price_diff,
                'initial_sl_amount': sl_amount,
                'tp1_hit': False,
                'tp2_hit': False
            }
            
            self.logger.info(f"✓ Paper order: {trade['order_id']} @ ₹{entry_price:.2f} | SL: ₹{trade['fixed_sl_price']:.2f}")
            return trade
        
        # Live trading
        try:
            symbol_token = self.broker_client.get_symbol_token(self.current_symbol, CONFIG['trading']['exchange'])
            
            order_params = {
                "variety": "NORMAL",
                "tradingsymbol": self.current_symbol,
                "symboltoken": symbol_token,
                "transactiontype": side,
                "exchange": CONFIG['trading']['exchange'],
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(qty * CONFIG['trading']['lot_size'])
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
                    'trailing_sl_price': entry_price * (1 - CONFIG['risk_management']['stop_loss_pct'] / 100)
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
        lot_size = CONFIG['trading']['lot_size']
        
        # Calculate PnL
        if trade['side'] == 'BUY':
            pnl_per_lot = (exit_price - entry_price) * lot_size
        else:
            pnl_per_lot = (entry_price - exit_price) * lot_size
        
        pnl_inr = pnl_per_lot * qty
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
                symbol_token = self.broker_client.get_symbol_token(trade['symbol'], CONFIG['trading']['exchange'])
                
                order_params = {
                    "variety": "NORMAL",
                    "tradingsymbol": trade['symbol'],
                    "symboltoken": symbol_token,
                    "transactiontype": exit_side,
                    "exchange": CONFIG['trading']['exchange'],
                    "ordertype": "MARKET",
                    "producttype": "INTRADAY",
                    "duration": "DAY",
                    "price": "0",
                    "squareoff": "0",
                    "stoploss": "0",
                    "quantity": str(trade['qty'] * CONFIG['trading']['lot_size'])
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
