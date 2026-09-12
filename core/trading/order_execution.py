"""Order placement (paper + live, with limit-order price chasing and status
verification) and position exit (paper + live, with exit retry and slippage checks) —
the actual trading decisions, not broker plumbing.

Mixed into BrokerInterface — uses self.broker_client, self.current_symbol/
current_strike/_option_token/spot_price, self.get_tick()/_get_token()/
resolve_strike_for_direction()/_build_option_symbol() (broker.py/strike_selector.py),
self._subscribe_with_retry()/_unsubscribe_with_verify()/_ensure_symbol_sync_before_order()
(reconnect_manager.py), self._fetch_option_tick_rest() (tick_feed.py), self.logger,
self._position_cache*.
"""

import time
from datetime import datetime
from typing import Any, Dict, Optional

from utils.instruments import round_to_tick

from config.constants import (
    PAPER_TRADING, USE_LIVE_DATA, ENABLE_WEBSOCKET,
    EXCHANGE, WS_OPTION_SUB_MODE,
    SL_POINTS_FIXED, TP_POINTS_FIXED,
    MAX_LOSS_PER_TRADE_CE, MAX_LOSS_PER_TRADE_PE,
    USE_LIMIT_ORDERS, LIMIT_ORDER_OFFSET, MAX_SLIPPAGE_PCT,
    ORDER_RETRY_ENABLED, ORDER_MAX_RETRIES, ORDER_RETRY_DELAY_MS, ORDER_PRICE_CHASE_STEP,
)


