"""
Market data feed — OHLCV bars, VWAP, ATR, Opening Range tracking.

DataFeed subscribes to ib_async Tickers for each watchlist symbol and
maintains per-symbol SymbolData objects that are updated on every tick.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ib_async import IB, Contract, Ticker

from .config_loader import StrategyConfig

logger = logging.getLogger(__name__)

_SENTINEL = float("nan")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class SymbolData:
    symbol: str

    # OHLCV bars (N-minute bars, rolling)
    bars: deque = field(default_factory=lambda: deque(maxlen=100))

    # Current bar accumulation
    current_bar_open: float = _SENTINEL
    current_bar_high: float = _SENTINEL
    current_bar_low: float = _SENTINEL
    current_bar_last: float = _SENTINEL
    current_bar_volume: int = 0
    current_bar_ts: Optional[datetime] = None

    # VWAP (cumulative from session open)
    vwap_cum_pv: float = 0.0    # cumulative price * volume
    vwap_cum_vol: int = 0
    vwap: float = _SENTINEL

    # Opening range
    or_high: Optional[float] = None
    or_low: Optional[float] = None
    or_complete: bool = False

    # ATR
    atr: float = _SENTINEL
    prev_close: Optional[float] = None

    # Quote tracking
    last_bid: float = _SENTINEL
    last_ask: float = _SENTINEL
    last_price: float = _SENTINEL
    spread_bps: float = _SENTINEL
    last_quote_ts: Optional[datetime] = None

    # Gap (set at market open using pre-market close vs prior close)
    gap_pct: float = 0.0

    # Volume stats
    avg_bar_volume: float = 0.0    # rolling average volume per bar


# ---------------------------------------------------------------------------
# DataFeed
# ---------------------------------------------------------------------------

class DataFeed:
    """
    Subscribes to market data for a watchlist and maintains SymbolData objects.

    Call order:
      feed.subscribe(symbols)
      # ib_async event loop runs → on_ticker_update fires automatically
      # On bar boundary: feed.finalize_bar(symbol, bar_ts)
      # At or_end_time:  feed.set_opening_range(symbol)
    """

    def __init__(self, ib: IB, cfg: StrategyConfig):
        self._ib = ib
        self._cfg = cfg
        self._data: dict[str, SymbolData] = {}
        self._tickers: dict[str, Ticker] = {}
        self._contracts: dict[str, Contract] = {}

        # Wire up the ib_async pending-tickers event
        self._ib.pendingTickersEvent += self._on_pending_tickers

    def subscribe(self, symbols: list[str],
                  contracts: dict[str, Contract]) -> None:
        """
        Subscribe to mktData for each symbol.
        *contracts* must be qualified contracts (from broker.qualify_contract).
        """
        for sym in symbols:
            if sym in self._tickers:
                continue  # already subscribed
            contract = contracts.get(sym)
            if contract is None:
                logger.warning("No contract for %s — skipping subscription", sym)
                continue
            self._contracts[sym] = contract
            self._data[sym] = SymbolData(symbol=sym)
            ticker = self._ib.reqMktData(
                contract, genericTickList="", snapshot=False, regulatorySnapshot=False
            )
            self._tickers[sym] = ticker
            logger.info("Subscribed to %s", sym)

    def cancel_all(self) -> None:
        for sym, ticker in self._tickers.items():
            try:
                self._ib.cancelMktData(self._contracts[sym])
            except Exception as exc:
                logger.debug("cancelMktData %s: %s", sym, exc)
        self._tickers.clear()

    # ------------------------------------------------------------------
    # Tick ingestion (called by ib_async event loop)
    # ------------------------------------------------------------------

    def _on_pending_tickers(self, tickers: set) -> None:
        for ticker in tickers:
            sym = ticker.contract.symbol if ticker.contract else None
            if sym and sym in self._data:
                self._ingest_ticker(sym, ticker)

    def _ingest_ticker(self, symbol: str, ticker: Ticker) -> None:
        sd = self._data[symbol]
        now = datetime.now(timezone.utc)

        # Update quote fields
        bid = ticker.bid if ticker.bid and not math.isnan(ticker.bid) else _SENTINEL
        ask = ticker.ask if ticker.ask and not math.isnan(ticker.ask) else _SENTINEL
        last = ticker.last if ticker.last and not math.isnan(ticker.last) else _SENTINEL
        vol = int(ticker.lastSize or 0)

        if not math.isnan(bid):
            sd.last_bid = bid
        if not math.isnan(ask):
            sd.last_ask = ask

        # Spread in bps
        if not math.isnan(bid) and not math.isnan(ask) and ask > 0 and bid > 0:
            mid = (bid + ask) / 2.0
            sd.spread_bps = (ask - bid) / mid * 10_000.0

        # Use last trade for price (fall back to mid)
        price = last
        if math.isnan(price) and not math.isnan(bid) and not math.isnan(ask):
            price = (bid + ask) / 2.0
        if math.isnan(price):
            return

        sd.last_price = price
        sd.last_quote_ts = now

        # Accumulate into current bar
        if math.isnan(sd.current_bar_open):
            sd.current_bar_open = price
            sd.current_bar_high = price
            sd.current_bar_low = price
            sd.current_bar_ts = now
        else:
            sd.current_bar_high = max(sd.current_bar_high, price)
            sd.current_bar_low = min(sd.current_bar_low, price)
        sd.current_bar_last = price
        sd.current_bar_volume += vol

        # Update VWAP
        if vol > 0:
            self._update_vwap(symbol, price, vol)

    def _update_vwap(self, symbol: str, price: float, volume: int) -> None:
        sd = self._data[symbol]
        sd.vwap_cum_pv += price * volume
        sd.vwap_cum_vol += volume
        if sd.vwap_cum_vol > 0:
            sd.vwap = sd.vwap_cum_pv / sd.vwap_cum_vol

    # ------------------------------------------------------------------
    # Bar finalisation (called by main scheduler every N minutes)
    # ------------------------------------------------------------------

    def finalize_bar(self, symbol: str, bar_ts: datetime) -> Optional[Bar]:
        """
        Close the current accumulation bar and push it to the bar deque.
        Returns the completed Bar or None if no data was accumulated.
        """
        sd = self._data.get(symbol)
        if sd is None or math.isnan(sd.current_bar_open):
            return None

        bar = Bar(
            ts=bar_ts,
            open=sd.current_bar_open,
            high=sd.current_bar_high,
            low=sd.current_bar_low,
            close=sd.current_bar_last,
            volume=sd.current_bar_volume,
        )
        sd.bars.append(bar)
        self._update_atr(symbol, bar)
        self._update_avg_volume(symbol)
        sd.prev_close = bar.close

        # Reset accumulator
        sd.current_bar_open = _SENTINEL
        sd.current_bar_high = _SENTINEL
        sd.current_bar_low = _SENTINEL
        sd.current_bar_last = _SENTINEL
        sd.current_bar_volume = 0
        sd.current_bar_ts = None

        logger.debug(
            "Bar finalised %s  O=%.2f H=%.2f L=%.2f C=%.2f V=%d",
            symbol, bar.open, bar.high, bar.low, bar.close, bar.volume,
        )
        return bar

    # ------------------------------------------------------------------
    # Opening range
    # ------------------------------------------------------------------

    def set_opening_range(self, symbol: str) -> None:
        """
        Set or_high/or_low from bars accumulated during the OR window.
        Called at or_end_time by the scheduler.
        """
        sd = self._data.get(symbol)
        if sd is None:
            return

        # Collect bars within the OR window (should be 1 or more depending on bar size)
        if not sd.bars:
            # Fall back to current partial bar data
            if not math.isnan(sd.current_bar_high) and not math.isnan(sd.current_bar_low):
                sd.or_high = sd.current_bar_high
                sd.or_low = sd.current_bar_low
        else:
            # Use all bars so far (they're all within the OR window at this point)
            sd.or_high = max(b.high for b in sd.bars)
            sd.or_low = min(b.low for b in sd.bars)

        if sd.or_high is not None and sd.or_low is not None:
            sd.or_complete = True
            logger.info(
                "Opening Range set %s  H=%.2f  L=%.2f",
                symbol, sd.or_high, sd.or_low,
            )
        else:
            logger.warning("Could not set opening range for %s — no data", symbol)

    def set_gap(self, symbol: str, prev_close: float) -> None:
        """Compute gap % from previous session close to first session price."""
        sd = self._data.get(symbol)
        if sd is None or prev_close <= 0:
            return
        if not math.isnan(sd.current_bar_open):
            sd.gap_pct = (sd.current_bar_open - prev_close) / prev_close * 100.0

    # ------------------------------------------------------------------
    # ATR (Wilder's)
    # ------------------------------------------------------------------

    def _update_atr(self, symbol: str, bar: Bar) -> None:
        sd = self._data[symbol]
        n = self._cfg.atr_lookback
        prev_close = sd.prev_close

        if prev_close is None:
            tr = bar.high - bar.low
        else:
            tr = max(
                bar.high - bar.low,
                abs(bar.high - prev_close),
                abs(bar.low - prev_close),
            )

        if math.isnan(sd.atr):
            # Seed with first TR
            sd.atr = tr
        else:
            # Wilder's smoothing
            sd.atr = (sd.atr * (n - 1) + tr) / n

        # Floor: ATR must be at least 0.15% of price to prevent micro-stops
        # (delayed data compresses bar ranges → unrealistically small ATR)
        price = bar.close if bar.close > 0 else bar.high
        if price > 0:
            atr_floor = price * 0.0015
            if sd.atr < atr_floor:
                sd.atr = atr_floor

    def _update_avg_volume(self, symbol: str) -> None:
        sd = self._data[symbol]
        if not sd.bars:
            return
        vols = [b.volume for b in sd.bars if b.volume > 0]
        sd.avg_bar_volume = sum(vols) / len(vols) if vols else 0.0

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> Optional[SymbolData]:
        return self._data.get(symbol)

    def is_stale(self, symbol: str, threshold_sec: int) -> bool:
        sd = self._data.get(symbol)
        if sd is None or sd.last_quote_ts is None:
            return True
        age = (datetime.now(timezone.utc) - sd.last_quote_ts).total_seconds()
        return age > threshold_sec

    def get_snapshot(self, symbol: str) -> dict:
        """Return a JSON-serialisable snapshot of key metrics for logging."""
        sd = self._data.get(symbol)
        if sd is None:
            return {"symbol": symbol, "error": "no_data"}

        def _f(v: float, precision: int = 4) -> Optional[float]:
            return None if math.isnan(v) else round(v, precision)

        last_bar = sd.bars[-1] if sd.bars else None
        return {
            "symbol": symbol,
            "last": _f(sd.last_price, 4),
            "bid": _f(sd.last_bid, 4),
            "ask": _f(sd.last_ask, 4),
            "spread_bps": _f(sd.spread_bps, 2),
            "vwap": _f(sd.vwap, 4),
            "atr": _f(sd.atr, 4),
            "or_high": sd.or_high,
            "or_low": sd.or_low,
            "or_complete": sd.or_complete,
            "gap_pct": round(sd.gap_pct, 2),
            "bars_count": len(sd.bars),
            "last_bar": {
                "open": last_bar.open, "high": last_bar.high,
                "low": last_bar.low, "close": last_bar.close,
                "volume": last_bar.volume,
            } if last_bar else None,
        }

    def get_last_n_closes(self, symbol: str, n: int) -> list[float]:
        sd = self._data.get(symbol)
        if sd is None:
            return []
        return [b.close for b in list(sd.bars)[-n:]]

    def symbols(self) -> list[str]:
        return list(self._data.keys())
