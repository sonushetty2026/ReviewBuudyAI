"""
Signal generation — Opening Range Breakout (ORB) with VWAP and RS filters.

Signal rules:
  LONG:  close > or_high  AND  close > vwap  AND  rs_vs_spy > 0
  SHORT: close < or_low   AND  close < vwap  AND  rs_vs_spy < 0  (if allow_shorts)

Entry:   limit at ask + entry_limit_offset (buy) or bid - offset (sell)
Stop:    min(or_low, entry - ATR)  for longs  (whichever is tighter)
         max(or_high, entry + ATR) for shorts
TP1/TP2: entry + R * take_profit_r1 / take_profit_r2
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .config_loader import StrategyConfig, WatchlistFilters
from .datafeed import DataFeed, SymbolData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Signal output
# ---------------------------------------------------------------------------

@dataclass
class Signal:
    symbol: str
    action: str             # ENTER_LONG | ENTER_SHORT | SKIP
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    qty: int = 0            # Filled in by risk_manager after sizing
    rationale: str = ""
    score: float = 0.0      # 0–1 conviction
    snapshot: dict = field(default_factory=dict)
    ts: str = ""


# ---------------------------------------------------------------------------
# Signal generator
# ---------------------------------------------------------------------------

class SignalGenerator:
    """Evaluates each watchlist symbol for ORB signals each trading loop tick."""

    def __init__(self, cfg: StrategyConfig, filters: WatchlistFilters, feed: DataFeed):
        self._cfg = cfg
        self._filters = filters
        self._feed = feed

    def scan_all(
        self,
        symbols: list[str],
        live_or_minutes: int,
        live_vwap_strength: int,
        banned_symbols: Optional[set[str]] = None,
    ) -> list[Signal]:
        """
        Scan all symbols, return signals with action ENTER_LONG / ENTER_SHORT.
        SKIP signals are not returned (they are logged elsewhere).
        """
        banned = banned_symbols or set()
        results: list[Signal] = []

        spy_data = self._feed.get("SPY")

        for sym in symbols:
            if sym in banned:
                continue
            try:
                sig = self.evaluate_symbol(sym, spy_data, live_vwap_strength)
                if sig and sig.action in ("ENTER_LONG", "ENTER_SHORT"):
                    results.append(sig)
            except Exception as exc:
                logger.error("Signal evaluation error for %s: %s", sym, exc)

        return results

    def evaluate_symbol(
        self,
        symbol: str,
        spy_data: Optional[SymbolData],
        vwap_strength: int,
    ) -> Optional[Signal]:
        """
        Evaluate a single symbol. Returns None if no meaningful signal.
        Returns Signal with action=SKIP if conditions not met (for logging).
        """
        sd = self._feed.get(symbol)
        if sd is None:
            return None

        ts = datetime.now(timezone.utc).isoformat()
        snap = self._feed.get_snapshot(symbol)

        def skip(reason: str) -> Signal:
            return Signal(
                symbol=symbol, action="SKIP",
                entry_price=0.0, stop_price=0.0, tp1_price=0.0, tp2_price=0.0,
                rationale=reason, snapshot=snap, ts=ts,
            )

        # --- Basic filters ---
        price = sd.last_price
        if math.isnan(price) or price <= 0:
            return skip("no_price")

        if price < self._filters.min_price:
            return skip(f"price_too_low: {price:.2f} < {self._filters.min_price}")

        if not math.isnan(sd.spread_bps) and sd.spread_bps > self._filters.max_spread_bps:
            return skip(f"spread_too_wide: {sd.spread_bps:.1f}bps")

        # --- Opening range must be complete ---
        if not sd.or_complete or sd.or_high is None or sd.or_low is None:
            return skip("or_not_complete")

        or_high = sd.or_high
        or_low = sd.or_low

        # --- VWAP must be valid ---
        if math.isnan(sd.vwap) or sd.vwap <= 0:
            return skip("vwap_unavailable")

        vwap = sd.vwap
        atr = sd.atr if not math.isnan(sd.atr) else (or_high - or_low) * 1.5

        # --- Relative strength vs SPY ---
        rs = self._compute_rs(symbol, spy_data)

        # --- Volume filter ---
        vol_ok = self._check_volume(sd)

        # === LONG signal ===
        long_breakout = price > or_high
        long_vwap = price > vwap
        long_rs = rs > 0

        if long_breakout and long_vwap and long_rs and vol_ok:
            # VWAP distance conviction: stronger if further above VWAP
            vwap_dist_pct = (price - vwap) / vwap * 100
            vwap_ok = self._check_vwap_strength(vwap_dist_pct, vwap_strength, side="long")
            if not vwap_ok:
                return skip(
                    f"vwap_filter_too_weak: dist={vwap_dist_pct:.2f}% strength={vwap_strength}"
                )

            entry = self._compute_entry(sd, "BUY")
            stop = self._compute_stop_long(or_low, entry, atr)
            risk = entry - stop
            if risk <= 0:
                return skip("stop_at_or_below_entry")

            tp1 = entry + risk * self._cfg.take_profit_r1
            tp2 = entry + risk * self._cfg.take_profit_r2

            score = self._compute_score(vwap_dist_pct, rs, sd)

            return Signal(
                symbol=symbol,
                action="ENTER_LONG",
                entry_price=round(entry, 4),
                stop_price=round(stop, 4),
                tp1_price=round(tp1, 4),
                tp2_price=round(tp2, 4),
                rationale=(
                    f"ORB long: price={price:.2f} > orH={or_high:.2f}, "
                    f"vwap={vwap:.2f} (+{vwap_dist_pct:.2f}%), rs={rs:.4f}"
                ),
                score=score,
                snapshot=snap,
                ts=ts,
            )

        # === SHORT signal ===
        if self._cfg.allow_shorts:
            short_breakout = price < or_low
            short_vwap = price < vwap
            short_rs = rs < 0

            if short_breakout and short_vwap and short_rs and vol_ok:
                vwap_dist_pct = (vwap - price) / vwap * 100
                vwap_ok = self._check_vwap_strength(vwap_dist_pct, vwap_strength, side="short")
                if not vwap_ok:
                    return skip(
                        f"vwap_filter_too_weak (short): dist={vwap_dist_pct:.2f}%"
                    )

                entry = self._compute_entry(sd, "SELL")
                stop = self._compute_stop_short(or_high, entry, atr)
                risk = stop - entry
                if risk <= 0:
                    return skip("stop_at_or_below_entry (short)")

                tp1 = entry - risk * self._cfg.take_profit_r1
                tp2 = entry - risk * self._cfg.take_profit_r2

                score = self._compute_score(vwap_dist_pct, abs(rs), sd)

                return Signal(
                    symbol=symbol,
                    action="ENTER_SHORT",
                    entry_price=round(entry, 4),
                    stop_price=round(stop, 4),
                    tp1_price=round(tp1, 4),
                    tp2_price=round(tp2, 4),
                    rationale=(
                        f"ORB short: price={price:.2f} < orL={or_low:.2f}, "
                        f"vwap={vwap:.2f} (-{vwap_dist_pct:.2f}%), rs={rs:.4f}"
                    ),
                    score=score,
                    snapshot=snap,
                    ts=ts,
                )

        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_rs(self, symbol: str, spy: Optional[SymbolData]) -> float:
        """
        Relative strength = symbol_return - spy_return over last rs_lookback_bars.
        Positive → symbol stronger than SPY (good for longs).
        """
        n = self._cfg.rs_lookback_bars
        sym_closes = self._feed.get_last_n_closes(symbol, n + 1)
        if len(sym_closes) < 2:
            return 0.0
        sym_return = (sym_closes[-1] - sym_closes[0]) / sym_closes[0]

        if spy is None:
            return sym_return  # no SPY comparison available

        spy_closes = self._feed.get_last_n_closes("SPY", n + 1)
        if len(spy_closes) < 2:
            return sym_return
        spy_return = (spy_closes[-1] - spy_closes[0]) / spy_closes[0]

        return sym_return - spy_return

    def _compute_entry(self, sd: SymbolData, side: str) -> float:
        offset = self._cfg.entry_limit_offset
        if side == "BUY":
            ask = sd.last_ask if not math.isnan(sd.last_ask) else sd.last_price
            return ask + offset
        else:
            bid = sd.last_bid if not math.isnan(sd.last_bid) else sd.last_price
            return bid - offset

    def _compute_stop_long(self, or_low: float, entry: float, atr: float) -> float:
        """Stop = tighter of OR low or entry - ATR."""
        # Enforce minimum stop distance: at least 0.20% of entry price
        min_risk = entry * 0.0020
        effective_atr = max(atr, min_risk)
        atr_stop = entry - effective_atr
        return max(or_low, atr_stop)   # max because we want the tighter (higher) stop

    def _compute_stop_short(self, or_high: float, entry: float, atr: float) -> float:
        """Stop = tighter of OR high or entry + ATR."""
        # Enforce minimum stop distance: at least 0.20% of entry price
        min_risk = entry * 0.0020
        effective_atr = max(atr, min_risk)
        atr_stop = entry + effective_atr
        return min(or_high, atr_stop)  # min because we want the tighter (lower) stop

    def _check_vwap_strength(self, dist_pct: float, strength: int, side: str) -> bool:
        """
        strength=1 (loose):  any breakout
        strength=2 (medium): price must be >= 0.05% beyond VWAP
        strength=3 (strict): price must be >= 0.10% beyond VWAP
        """
        if strength <= 1:
            return True
        elif strength == 2:
            return dist_pct >= 0.05
        else:
            return dist_pct >= 0.10

    def _check_volume(self, sd: SymbolData) -> bool:
        """Current bar volume should be elevated vs average."""
        if sd.avg_bar_volume <= 0 or sd.current_bar_volume <= 0:
            return True  # can't filter, allow
        ratio = sd.current_bar_volume / sd.avg_bar_volume
        return ratio >= self._cfg.min_breakout_volume_ratio

    def _compute_score(self, vwap_dist_pct: float, rs: float,
                        sd: SymbolData) -> float:
        """Simple 0–1 conviction score from multiple sub-signals."""
        # VWAP distance component (0–0.4)
        vwap_score = min(0.4, vwap_dist_pct / 0.25 * 0.4)

        # RS component (0–0.3)
        rs_score = min(0.3, abs(rs) / 0.005 * 0.3)

        # Volume component (0–0.3)
        if sd.avg_bar_volume > 0 and sd.current_bar_volume > 0:
            vol_ratio = sd.current_bar_volume / sd.avg_bar_volume
            vol_score = min(0.3, (vol_ratio - 1.0) / 1.0 * 0.3)
        else:
            vol_score = 0.15  # neutral if unknown

        return round(vwap_score + rs_score + vol_score, 3)
