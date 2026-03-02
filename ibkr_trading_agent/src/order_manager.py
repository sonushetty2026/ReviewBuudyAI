"""
Order Manager — bracket order submission, fill monitoring, kill switch.

Bracket order structure per trade:
  1. Entry LMT  (parent)
  2. Stop STP   (child, OCA group)
  3. TP1 LMT    (child, OCA group, partial qty)
  4. TP2 LMT    (child, OCA group, remaining qty)

Any exit fill triggers OCA cancellation of remaining exit legs.

In dry_run mode: orders are logged but never submitted to IBKR.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ib_insync import IB, Contract, Fill, LimitOrder, MarketOrder, StopOrder, Trade

from .config_loader import StrategyConfig
from .risk_manager import RiskManager
from .signals import Signal
from .storage import FillRecord, OrderRecord, PositionRecord, Storage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal state per open trade
# ---------------------------------------------------------------------------

@dataclass
class OpenTrade:
    symbol: str
    side: str           # BUY | SELL
    qty: int
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    partial_at_tp1: float

    # IBKR trade objects (None in dry-run)
    entry_trade: Optional[Trade] = None
    stop_trade: Optional[Trade] = None
    tp1_trade: Optional[Trade] = None
    tp2_trade: Optional[Trade] = None

    # DB row id
    position_row_id: int = 0

    # Timing
    submitted_ts: float = field(default_factory=time.monotonic)
    entry_fill_ts: Optional[float] = None

    # Fill tracking
    entry_filled_qty: int = 0
    entry_avg_price: float = 0.0
    exit_filled_qty: int = 0
    exit_avg_price: float = 0.0

    # MAE / MFE
    mae: float = 0.0
    mfe: float = 0.0

    # Fake-breakout tracking
    time_above_or: int = 0   # bars price stayed beyond breakout level

    run_id: str = ""


# ---------------------------------------------------------------------------
# Order Manager
# ---------------------------------------------------------------------------

class OrderManager:
    """
    Manages the full lifecycle of bracket orders.
    """

    def __init__(
        self,
        ib: IB,
        cfg: StrategyConfig,
        risk: RiskManager,
        storage: Storage,
        logger_: logging.Logger,
        dry_run: bool = False,
        run_id: str = "",
    ):
        self._ib = ib
        self._cfg = cfg
        self._risk = risk
        self._storage = storage
        self._log = logger_
        self._dry_run = dry_run
        self._run_id = run_id

        self._open_trades: dict[str, OpenTrade] = {}   # symbol → OpenTrade
        self._min_ticks: dict[str, float] = {}          # symbol → minTick
        self._contracts: dict[str, Contract] = {}       # symbol → Contract

        self._oca_counter: int = 0

        # Wire up ib_insync callbacks
        self._ib.orderStatusEvent += self._on_order_status
        self._ib.execDetailsEvent += self._on_exec_details

    def set_contract(self, symbol: str, contract: Contract, min_tick: float) -> None:
        self._contracts[symbol] = contract
        self._min_ticks[symbol] = min_tick

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id

    # ------------------------------------------------------------------
    # Bracket submission
    # ------------------------------------------------------------------

    async def submit_bracket(self, signal: Signal) -> Optional[OpenTrade]:
        """
        Submit a bracket order for *signal*.
        Returns the OpenTrade record, or None on failure.
        """
        symbol = signal.symbol
        side = "BUY" if signal.action == "ENTER_LONG" else "SELL"
        exit_side = "SELL" if side == "BUY" else "BUY"

        min_tick = self._min_ticks.get(symbol, 0.01)
        contract = self._contracts.get(symbol)
        if contract is None:
            logger.error("No contract registered for %s", symbol)
            return None

        # Round prices to valid tick increments
        entry_px = self.round_to_tick(signal.entry_price, min_tick)
        stop_px = self.round_to_tick(signal.stop_price, min_tick)
        tp1_px = self.round_to_tick(signal.tp1_price, min_tick)
        tp2_px = self.round_to_tick(signal.tp2_price, min_tick)

        qty = signal.qty
        if qty < 1:
            logger.error("Signal qty < 1 for %s — skipping", symbol)
            return None

        tp1_qty = max(1, int(math.floor(qty * self._cfg.partial_exit_pct_at_r1)))
        tp2_qty = qty - tp1_qty
        if tp2_qty < 1:
            tp1_qty = qty
            tp2_qty = 0   # No TP2 if position too small

        oca_group = self._next_oca_group(symbol)
        ts = datetime.now(timezone.utc).isoformat()

        if self._dry_run:
            logger.info(
                "[DRY-RUN] Bracket %s %s %d @ %.4f | stop=%.4f tp1=%.4f tp2=%.4f",
                side, symbol, qty, entry_px, stop_px, tp1_px, tp2_px,
            )
            ot = OpenTrade(
                symbol=symbol, side=side, qty=qty,
                entry_price=entry_px, stop_price=stop_px,
                tp1_price=tp1_px, tp2_price=tp2_px,
                partial_at_tp1=self._cfg.partial_exit_pct_at_r1,
                run_id=self._run_id,
            )
            self._open_trades[symbol] = ot
            self._persist_order(ot, -1, "entry", ts)
            return ot

        try:
            # --- Entry order (parent) ---
            entry_order = LimitOrder(
                action=side,
                totalQuantity=qty,
                lmtPrice=entry_px,
                transmit=False,          # transmit=False until children created
                tif="DAY",
            )

            # --- Stop loss (child) ---
            stop_order = StopOrder(
                action=exit_side,
                totalQuantity=qty,
                stopPrice=stop_px,
                transmit=False,
                tif="GTC",
                ocaGroup=oca_group,
                ocaType=1,               # cancel all other on fill
                parentId=0,              # will be set after entry placed
            )

            # --- TP1 (child, partial) ---
            tp1_order = LimitOrder(
                action=exit_side,
                totalQuantity=tp1_qty,
                lmtPrice=tp1_px,
                transmit=False,
                tif="DAY",
                ocaGroup=oca_group,
                ocaType=1,
            )

            # Place entry first to get its order ID
            entry_trade = self._ib.placeOrder(contract, entry_order)
            await asyncio.sleep(0.05)   # tiny wait for ID assignment
            parent_id = entry_order.orderId

            stop_order.parentId = parent_id
            tp1_order.parentId = parent_id

            stop_trade = self._ib.placeOrder(contract, stop_order)

            if tp2_qty > 0:
                tp2_order = LimitOrder(
                    action=exit_side,
                    totalQuantity=tp2_qty,
                    lmtPrice=tp2_px,
                    transmit=True,       # transmit all on last child
                    tif="DAY",
                    ocaGroup=oca_group,
                    ocaType=1,
                    parentId=parent_id,
                )
                tp1_order.transmit = False
                tp1_trade = self._ib.placeOrder(contract, tp1_order)
                tp2_trade = self._ib.placeOrder(contract, tp2_order)
            else:
                tp1_order.transmit = True
                tp1_trade = self._ib.placeOrder(contract, tp1_order)
                tp2_trade = None

            logger.info(
                "Bracket submitted %s %s %d @ %.4f | stop=%.4f tp1=%.4f tp2=%.4f oca=%s",
                side, symbol, qty, entry_px, stop_px, tp1_px, tp2_px, oca_group,
            )

            ot = OpenTrade(
                symbol=symbol, side=side, qty=qty,
                entry_price=entry_px, stop_price=stop_px,
                tp1_price=tp1_px, tp2_price=tp2_px,
                partial_at_tp1=self._cfg.partial_exit_pct_at_r1,
                entry_trade=entry_trade,
                stop_trade=stop_trade,
                tp1_trade=tp1_trade,
                tp2_trade=tp2_trade,
                run_id=self._run_id,
            )
            self._open_trades[symbol] = ot

            # Persist to DB
            self._persist_order(ot, entry_order.orderId, "entry", ts)
            self._persist_order(ot, stop_order.orderId, "stop", ts)
            self._persist_order(ot, tp1_order.orderId, "take_profit_1", ts)
            if tp2_qty > 0:
                self._persist_order(ot, tp2_order.orderId, "take_profit_2", ts)

            return ot

        except Exception as exc:
            logger.error("Bracket submission failed for %s: %s", symbol, exc)
            return None

    # ------------------------------------------------------------------
    # Position monitoring (call from main loop)
    # ------------------------------------------------------------------

    async def monitor(self, current_prices: dict[str, float]) -> None:
        """
        Called every second from the main loop.
        - Cancel stale unfilled entries
        - Update MAE/MFE
        - Update unrealized PnL in risk manager
        - Trail stop after +1R
        """
        now = time.monotonic()
        to_remove: list[str] = []

        for sym, ot in list(self._open_trades.items()):
            price = current_prices.get(sym, 0.0)
            if price <= 0:
                continue

            # --- Stale entry cancel ---
            if ot.entry_filled_qty == 0:
                age = now - ot.submitted_ts
                if age > self._cfg.stale_entry_cancel_sec:
                    await self._cancel_stale_entry(sym, ot)
                    to_remove.append(sym)
                    continue

            # --- MAE / MFE tracking ---
            if ot.entry_filled_qty > 0 and ot.entry_avg_price > 0:
                if ot.side == "BUY":
                    excursion = (price - ot.entry_avg_price) / ot.entry_avg_price
                else:
                    excursion = (ot.entry_avg_price - price) / ot.entry_avg_price
                ot.mfe = max(ot.mfe, excursion)
                ot.mae = min(ot.mae, excursion)

                # Update risk manager unrealized
                self._risk.update_unrealized(sym, price)

        for sym in to_remove:
            self._open_trades.pop(sym, None)

    async def _cancel_stale_entry(self, symbol: str, ot: OpenTrade) -> None:
        logger.info("Cancelling stale entry for %s", symbol)
        if not self._dry_run and ot.entry_trade:
            try:
                self._ib.cancelOrder(ot.entry_trade.order)
                # Cancel child orders too
                for child in (ot.stop_trade, ot.tp1_trade, ot.tp2_trade):
                    if child:
                        self._ib.cancelOrder(child.order)
            except Exception as exc:
                logger.warning("Cancel error for %s: %s", symbol, exc)

        ts = datetime.now(timezone.utc).isoformat()
        if ot.entry_trade and not self._dry_run:
            oid = ot.entry_trade.order.orderId
        else:
            oid = -1
        self._storage.upsert_order(OrderRecord(
            run_id=self._run_id, order_id=oid, symbol=symbol,
            order_type="entry", action=ot.side, qty=ot.qty,
            limit_price=ot.entry_price, status="cancelled",
            submitted_ts=ts, last_update_ts=ts,
        ))

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    async def flatten_all(self, reason: str) -> None:
        """Cancel all open orders, market-sell all open positions."""
        logger.critical("FLATTEN ALL — reason: %s", reason)

        if self._dry_run:
            self._open_trades.clear()
            return

        # Cancel all open orders via ib_insync
        try:
            for trade in self._ib.openTrades():
                try:
                    self._ib.cancelOrder(trade.order)
                except Exception as exc:
                    logger.warning("Cancel order %d failed: %s", trade.order.orderId, exc)
            await asyncio.sleep(0.5)
        except Exception as exc:
            logger.error("Error cancelling orders during flatten: %s", exc)

        # Market-close all remaining positions
        for sym, ot in list(self._open_trades.items()):
            if ot.entry_filled_qty > 0:
                exit_side = "SELL" if ot.side == "BUY" else "BUY"
                remaining = ot.entry_filled_qty - ot.exit_filled_qty
                if remaining <= 0:
                    continue
                contract = self._contracts.get(sym)
                if contract is None:
                    continue
                try:
                    mkt_order = MarketOrder(action=exit_side, totalQuantity=remaining)
                    self._ib.placeOrder(contract, mkt_order)
                    logger.info("Market exit placed for %s x %d (%s)", sym, remaining, exit_side)
                except Exception as exc:
                    logger.error("Flatten market order failed for %s: %s", sym, exc)

        await asyncio.sleep(1.0)
        self._open_trades.clear()

    # ------------------------------------------------------------------
    # ib_insync callbacks
    # ------------------------------------------------------------------

    def _on_order_status(self, trade: Trade) -> None:
        if not trade.contract:
            return
        sym = trade.contract.symbol
        status = trade.orderStatus.status
        oid = trade.order.orderId
        ts = datetime.now(timezone.utc).isoformat()

        logger.debug("OrderStatus %s [%d]: %s", sym, oid, status)

        self._storage.upsert_order(OrderRecord(
            run_id=self._run_id, order_id=oid, symbol=sym,
            order_type="unknown", action=trade.order.action,
            qty=int(trade.order.totalQuantity),
            limit_price=float(getattr(trade.order, "lmtPrice", 0) or 0),
            status=status.lower(),
            submitted_ts=ts, last_update_ts=ts,
        ))

    def _on_exec_details(self, trade: Trade, fill: Fill) -> None:
        if not trade.contract:
            return
        sym = trade.contract.symbol
        fill_px = fill.execution.price
        fill_qty = int(fill.execution.shares)
        oid = trade.order.orderId
        exec_id = fill.execution.execId
        commission = float(fill.commissionReport.commission or 0) if fill.commissionReport else 0.0
        ts = fill.time.isoformat() if fill.time else datetime.now(timezone.utc).isoformat()

        logger.info(
            "FILL %s [%d] %s %d @ %.4f (commission=%.2f)",
            sym, oid, trade.order.action, fill_qty, fill_px, commission,
        )

        # Persist fill
        self._storage.insert_fill(FillRecord(
            order_id=oid, exec_id=exec_id,
            fill_price=fill_px, fill_qty=fill_qty,
            commission=commission, ts=ts,
        ))

        ot = self._open_trades.get(sym)
        if ot is None:
            return

        action = trade.order.action

        # Entry fill
        if action == ot.side:
            prev_qty = ot.entry_filled_qty
            prev_total = ot.entry_avg_price * prev_qty
            ot.entry_filled_qty += fill_qty
            ot.entry_avg_price = (prev_total + fill_px * fill_qty) / ot.entry_filled_qty
            ot.entry_fill_ts = time.monotonic()
            self._risk.record_entry_fill(sym, ot.side, ot.entry_avg_price, ot.entry_filled_qty)

            # Open position in DB
            pos_id = self._storage.insert_position(PositionRecord(
                run_id=self._run_id, symbol=sym,
                entry_price=ot.entry_avg_price, qty=ot.entry_filled_qty,
                stop_price=ot.stop_price, tp1_price=ot.tp1_price, tp2_price=ot.tp2_price,
                open_ts=ts, close_ts="",
                realized_pnl=0.0, r_multiple=0.0, mae=0.0, mfe=0.0,
            ))
            ot.position_row_id = pos_id

        # Exit fill (stop, TP1, TP2)
        else:
            ot.exit_filled_qty += fill_qty
            prev_qty_e = ot.exit_filled_qty - fill_qty
            prev_total_e = ot.exit_avg_price * prev_qty_e
            ot.exit_avg_price = (prev_total_e + fill_px * fill_qty) / ot.exit_filled_qty

            pnl = self._risk.record_exit(sym, fill_px, fill_qty)

            # Update position record
            risk_per_share = abs(ot.entry_avg_price - ot.stop_price)
            r_mult = pnl / (risk_per_share * fill_qty) if risk_per_share > 0 else 0.0
            if ot.position_row_id:
                closed = ot.exit_filled_qty >= ot.entry_filled_qty
                self._storage.update_position(
                    ot.position_row_id,
                    close_ts=ts if closed else "",
                    realized_pnl=round(pnl, 4),
                    r_multiple=round(r_mult, 4),
                    mae=round(ot.mae, 6),
                    mfe=round(ot.mfe, 6),
                )

            if ot.exit_filled_qty >= ot.entry_filled_qty:
                logger.info("Position fully closed: %s PnL=%.2f R=%.2f", sym, pnl, r_mult)
                self._open_trades.pop(sym, None)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def round_to_tick(self, price: float, min_tick: float) -> float:
        """Round *price* to the nearest valid tick increment."""
        if min_tick <= 0:
            return round(price, 4)
        ticks = round(price / min_tick)
        return round(ticks * min_tick, 10)

    def _next_oca_group(self, symbol: str) -> str:
        self._oca_counter += 1
        return f"ibkr_agent_{symbol}_{self._oca_counter}"

    def _persist_order(self, ot: OpenTrade, order_id: int,
                       order_type: str, ts: str) -> None:
        self._storage.upsert_order(OrderRecord(
            run_id=self._run_id,
            order_id=order_id,
            symbol=ot.symbol,
            order_type=order_type,
            action=ot.side,
            qty=ot.qty,
            limit_price=ot.entry_price,
            status="submitted",
            submitted_ts=ts,
            last_update_ts=ts,
        ))

    def get_open_trades(self) -> dict[str, OpenTrade]:
        return dict(self._open_trades)

    def get_open_position_info(self) -> list[dict]:
        result = []
        for sym, ot in self._open_trades.items():
            result.append({
                "symbol": sym,
                "side": ot.side,
                "qty": ot.qty,
                "entry_filled": ot.entry_filled_qty,
                "entry_price": ot.entry_avg_price or ot.entry_price,
                "stop": ot.stop_price,
                "tp1": ot.tp1_price,
                "tp2": ot.tp2_price,
            })
        return result
