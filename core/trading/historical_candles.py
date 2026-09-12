"""Historical OHLC fetch (for indicator warm-up) with retry/backoff, an in-memory
cache, and an on-disk fallback that survives a restart.

Mixed into BrokerInterface — uses self.broker_client, self._historical_candles_cache,
self.logger.
"""

import json
import os
import random
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


class HistoricalCandlesMixin:

    def get_historical_candles(self, exchange: str, token: str, interval: str = "FIVE_MINUTE", days_back: int = 2, max_retries: int = 3) -> List[Dict[str, Any]]:
        """
        Fetch historical OHLC data to warm up indicators.
        Retries with backoff on transient/rate-limit failures, falling back to the
        last known-good fetch for this symbol if every retry is exhausted.
        Returns a list of standardized candle dicts.
        """
        if not self.broker_client:
            return []

        cache_key = f"{exchange}:{token}:{interval}"
        now = datetime.now()
        from_date = (now - timedelta(days=days_back)).strftime("%Y-%m-%d %H:%M")
        to_date = now.strftime("%Y-%m-%d %H:%M")

        for attempt in range(1, max_retries + 1):
            try:
                raw_candles = self.broker_client.get_candle_data(
                    symbol_token=token,
                    exchange=exchange,
                    interval=interval,
                    from_date=from_date,
                    to_date=to_date
                )

                formatted = []
                if raw_candles:
                    for c in raw_candles:
                        if len(c) >= 6:
                            # AngelOne format: [timestamp, open, high, low, close, volume]
                            formatted.append({
                                "timestamp": c[0],
                                "open": float(c[1]),
                                "high": float(c[2]),
                                "low": float(c[3]),
                                "close": float(c[4]),
                                "volume": int(c[5])
                            })

                if formatted:
                    self._historical_candles_cache[cache_key] = {"candles": formatted, "cached_at": now}
                    self._save_candle_cache(cache_key, formatted, now)
                    if self.logger:
                        self.logger.info(f"📊 Fetched {len(formatted)} historical candles for {exchange}:{token}")
                    return formatted

                if self.logger:
                    self.logger.warning(f"⚠ Historical candle fetch returned 0 rows for {exchange}:{token}")
                break  # Empty-but-successful response — retrying won't help, fall through to cache.
            except Exception as e:
                if attempt < max_retries:
                    backoff_sec = min(2 * (2 ** (attempt - 1)), 10) + random.uniform(0, 1)
                    if self.logger:
                        self.logger.warning(
                            f"⚠ Historical candle fetch failed (attempt {attempt}/{max_retries}): {e} — retrying in {backoff_sec:.1f}s"
                        )
                    time.sleep(backoff_sec)
                else:
                    if self.logger:
                        self.logger.warning(f"⚠ Historical candle fetch failed after {max_retries} attempts: {e}")

        cached = self._historical_candles_cache.get(cache_key)
        if cached and cached.get("candles"):
            age_sec = (datetime.now() - cached["cached_at"]).total_seconds()
            if self.logger:
                self.logger.warning(
                    f"♻ Using stale cached historical candles for {exchange}:{token} "
                    f"(age {age_sec:.0f}s, {len(cached['candles'])} candles)"
                )
            return cached["candles"]

        # The in-memory cache above only helps a process that has already fetched once, so it
        # is empty in the case that matters: the warm-up at startup. On 2026-09-07 two
        # restarts inside eight minutes both hit "exceeding access rate" on this endpoint and
        # both logged "Strategy indicators will start from zero" — after which EMA9 and EMA21
        # were rebuilt from a couple of minutes of ticks and sat 0.1-0.7 points apart, against
        # 16 points from the 5-minute candles, and the chop filter rejected everything. A
        # disk copy of the last good fetch survives the restart that the memory cache cannot.
        disk = self._load_candle_cache(cache_key)
        if disk:
            candles, saved_at = disk
            if self.logger:
                self.logger.warning(
                    f"💾 Historical API unavailable — warming up from the on-disk candle cache "
                    f"for {exchange}:{token} ({len(candles)} candles, saved {saved_at})"
                )
            self._historical_candles_cache[cache_key] = {"candles": candles, "cached_at": datetime.now()}
            return candles

        return []

    # ---- on-disk fallback for the warm-up fetch -----------------------------

    def _candle_cache_path(self, cache_key: str) -> str:
        safe = cache_key.replace(":", "_")
        return os.path.join("data", "candle_cache", f"{safe}.json")

    def _save_candle_cache(self, cache_key: str, candles: List[Dict[str, Any]], when: datetime) -> None:
        """Best-effort: a failure to cache must never break a successful fetch."""
        try:
            path = self._candle_cache_path(cache_key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"saved_at": when.strftime("%Y-%m-%d %H:%M:%S"),
                           "cache_key": cache_key, "candles": candles}, fh)
            os.replace(tmp, path)          # atomic, so a crash cannot leave a half-written cache
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Candle cache write skipped for {cache_key}: {e}")

    def _load_candle_cache(self, cache_key: str) -> Optional[Tuple[List[Dict[str, Any]], str]]:
        try:
            path = self._candle_cache_path(cache_key)
            if not os.path.exists(path):
                return None
            with open(path, encoding="utf-8") as fh:
                blob = json.load(fh)
            candles = blob.get("candles") or []
            if not candles:
                return None
            return candles, str(blob.get("saved_at", "unknown"))
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Candle cache read skipped for {cache_key}: {e}")
            return None