class OrderExecutionMixin:

    def place_order(self, side: str, qty: int, trades_this_hour: int = 0,
                    direction: str = "CE", signal_params: Dict = None) -> Optional[Dict]:
        """
        Place order — Paper or Live with status verification.
        """
        if signal_params is None:
            signal_params = {}

        self.logger.info(f"📋 Placing {side} order: {qty} {direction} contracts")

        # The exchange refuses a single order above the contract's freeze quantity. Say so
        # here rather than letting the rejection come back from the broker unexplained;
        # splitting the order is a separate piece of work and is not attempted.
        from utils.instruments import freeze_quantity

        freeze = freeze_quantity()
        if freeze and qty > freeze:
            self.logger.warning(
                f"⚠ Order quantity {qty} exceeds the exchange freeze quantity {freeze}; "
                f"the exchange will refuse it. Reduce the size or split the order.")

        # Build option symbol for this direction. Same resolver get_tick_for_direction()
        # used to validate, so the contract that was checked is the contract that trades.
        order_strike = self.resolve_strike_for_direction(direction)
        option_symbol = self._build_option_symbol(order_strike, direction)
        self.logger.info(f"   Strike: {order_strike} | Symbol: {option_symbol}")

        # ═══════════════════════════════════════════════════════════════════
        # CRITICAL FIX: Update current_symbol BEFORE getting tick
        # This ensures tick data matches the actual symbol being traded
        # ═══════════════════════════════════════════════════════════════════
        old_symbol = self.current_symbol
        if option_symbol != self.current_symbol:
            old_token = self._option_token
            self.current_symbol = option_symbol
            self.current_strike = order_strike   # the subscribed strike IS the traded one
            self._option_token = self._get_token(option_symbol, EXCHANGE)
            self.logger.info(f"📍 Symbol switched: {old_symbol} → {option_symbol}")

            # Re-subscribe WebSocket to new symbol using MAKE-BEFORE-BREAK (Overlapping)
            if USE_LIVE_DATA and ENABLE_WEBSOCKET and self._ws_connected:
                if self.broker_client and self._option_token:
                    try:
                        # Clear old tick data to avoid stale price
                        with self._tick_lock:
                            self.last_tick = None
                            self._tick_buffer.clear()

                        # 1. Subscribe to new token FIRST to ensure data flow
                        if not self._subscribe_with_retry([(EXCHANGE, self._option_token, WS_OPTION_SUB_MODE)]):
                            self.logger.warning(f"⚠ WebSocket re-subscribe failed for {self._option_token}")
                            return None

                        self.logger.info(f"🔌 WebSocket re-subscribed to {option_symbol}")

                        # 2. Unsubscribe old token SECOND
                        if old_token and old_token != self._option_token:
                            if not self._unsubscribe_with_verify([(EXCHANGE, old_token, WS_OPTION_SUB_MODE)]):
                                self.logger.warning(f"⚠ Old token unsubscribe failed: {old_token}")

                    except Exception as e:
                        self.logger.warning(f"⚠ WebSocket re-subscribe failed: {e}")

        if not self._ensure_symbol_sync_before_order(option_symbol, self._option_token):
            self.logger.warning(f"⚠ Order blocked: symbol stream not synced for {option_symbol}")
            return None

        # Get SL/TP from signal params (which now come from .env via strategy)
        sl_points = signal_params.get('sl_points', SL_POINTS_FIXED)
        tp_points = signal_params.get('tp_points', TP_POINTS_FIXED)
        confidence = signal_params.get('confidence', 60)
        details = signal_params.get('details', {}) if isinstance(signal_params, dict) else {}
        mq_score = details.get('market_quality_score')
        mq_grade = details.get('market_quality_grade')
        mq_components = details.get('market_quality_components', {})
        mq_hard_reject = details.get('hard_reject_reason')

        # -- PAPER TRADING --
        if PAPER_TRADING:
            tick = self.get_tick()

            # CRITICAL: If tick is from wrong symbol or stale, fetch fresh via REST
            if tick and tick.get('symbol') != option_symbol:
                self.logger.warning(f"⚠ Tick symbol mismatch: {tick.get('symbol')} vs {option_symbol}")
                # Force REST fetch for correct symbol's price
                rest_tick = self._fetch_option_tick_rest()
                if rest_tick:
                    tick = rest_tick
                    self.logger.info(f"✅ REST tick for {option_symbol}: LTP ₹{tick.get('ltp', 0):.2f}")

            if not tick:
                self.logger.error("❌ No tick data for paper order")
                return None

            entry_price = tick['ask'] if side == 'BUY' else tick['bid']

            trade = {
                'order_id': f"PAPER_{int(time.time())}_{trades_this_hour}",
                'entry_price': entry_price,
                # The book at the moment of entry, recorded because the spread is
                # paid here and nowhere else: entry crosses to the ask, exit
                # crosses to the bid, and neither cost appears in any greek or in
                # research/costs.py. Without these two numbers there is no way to
                # tell an instrument whose delta earned its keep from one whose
                # spread ate the gain, which is the open question about trading
                # deep-ITM contracts at all.
                'entry_bid': tick.get('bid'),
                'entry_ask': tick.get('ask'),
                'entry_ltp': tick.get('ltp'),
                'entry_spread': (round(float(tick['ask']) - float(tick['bid']), 2)
                                 if tick.get('ask') and tick.get('bid') else None),
                'entry_time': datetime.now(),
                'qty': qty,
                'side': side,
                'direction': direction,
                'symbol': option_symbol,
                'strike': self.current_strike,
                'spot_at_entry': self.spot_price,
                'highest_price': entry_price,
                'fixed_sl_price': entry_price - sl_points if side == 'BUY' else entry_price + sl_points,
                'trailing_sl_price': entry_price - sl_points if side == 'BUY' else entry_price + sl_points,
                'sl_points': sl_points,
                'tp_points': tp_points,
                'tp_price': entry_price + tp_points if side == 'BUY' else entry_price - tp_points,
                'confidence': confidence,
                'score': signal_params.get('score') if isinstance(signal_params, dict) else None,
                'market_quality_score': mq_score,
                'market_quality_grade': mq_grade,
                'market_quality_components': mq_components,
                'hard_reject_reason': mq_hard_reject,
                'initial_sl_amount': sl_points * qty,
                'tp1_hit': False,
                'tp2_hit': False,
                'signal_params': signal_params,
                'status': 'COMPLETE',
            }

            self.logger.info(f"✅ [PAPER] Order filled: {trade['order_id']} @ ₹{entry_price:.2f}")
            self.logger.info(f"   {direction} {self.current_strike} | SL: -{sl_points}pts | TP: +{tp_points}pts | Conf: {confidence}%")
            return trade

        # -- LIVE TRADING — with smart order execution --
        try:
            symbol_token = self._get_token(option_symbol, EXCHANGE)
            if not symbol_token:
                self.logger.error(f"❌ Token not found for {option_symbol}")
                return None

            # Get current tick for price calculation
            tick = self.get_tick()
            if not tick:
                self.logger.error("❌ No tick data for order pricing")
                return None

            # ═══════════════════════════════════════════════════════════════════
            # v3.1: SMART LIMIT ORDER EXECUTION WITH RETRY
            # ═══════════════════════════════════════════════════════════════════
            if USE_LIMIT_ORDERS:
                # Calculate initial limit price
                bid = tick.get('bid', tick['ltp'] - 0.5)
                ask = tick.get('ask', tick['ltp'] + 0.5)

                if side == 'BUY':
                    # For BUY: start at ask - offset, chase up on retries
                    limit_price = ask - LIMIT_ORDER_OFFSET
                else:
                    # For SELL: start at bid + offset, chase down on retries
                    limit_price = bid + LIMIT_ORDER_OFFSET

                # Snap onto the exchange's tick grid. round(x, 2) put prices between
                # ticks - NIFTY options move in 0.05 - and the exchange refuses those.
                # BUY rounds down and SELL rounds up, so rounding never worsens the price.
                limit_price = round_to_tick(limit_price, side)

                # Retry loop with price chasing
                order_resp = None
                for attempt in range(ORDER_MAX_RETRIES if ORDER_RETRY_ENABLED else 1):
                    self.logger.info(f"📦 LIMIT order attempt {attempt + 1}: {side} @ ₹{limit_price:.2f}")

                    try:
                        order_resp = self.broker_client.place_order(
                            symbol=option_symbol,
                            exchange=EXCHANGE,
                            transaction_type=side,
                            quantity=qty,
                            order_type="LIMIT",
                            price=limit_price,
                            symbol_token=symbol_token
                        )

                        if order_resp and order_resp.get('orderid'):
                            order_id = order_resp['orderid']

                            # Wait for fill (2 seconds)
                            time.sleep(2)
                            status = self.broker_client.get_order_status(order_id)

                            if status:
                                order_status = str(status.get('orderstatus', '')).lower()

                                if order_status == 'complete':
                                    # Order filled! Success!
                                    break
                                elif order_status == 'open' or order_status == 'pending':
                                    # Not filled yet - cancel and retry with better price
                                    self.logger.info(f"⏳ LIMIT order pending, cancelling for retry...")
                                    try:
                                        self.broker_client.cancel_order(order_id)
                                    except:
                                        pass

                                    # Chase price
                                    if side == 'BUY':
                                        limit_price += ORDER_PRICE_CHASE_STEP
                                    else:
                                        limit_price -= ORDER_PRICE_CHASE_STEP
                                    limit_price = round_to_tick(limit_price, side)

                                    time.sleep(ORDER_RETRY_DELAY_MS / 1000)
                                    continue
                                elif order_status == 'rejected':
                                    self.logger.warning(f"⚠ LIMIT order rejected: {status.get('text')}")
                                    break

                    except Exception as e:
                        self.logger.warning(f"⚠ LIMIT order attempt {attempt + 1} failed: {e}")

                # If LIMIT orders failed, fall back to MARKET
                if not order_resp or not order_resp.get('orderid'):
                    self.logger.warning("⚠ LIMIT orders failed, falling back to MARKET order")
                else:
                    # Check final status
                    order_id = order_resp['orderid']
                    status = self.broker_client.get_order_status(order_id)
                    if status and str(status.get('orderstatus', '')).lower() != 'complete':
                        self.logger.warning("⚠ LIMIT order not filled, falling back to MARKET")
                        try:
                            self.broker_client.cancel_order(order_id)
                        except:
                            pass
                        order_resp = None

            # MARKET order (original path or fallback)
            if not USE_LIMIT_ORDERS or not order_resp or not order_resp.get('orderid'):
                order_resp = self.broker_client.place_order(
                    symbol=option_symbol,
                    exchange=EXCHANGE,
                    transaction_type=side,
                    quantity=qty,
                    symbol_token=symbol_token
                )

            if not order_resp or not order_resp.get('orderid'):
                self.logger.error(f"❌ Order rejected: {order_resp}")
                return None

            order_id = order_resp['orderid']
            self.logger.info(f"🚀 [LIVE] Order sent: {order_id} — Verifying...")

            # -- ORDER STATUS VERIFICATION (wait up to 5s) --
            for attempt in range(5):
                time.sleep(1)
                try:
                    status = self.broker_client.get_order_status(order_id)
                    if not status:
                        continue

                    order_status = str(status.get('orderstatus', '')).lower()

                    if order_status == 'complete':
                        avg_price = float(status.get('averageprice', 0))
                        filled_qty = int(status.get('filledshares', qty))

                        # v3.4: Slippage validation — alert if fill deviates too much
                        expected_price = tick.get('ltp', avg_price) if tick else avg_price
                        if expected_price > 0:
                            slippage_pct = abs(avg_price - expected_price) / expected_price * 100
                            if slippage_pct > MAX_SLIPPAGE_PCT:
                                self.logger.warning(
                                    f"⚠️ HIGH SLIPPAGE: {slippage_pct:.2f}% | Expected ₹{expected_price:.2f} → Got ₹{avg_price:.2f}"
                                )
                                try:
                                    from core.services.telegram_bot import send_alert
                                    send_alert(
                                        f"⚠️ SLIPPAGE ALERT\n"
                                        f"Expected: ₹{expected_price:.2f}\n"
                                        f"Filled: ₹{avg_price:.2f}\n"
                                        f"Slip: {slippage_pct:.2f}% (limit {MAX_SLIPPAGE_PCT}%)"
                                    )
                                except Exception:
                                    pass

                        trade = {
                            'order_id': order_id,
                            'entry_price': avg_price,
                            'entry_time': datetime.now(),
                            'qty': filled_qty,
                            'side': side,
                            'direction': direction,
                            'symbol': option_symbol,
                            'strike': self.current_strike,
                            'spot_at_entry': self.spot_price,
                            'highest_price': avg_price,
                            'fixed_sl_price': avg_price - sl_points if side == 'BUY' else avg_price + sl_points,
                            'trailing_sl_price': avg_price - sl_points if side == 'BUY' else avg_price + sl_points,
                            'sl_points': sl_points,
                            'tp_points': tp_points,
                            'tp_price': avg_price + tp_points if side == 'BUY' else avg_price - tp_points,
                            'confidence': confidence,
                            'score': signal_params.get('score') if isinstance(signal_params, dict) else None,
                            'market_quality_score': mq_score,
                            'market_quality_grade': mq_grade,
                            'market_quality_components': mq_components,
                            'hard_reject_reason': mq_hard_reject,
                            'initial_sl_amount': sl_points * filled_qty,
                            'tp1_hit': False,
                            'tp2_hit': False,
                            'signal_params': signal_params,
                            'status': 'COMPLETE',
                        }
                        self.logger.info(f"✅ [LIVE] Order filled: {order_id} @ ₹{avg_price:.2f} | Qty: {filled_qty}")
                        self.clear_position_cache()
                        return trade

                    elif order_status == 'rejected':
                        reject_reason = status.get('text', 'Unknown')
                        self.logger.error(f"❌ Order REJECTED: {reject_reason}")
                        return None

                    elif order_status == 'cancelled':
                        self.logger.error(f"❌ Order CANCELLED: {order_id}")
                        return None

                except Exception as e:
                    self.logger.warning(f"⚠ Order status check error (attempt {attempt + 1}): {e}")

            self.logger.warning(f"⚠ Order status timeout: {order_id} — treating as failed")
            return None

        except Exception as e:
            self.logger.error(f"❌ Order placement error: {e}")
            return None

    # =========================================================================
    # EXIT POSITION
    # =========================================================================

    def exit_position(self, trade: Dict, exit_reason: str, daily_pnl_inr: float,
                      total_capital: float, current_tick: Dict = None) -> Dict[str, Any]:
        """Exit current position — Paper or Live with verification.

        Args:
            current_tick: If provided, use this tick for PnL calculation instead
                          of calling get_tick() again (prevents data source mismatch).
        """
        if trade is None:
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0}

        self.logger.info(f"🚪 Exiting position: {trade['order_id']} | Reason: {exit_reason}")

        # FIX: Use the same tick that triggered the exit, not a new one
        tick = current_tick if current_tick else self.get_tick()
        if not tick:
            self.logger.error("Cannot exit: No tick data")
            return {'pnl_inr': 0, 'pnl_pct': 0, 'hold_time': 0, 'exit_confirmed': False}

        exit_price = tick['bid'] if trade['side'] == 'BUY' else tick['ask']
        entry_price = trade['entry_price']
        qty = trade['qty']

        # Calculate PnL
        if trade['side'] == 'BUY':
            price_diff = exit_price - entry_price
        else:
            price_diff = entry_price - exit_price

        pnl_inr = price_diff * qty

        # Trust the real bid/ask tick-based PnL as the realized value for both
        # wins and losses — it correctly reflects spread cost either way.
        # Previously, any loss unconditionally used the exit engine's
        # LTP-based estimate instead, which meant losing exits never paid
        # spread cost while winning exits did (an inconsistent accounting,
        # not an intentional one). The engine's capped value is still applied,
        # but only as a hard floor so no loss ever exceeds the configured max.
        if 'current_pnl' in trade and trade['current_pnl'] != 0:
            engine_pnl = trade['current_pnl']
            # For profits, trust the engine when tick-based PnL is suspicious (e.g. zero).
            if engine_pnl > 0 and abs(pnl_inr) < 0.01:
                pnl_inr = engine_pnl
                self.logger.info(f"   Using exit engine PnL: ₹{pnl_inr:+.2f} (tick PnL was zero)")

        if pnl_inr < 0:
            direction = trade.get('direction', 'CE')
            max_loss = MAX_LOSS_PER_TRADE_CE if direction == 'CE' else MAX_LOSS_PER_TRADE_PE
            if pnl_inr < -max_loss:
                self.logger.info(f"   PnL floored: ₹{pnl_inr:+.2f} -> ₹{-max_loss:+.2f} (max loss cap)")
                pnl_inr = -max_loss

        pnl_pct = (pnl_inr / total_capital) * 100
        hold_time = (datetime.now() - trade['entry_time']).total_seconds()

        new_daily_pnl = daily_pnl_inr + pnl_inr
        new_daily_pnl_pct = (new_daily_pnl / total_capital) * 100

        exit_confirmed = True

        # Execute exit order if live trading
        if not PAPER_TRADING and self.broker_client:
            exit_confirmed = False
            try:
                exit_side = "SELL" if trade['side'] == "BUY" else "BUY"
                symbol = trade.get('symbol', self.current_symbol)
                symbol_token = self._get_token(symbol, EXCHANGE)

                if symbol_token:
                    # ═══════════════════════════════════════════════════════════
                    # EXIT ORDER WITH RETRY (v3.3 - Critical Safety Fix)
                    # Retry up to 3 times with MARKET order fallback
                    # ═══════════════════════════════════════════════════════════
                    exit_order_id = None
                    max_exit_retries = 3

                    for attempt in range(1, max_exit_retries + 1):
                        try:
                            # First attempt: normal order, retries: force MARKET
                            order_type = "MARKET" if attempt > 1 else None

                            order_kwargs = dict(
                                symbol=symbol,
                                exchange=EXCHANGE,
                                transaction_type=exit_side,
                                quantity=qty,
                                symbol_token=symbol_token
                            )
                            if order_type:
                                order_kwargs['order_type'] = order_type

                            order_resp = self.broker_client.place_order(**order_kwargs)

                            if order_resp and order_resp.get('orderid'):
                                exit_order_id = order_resp['orderid']
                                self.logger.info(f"✅ Exit order sent (attempt {attempt}): {exit_order_id}")
                                break
                            else:
                                self.logger.warning(f"⚠️ Exit order attempt {attempt}/{max_exit_retries} failed: {order_resp}")
                                if attempt < max_exit_retries:
                                    time.sleep(1)
                        except Exception as retry_err:
                            self.logger.error(f"❌ Exit order attempt {attempt}/{max_exit_retries} error: {retry_err}")
                            if attempt < max_exit_retries:
                                time.sleep(1)

                    if exit_order_id:
                        # Verify exit fill
                        for _ in range(5):
                            time.sleep(1)
                            try:
                                status = self.broker_client.get_order_status(exit_order_id)
                                if status and str(status.get('orderstatus', '')).lower() == 'complete':
                                    real_exit = float(status.get('averageprice', exit_price))
                                    # v3.4: Exit slippage check
                                    if exit_price > 0:
                                        exit_slip_pct = abs(real_exit - exit_price) / exit_price * 100
                                        if exit_slip_pct > MAX_SLIPPAGE_PCT:
                                            self.logger.warning(f"⚠️ EXIT SLIPPAGE: {exit_slip_pct:.2f}% | Target ₹{exit_price:.2f} → Got ₹{real_exit:.2f}")
                                    # Recalculate with real exit price
                                    if trade['side'] == 'BUY':
                                        pnl_inr = (real_exit - entry_price) * qty
                                    else:
                                        pnl_inr = (entry_price - real_exit) * qty
                                    exit_price = real_exit
                                    pnl_pct = (pnl_inr / total_capital) * 100
                                    new_daily_pnl = daily_pnl_inr + pnl_inr
                                    new_daily_pnl_pct = (new_daily_pnl / total_capital) * 100
                                    exit_confirmed = True
                                    self.logger.info(f"✅ Exit confirmed @ ₹{real_exit:.2f}")
                                    break
                            except Exception:
                                pass
                    else:
                        self.logger.error(f"🚨 CRITICAL: All {max_exit_retries} exit attempts FAILED! Position may remain OPEN!")
                        self.logger.error(f"🚨 Manual intervention needed: {exit_side} {qty} {symbol}")
                        # Send Telegram alert if available
                        try:
                            from core.services.telegram_bot import get_telegram
                            tg = get_telegram()
                            if tg:
                                tg.send_message(
                                    f"🚨 EMERGENCY: Exit order FAILED after {max_exit_retries} retries!\n"
                                    f"Action: {exit_side} {qty} {symbol}\n"
                                    f"Please close position MANUALLY!"
                                )
                        except Exception:
                            pass

                self.clear_position_cache()

            except Exception as e:
                self.logger.error(f"❌ Exit order error: {e}")

        if not exit_confirmed:
            self.logger.error("🚨 Exit not confirmed. Keeping trade open in bot state.")
            return {
                'pnl_inr': pnl_inr,
                'pnl_pct': pnl_pct,
                'hold_time': hold_time,
                'exit_confirmed': False,
                'exit_price': exit_price,
                'exit_reason': exit_reason
            }

        # Log trade exit only after paper exit or confirmed live exit.
        self.logger.trade_exit({
            'order_id': trade['order_id'],
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'pnl': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time_sec': hold_time,
            # See the entry side: the round trip crosses the book twice and
            # neither crossing is in any greek or in research/costs.py.
            'exit_bid': tick.get('bid'),
            'exit_ask': tick.get('ask'),
            'exit_spread': (round(float(tick['ask']) - float(tick['bid']), 2)
                            if tick.get('ask') and tick.get('bid') else None),
            'entry_spread': trade.get('entry_spread'),
            'spot_at_exit': self.spot_price,
        })
        self.logger.info(f"💰 PnL: ₹{pnl_inr:+.2f} ({pnl_pct:+.2f}%) | Daily: ₹{new_daily_pnl:+.2f} ({new_daily_pnl_pct:+.2f}%)")

        return {
            'pnl_inr': pnl_inr,
            'pnl_pct': pnl_pct,
            'hold_time': hold_time,
            'exit_confirmed': True,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'exit_bid': tick.get('bid'),
            'exit_ask': tick.get('ask'),
            'exit_ltp': tick.get('ltp'),
            'exit_spread': (round(float(tick['ask']) - float(tick['bid']), 2)
                            if tick.get('ask') and tick.get('bid') else None),
        }

    # =========================================================================
    # POSITION CACHE (Phase 4)
    # =========================================================================

    def get_position_cached(self, force_refresh: bool = False) -> Optional[Dict]:
        """Get position with 5-second cache"""
        if not self.broker_client:
            return None

        current_time = time.time()
        if (not force_refresh and
                self._position_cache is not None and
                current_time - self._position_cache_time < self._position_cache_ttl):
            return self._position_cache

        try:
            positions = self.broker_client.get_positions()
            if positions and len(positions) > 0:
                self._position_cache = positions[0]
                self._position_cache_time = current_time
                return self._position_cache
        except Exception as e:
            self.logger.warning(f"Position query error: {e}")

        return self._position_cache

    def clear_position_cache(self) -> None:
        """Clear position cache"""
        self._position_cache = None
        self._position_cache_time = 0
