"""Binary WebSocket tick parsing + best-5 depth extraction.

Mixed into AngelOneClient — uses self._best5_warned (one-shot warning latch) and
self.logger. Kept as instance methods (not free functions) so the existing direct-call
tests (tests/test_snapquote_depth.py: `client._parse_best5(...)`, `client._parse_ws_binary(...)`)
keep working unchanged.
"""

import struct
from typing import Dict, Optional

WS_MODE_QUOTE = 2
WS_MODE_SNAP_QUOTE = 3


class MessageParserMixin:

    def _parse_best5(self, block: bytes, ltp: float) -> Optional[Dict]:
        """Best-5 depth from the 200-byte block at offset 147 of a SnapQuote packet.

        Ten 20-byte records: flag (uint16), quantity (int64), price (int64, paise),
        order count (uint16). The flag separates the two sides.

        Which flag means "buy" is deliberately NOT trusted. The vendored SmartApi SDK
        assigns `best_5_buy_data` from the flag!=0 list and `best_5_sell_data` from the
        flag==0 list -- i.e. it swaps them -- and Angel One's documentation does not settle
        which is right. Guessing costs more than it saves: an inverted book would make every
        recorded fill look better or worse than it was, silently, and unlike the current
        fabricated spread it would look like real data. So both assignments are tried and the
        one that actually forms a book (bid <= ask, straddling ltp most closely) wins. If
        neither does, None is returned and the caller keeps its existing estimate.
        """
        if len(block) < 200:
            return None
        side_a, side_b = [], []
        try:
            for i in range(0, 200, 20):
                rec = block[i:i + 20]
                flag = struct.unpack('<H', rec[0:2])[0]
                qty = struct.unpack('<q', rec[2:10])[0]
                price = struct.unpack('<q', rec[10:18])[0] / 100.0
                if price <= 0 or qty <= 0:
                    continue          # an unfilled level, not a quote
                (side_a if flag == 0 else side_b).append((price, qty))
        except struct.error:
            return None
        if not side_a or not side_b:
            return None

        best = None
        for bids, asks in ((side_a, side_b), (side_b, side_a)):
            bid, bid_qty = max(bids, key=lambda x: x[0])
            ask, ask_qty = min(asks, key=lambda x: x[0])
            if bid > ask:
                continue                       # crossed: wrong way round
            dist = abs((bid + ask) / 2.0 - ltp)
            if best is None or dist < best[0]:
                best = (dist, bid, ask, bid_qty, ask_qty)
        if best is None:
            return None

        _, bid, ask, bid_qty, ask_qty = best
        # What actually has to be caught here is a book read the wrong way round, and the
        # assignment search above already does that: for two disjoint price groups only one
        # ordering can give bid <= ask, so a swapped book cannot survive it.
        #
        # This second check is only against a misread packet — wrong offsets would give
        # absurd numbers, not slightly-off ones. It first required bid <= ltp <= ask, which
        # is not true of a real book: the last trade routinely sits a tick outside the
        # current quote because the book moved after it. Live at 13:28:53 that threw away a
        # perfectly good 185.50/185.95 quote for an ltp of 185.40. Generous bounds instead,
        # sized to catch garbage rather than to police normal drift.
        if ltp > 0:
            spread = ask - bid
            mid = (bid + ask) / 2.0
            if spread > 0.10 * ltp or abs(mid - ltp) > 0.05 * ltp:
                if not self._best5_warned:
                    self._best5_warned = True
                    self.logger.warning(
                        f"⚠ best-5 depth rejected as implausible: bid {bid} / ask {ask} "
                        f"against ltp {ltp} — keeping the estimated spread"
                    )
                return None
        return {
            'best_bid_price': bid,
            'best_ask_price': ask,
            'best_bid_qty': bid_qty,
            'best_ask_qty': ask_qty,
            'depth_source': 'ws_best5',
        }

    def _parse_ws_binary(self, data: bytes) -> Optional[Dict]:
        """
        Parse WebSocket binary tick data

        Binary format (Little Endian):
        - Byte 0: Subscription Mode (1=LTP, 2=Quote, 3=SnapQuote)
        - Byte 1: Exchange Type
        - Bytes 2-26: Token (25 bytes, null-terminated string)
        - Bytes 27-34: Sequence Number (int64)
        - Bytes 35-42: Exchange Timestamp (int64, epoch ms)
        - Bytes 43-50: LTP (int64, divide by 100)
        - ... more fields for Quote/SnapQuote modes
        """
        if len(data) < 51:
            return None

        try:
            mode = data[0]
            exchange_type = data[1]

            # Token is 25 bytes, null-terminated
            token_bytes = data[2:27]
            token = token_bytes.decode('utf-8').rstrip('\x00')

            # Parse numeric fields (Little Endian)
            sequence = struct.unpack('<q', data[27:35])[0]
            timestamp = struct.unpack('<q', data[35:43])[0]
            ltp_raw = struct.unpack('<q', data[43:51])[0]

            # Convert LTP (divide by 100 for most, 10000000 for currencies)
            ltp = ltp_raw / 100.0

            tick = {
                'mode': mode,
                'exchange_type': exchange_type,
                'token': token,
                'sequence': sequence,
                'timestamp': timestamp,
                'ltp': ltp
            }

            # Parse additional fields for Quote mode
            if mode >= WS_MODE_QUOTE and len(data) >= 123:
                tick['last_trade_qty'] = struct.unpack('<q', data[51:59])[0]
                tick['avg_price'] = struct.unpack('<q', data[59:67])[0] / 100.0
                tick['volume'] = struct.unpack('<q', data[67:75])[0]
                tick['total_buy_qty'] = struct.unpack('<d', data[75:83])[0]
                tick['total_sell_qty'] = struct.unpack('<d', data[83:91])[0]
                tick['open'] = struct.unpack('<q', data[91:99])[0] / 100.0
                tick['high'] = struct.unpack('<q', data[99:107])[0] / 100.0
                tick['low'] = struct.unpack('<q', data[107:115])[0] / 100.0
                tick['close'] = struct.unpack('<q', data[115:123])[0] / 100.0

            # Parse additional fields for SnapQuote mode
            if mode >= WS_MODE_SNAP_QUOTE and len(data) >= 379:
                tick['last_trade_time'] = struct.unpack('<q', data[123:131])[0]
                tick['open_interest'] = struct.unpack('<q', data[131:139])[0]
                tick['oi_change_pct'] = struct.unpack('<q', data[139:147])[0] / 100.0
                # Bytes 147:347 are the best-5 book. This parser used to jump
                # straight from 139 to 347, so the depth was discarded and
                # broker.py's `tick_data.get('best_bid_price')` never found
                # anything — which is why every persisted bid/ask in the project
                # is the ltp +/- 0.3% estimate rather than a quote.
                book = self._parse_best5(data[147:347], ltp)
                if book:
                    tick.update(book)
                tick['upper_circuit'] = struct.unpack('<q', data[347:355])[0] / 100.0
                tick['lower_circuit'] = struct.unpack('<q', data[355:363])[0] / 100.0
                tick['week_52_high'] = struct.unpack('<q', data[363:371])[0] / 100.0
                tick['week_52_low'] = struct.unpack('<q', data[371:379])[0] / 100.0

            return tick

        except Exception as e:
            self.logger.error(f"Binary parse error: {e}")
            return None
