"""
Risk Manager — central authority that approves every trade and enforces all caps.

Hard limits (configured in settings.yaml):
  - max_daily_loss_usd
  - max_loss_per_trade_usd
  - max_trades_per_day
  - max_position_notional_usd
  - max_concurrent_positions
  - consecutive_loss_limit

Also tracks real-time unrealized PnL and triggers circuit breaker if daily loss
limit is hit.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from .config_loader import RiskConfig

logger = logging.getLogger(__name__)


class RiskManager:
    """
    Central risk gate.  Every entry must pass through approve_entry().
    Every fill and exit must be reported back so we track PnL accurately.
    """

    def __init__(self, cfg: RiskConfig):
        self._cfg = cfg

        # Session counters
        self._trades_today: int = 0
        self._realized_pnl: float = 0.0
        self._consecutive_losses: int = 0

        # Open positions: symbol → {entry_price, qty, side}
        self._open_positions: dict[str, dict] = {}

        # Unrealized PnL per symbol
        self._unrealized: dict[str, float] = {}

        # Circuit breaker state
        self._circuit_broken: bool = False
        self._circuit_reason: str = ""

        # Cooldown tracking (set by online learning)
        self._cooldown_until: Optional[datetime] = None

        # Symbol banlist (set by online learning)
        self._banlist: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def compute_position_size(
        self,
        price: float,
        stop_price: float,
        multiplier: float = 1.0,
    ) -> int:
        """
        shares = floor( min(max_notional/price, max_loss/stop_distance) * multiplier )

        Returns 0 if the trade should be rejected.
        """
        if price <= 0:
            return 0
        stop_dist = abs(price - stop_price)
        if stop_dist <= 0:
            return 0

        notional_limit = self._cfg.max_position_notional_usd / price
        loss_limit = self._cfg.max_loss_per_trade_usd / stop_dist

        raw = min(notional_limit, loss_limit) * multiplier
        shares = int(math.floor(raw))
        return max(0, shares)

    # ------------------------------------------------------------------
    # Trade approval gate
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        symbol: str,
        side: str,          # "BUY" | "SELL"
        price: float,
        stop_price: float,
        qty: int,
    ) -> tuple[bool, str]:
        """
        Run all risk checks in priority order.
        Returns (approved: bool, reason: str).
        """
        checks: list[tuple[bool, str]] = [
            self._check_circuit_breaker(),
            self._check_daily_loss(price, stop_price, qty),
            self._check_max_trades(),
            self._check_concurrent_positions(symbol),
            self._check_position_notional(price, qty),
            self._check_stop_distance(price, stop_price),
            self._check_consecutive_losses(),
            self._check_cooldown(),
            self._check_banlist(symbol),
        ]

        for ok, reason in checks:
            if not ok:
                logger.info("RISK VETO [%s] %s: %s", symbol, side, reason)
                return False, reason

        logger.info("RISK APPROVED [%s] %s qty=%d @ %.2f stop=%.2f",
                    symbol, side, qty, price, stop_price)
        return True, "all_checks_passed"

    def _check_circuit_breaker(self) -> tuple[bool, str]:
        if self._circuit_broken:
            return False, f"circuit_breaker_tripped: {self._circuit_reason}"
        return True, ""

    def _check_daily_loss(self, price: float, stop: float, qty: int) -> tuple[bool, str]:
        # Would this trade push us past the daily loss cap?
        potential_loss = abs(price - stop) * qty
        remaining = self._cfg.max_daily_loss_usd - abs(self._realized_pnl)
        if remaining <= 0:
            return False, f"daily_loss_limit_reached: realized={self._realized_pnl:.2f}"
        if potential_loss > self._cfg.max_loss_per_trade_usd:
            return False, (
                f"trade_loss_exceeds_cap: potential={potential_loss:.2f} "
                f"cap={self._cfg.max_loss_per_trade_usd:.2f}"
            )
        return True, ""

    def _check_max_trades(self) -> tuple[bool, str]:
        if self._trades_today >= self._cfg.max_trades_per_day:
            return False, f"max_trades_per_day_reached: {self._trades_today}/{self._cfg.max_trades_per_day}"
        return True, ""

    def _check_concurrent_positions(self, symbol: str) -> tuple[bool, str]:
        open_count = len(self._open_positions)
        # Allow adding to existing position in same symbol (shouldn't happen in our strategy)
        if symbol not in self._open_positions:
            if open_count >= self._cfg.max_concurrent_positions:
                return False, (
                    f"max_concurrent_positions: {open_count}/{self._cfg.max_concurrent_positions}"
                )
        return True, ""

    def _check_position_notional(self, price: float, qty: int) -> tuple[bool, str]:
        notional = price * qty
        if notional > self._cfg.max_position_notional_usd:
            return False, (
                f"notional_cap: {notional:.2f} > {self._cfg.max_position_notional_usd:.2f}"
            )
        return True, ""

    def _check_stop_distance(self, price: float, stop: float) -> tuple[bool, str]:
        dist = abs(price - stop)
        if dist <= 0:
            return False, "stop_distance_zero"
        # Stop must be reasonable: at least $0.05 or 0.10% of price, at most 10%
        min_dist = max(0.05, price * 0.0010)
        if dist < min_dist:
            return False, f"stop_too_tight: {dist:.4f} (min={min_dist:.4f})"
        if dist > price * 0.10:
            return False, f"stop_too_wide: {dist:.4f} ({dist/price*100:.1f}%)"
        return True, ""

    def _check_consecutive_losses(self) -> tuple[bool, str]:
        if self._consecutive_losses >= self._cfg.consecutive_loss_limit:
            return False, (
                f"consecutive_loss_limit: {self._consecutive_losses}/{self._cfg.consecutive_loss_limit}"
            )
        return True, ""

    def _check_cooldown(self) -> tuple[bool, str]:
        if self._cooldown_until is None:
            return True, ""
        now = datetime.now(timezone.utc)
        if now < self._cooldown_until:
            remaining = (self._cooldown_until - now).total_seconds()
            return False, f"cooldown: {remaining:.0f}s remaining"
        return True, ""

    def _check_banlist(self, symbol: str) -> tuple[bool, str]:
        if symbol in self._banlist:
            return False, f"symbol_banned: {self._banlist[symbol]}"
        return True, ""

    # ------------------------------------------------------------------
    # Fill / exit reporting
    # ------------------------------------------------------------------

    def record_entry_fill(self, symbol: str, side: str, price: float, qty: int) -> None:
        """Call when an entry order fills."""
        self._open_positions[symbol] = {
            "side": side, "entry_price": price, "qty": qty,
        }
        self._trades_today += 1
        logger.info("Entry fill recorded: %s %s %d @ %.4f", side, symbol, qty, price)

    def record_exit(self, symbol: str, exit_price: float, qty: int) -> float:
        """
        Call when position is fully or partially closed.
        Returns the PnL for this exit.
        """
        pos = self._open_positions.get(symbol)
        if pos is None:
            logger.warning("record_exit called for unknown position: %s", symbol)
            return 0.0

        entry = pos["entry_price"]
        side = pos["side"]
        if side == "BUY":
            pnl = (exit_price - entry) * qty
        else:
            pnl = (entry - exit_price) * qty

        self._realized_pnl += pnl

        if qty >= pos["qty"]:
            del self._open_positions[symbol]
            self._unrealized.pop(symbol, None)
        else:
            pos["qty"] -= qty

        # Track consecutive losses
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        logger.info(
            "Exit recorded: %s qty=%d @ %.4f  pnl=%.2f  realized_total=%.2f",
            symbol, qty, exit_price, pnl, self._realized_pnl,
        )

        # Check daily loss after exit
        self._check_and_trip_daily_loss()
        return pnl

    def update_unrealized(self, symbol: str, current_price: float) -> None:
        """Update mark-to-market unrealized PnL for an open position."""
        pos = self._open_positions.get(symbol)
        if pos is None:
            return
        entry = pos["entry_price"]
        qty = pos["qty"]
        side = pos["side"]
        if side == "BUY":
            upnl = (current_price - entry) * qty
        else:
            upnl = (entry - current_price) * qty
        self._unrealized[symbol] = upnl
        self._check_and_trip_daily_loss()

    def _check_and_trip_daily_loss(self) -> None:
        total = self._realized_pnl + sum(self._unrealized.values())
        if total <= -self._cfg.max_daily_loss_usd:
            self.trip_circuit_breaker(
                f"daily_loss_limit: total_pnl={total:.2f} <= -{self._cfg.max_daily_loss_usd}"
            )

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def trip_circuit_breaker(self, reason: str) -> None:
        if not self._circuit_broken:
            self._circuit_broken = True
            self._circuit_reason = reason
            logger.critical("RISK CIRCUIT BREAKER TRIPPED: %s", reason)

    def is_circuit_broken(self) -> bool:
        return self._circuit_broken

    # ------------------------------------------------------------------
    # Online learning hooks
    # ------------------------------------------------------------------

    def set_cooldown(self, minutes: int) -> None:
        from datetime import timedelta
        if minutes > 0:
            self._cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
            logger.info("Cooldown set: %d minutes", minutes)
        else:
            self._cooldown_until = None

    def add_to_banlist(self, symbol: str, reason: str) -> None:
        self._banlist[symbol] = reason
        logger.info("Symbol %s banned for session: %s", symbol, reason)

    def is_banned(self, symbol: str) -> bool:
        return symbol in self._banlist

    def get_banlist(self) -> dict[str, str]:
        return dict(self._banlist)

    # ------------------------------------------------------------------
    # Stats / reporting
    # ------------------------------------------------------------------

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def unrealized_pnl(self) -> float:
        return sum(self._unrealized.values())

    @property
    def total_pnl(self) -> float:
        return self._realized_pnl + self.unrealized_pnl

    @property
    def daily_loss_remaining(self) -> float:
        return self._cfg.max_daily_loss_usd - abs(min(0.0, self.total_pnl))

    @property
    def trades_today(self) -> int:
        return self._trades_today

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses

    @property
    def open_positions(self) -> dict:
        return dict(self._open_positions)

    def get_daily_stats(self) -> dict:
        return {
            "realized_pnl": round(self._realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "trades_today": self._trades_today,
            "trades_remaining": self._cfg.max_trades_per_day - self._trades_today,
            "daily_loss_remaining": round(self.daily_loss_remaining, 2),
            "consecutive_losses": self._consecutive_losses,
            "circuit_broken": self._circuit_broken,
            "circuit_reason": self._circuit_reason,
            "open_positions": len(self._open_positions),
        }
