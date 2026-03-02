"""
Main runner — asyncio orchestrator for the IBKR Trading Agent.

Usage:
  python -m src.main --config config/settings.yaml
  python -m src.main --config config/settings.yaml --dry-run

Trading schedule (America/Los_Angeles):
  06:15  PREP      — connect, qualify contracts, subscribe data
  06:30  OR_REC    — record opening range (no entries)
  06:35  TRADING   — scan signals, submit brackets
  09:30  WIND_DOWN — no new entries, manage exits
  09:45  DONE      — flatten remaining, generate EOD report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ib_insync import IB, Stock

from .broker import BrokerManager
from .config_loader import AppConfig, load_config
from .dashboard import AgentState, Dashboard, PositionEntry, WatchlistEntry
from .datafeed import DataFeed
from .logger import log_decision, log_error, setup_logging
from .online_learning import OnlineLearningController, TradeDiagnostic
from .order_manager import OrderManager
from .reporter import EODReporter
from .risk_manager import RiskManager
from .signals import SignalGenerator
from .storage import (
    DecisionRecord, ErrorRecord, PnlSnapshot, RunRecord, Storage,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------

class Phase:
    WAITING = "WAITING"
    PREP = "PREP"
    OR_RECORDING = "OR_RECORDING"
    TRADING = "TRADING"
    WIND_DOWN = "WIND_DOWN"
    DONE = "DONE"


# ---------------------------------------------------------------------------
# Trading Agent
# ---------------------------------------------------------------------------

class TradingAgent:
    """Main trading loop orchestrator."""

    def __init__(self, cfg: AppConfig, dry_run_override: bool = False):
        self._cfg = cfg
        self._dry_run = cfg.mode.dry_run or dry_run_override
        self._run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._tz = ZoneInfo(cfg.schedule.timezone)
        self._phase = Phase.WAITING
        self._shutdown_requested = False
        self._last_pnl_snapshot = 0.0

        # Determine mode label
        if cfg.mode.live_mode:
            self._mode_label = "live"
        elif self._dry_run:
            self._mode_label = "dry_run"
        else:
            self._mode_label = "paper"

        # Initialise all subsystems
        self._app_logger = setup_logging(cfg.paths.log_dir, self._date_str)
        self._storage = Storage(cfg.paths.db)
        self._broker = BrokerManager(cfg.broker, cfg.risk.circuit_breaker, self._storage)
        self._broker.set_run_id(self._run_id)
        self._feed = DataFeed(self._broker.ib, cfg.strategy)
        self._risk = RiskManager(cfg.risk)
        self._signals = SignalGenerator(cfg.strategy, cfg.watchlist.filters, self._feed)
        self._order_mgr = OrderManager(
            self._broker.ib, cfg.strategy, self._risk, self._storage,
            self._app_logger, self._dry_run, self._run_id,
        )
        self._ol = OnlineLearningController(
            cfg.online_learning, cfg.risk,
            initial_max_trades=cfg.risk.max_trades_per_day,
            app_logger=self._app_logger,
        )
        self._dashboard = Dashboard(tz=cfg.schedule.timezone)
        self._reporter = EODReporter(self._storage, cfg)

        # Qualified contracts and min-ticks (populated in prep)
        self._contracts: dict = {}
        self._min_ticks: dict = {}

        # Signal state for dashboard
        self._signal_states: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Top-level coroutine. Handles phases and graceful shutdown."""

        # Live mode safety gate
        if self._cfg.mode.live_mode:
            print("\n" + "=" * 60)
            print("  ⚠️  LIVE TRADING MODE ENABLED")
            print("  Real money orders will be placed at IBKR.")
            print("  Press Ctrl-C within 5 seconds to abort.")
            print("=" * 60 + "\n")
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                print("Aborted by user.")
                return

        # Persist run record
        self._storage.insert_run(RunRecord(
            run_id=self._run_id,
            start_ts=datetime.now(timezone.utc).isoformat(),
            end_ts="",
            mode=self._mode_label,
            config_snapshot=json.dumps({
                "paper_only": self._cfg.mode.paper_only,
                "live_mode": self._cfg.mode.live_mode,
                "risk": {
                    "max_daily_loss_usd": self._cfg.risk.max_daily_loss_usd,
                    "max_loss_per_trade_usd": self._cfg.risk.max_loss_per_trade_usd,
                    "max_trades_per_day": self._cfg.risk.max_trades_per_day,
                },
            }),
        ))

        logger.info("Run started: %s  mode=%s", self._run_id, self._mode_label)
        self._dashboard.start()

        try:
            # Connect to IBKR
            if not self._dry_run:
                connected = await self._broker.connect()
                if not connected:
                    logger.critical("Cannot connect to IBKR. Exiting.")
                    return
            else:
                logger.info("[DRY-RUN] Skipping IBKR connection.")

            # Wait for and execute each phase
            await self._wait_for_phase(Phase.PREP, self._cfg.schedule.prep_time)
            await self._prep_phase()

            await self._wait_for_phase(Phase.OR_RECORDING, self._cfg.schedule.market_open)
            await self._or_recording_phase()

            await self._wait_for_phase(Phase.TRADING, self._cfg.schedule.trading_start)
            await self._trading_phase()

            await self._wind_down_phase()

        except asyncio.CancelledError:
            logger.info("Agent cancelled — initiating graceful shutdown.")
        except Exception as exc:
            logger.critical("Unhandled exception: %s\n%s", exc, traceback.format_exc())
            self._storage.insert_error(ErrorRecord(
                run_id=self._run_id,
                ts=datetime.now(timezone.utc).isoformat(),
                module="main",
                error_type=type(exc).__name__,
                message=str(exc),
                traceback=traceback.format_exc(),
            ))
        finally:
            await self._shutdown()

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _prep_phase(self) -> None:
        """Connect, qualify contracts, subscribe data."""
        self._phase = Phase.PREP
        logger.info("=== PREP PHASE ===")

        symbols = self._cfg.watchlist.symbols
        logger.info("Watchlist: %s", symbols)

        if self._dry_run:
            # Dry-run: create stub contracts
            for sym in symbols:
                self._contracts[sym] = Stock(sym, "SMART", "USD")
                self._min_ticks[sym] = 0.01
            self._feed.subscribe(symbols, self._contracts)
            return

        # Qualify contracts
        for sym in symbols:
            contract = Stock(sym, "SMART", "USD")
            qualified = await self._broker.qualify_contract(contract)
            if qualified:
                self._contracts[sym] = qualified
                # Fetch min tick
                details = await self._broker.get_contract_details(qualified)
                min_tick = details.minTick if details and details.minTick > 0 else 0.01
                self._min_ticks[sym] = min_tick
                logger.info("Contract qualified: %s (minTick=%.4f)", sym, min_tick)
            else:
                logger.warning("Failed to qualify %s — using default", sym)
                self._contracts[sym] = contract
                self._min_ticks[sym] = 0.01

        # Subscribe market data
        self._feed.subscribe(symbols, self._contracts)

        # Register contracts with order manager
        for sym in symbols:
            self._order_mgr.set_contract(sym, self._contracts[sym], self._min_ticks[sym])

        # Brief wait for initial quotes
        await asyncio.sleep(2)
        logger.info("PREP complete — waiting for market open.")

    async def _or_recording_phase(self) -> None:
        """Record the opening range — no entries."""
        self._phase = Phase.OR_RECORDING
        logger.info("=== OPENING RANGE RECORDING ===")

        or_end = self._parse_schedule_time(self._cfg.schedule.or_end_time)
        live_params = self._ol.get_params()

        while not self._shutdown_requested:
            now = datetime.now(self._tz)
            if now >= or_end:
                break
            self._check_circuit_breaker()
            self._update_dashboard()
            await asyncio.sleep(1)

        # Finalise bars and set opening ranges
        bar_ts = datetime.now(timezone.utc)
        for sym in self._cfg.watchlist.symbols:
            self._feed.finalize_bar(sym, bar_ts)
            self._feed.set_opening_range(sym)
            sd = self._feed.get(sym)
            if sd and sd.or_complete:
                logger.info("OR set: %s H=%.2f L=%.2f", sym, sd.or_high, sd.or_low)
            self._signal_states[sym] = "WATCH"

        logger.info("Opening range recording complete.")

    async def _trading_phase(self) -> None:
        """Main trading loop — scan signals, submit brackets, monitor."""
        self._phase = Phase.TRADING
        logger.info("=== TRADING PHASE ===")

        cutoff = self._parse_schedule_time(self._cfg.schedule.trading_cutoff)
        bar_interval_sec = self._ol.get_params().or_minutes * 60
        next_bar_time = datetime.now(self._tz) + timedelta(seconds=bar_interval_sec)
        last_signal_scan = 0.0
        last_pnl_snapshot = time.monotonic()
        pnl_snap_interval = 60  # seconds

        while not self._shutdown_requested:
            now_tz = datetime.now(self._tz)
            now_mono = time.monotonic()

            # ---- Check cutoff ----
            if now_tz >= cutoff:
                logger.info("Trading cutoff reached (%s)", self._cfg.schedule.trading_cutoff)
                break

            # ---- Circuit breaker check ----
            if self._check_circuit_breaker():
                await self._order_mgr.flatten_all("circuit_breaker")
                break

            # ---- Data staleness check ----
            stale_threshold = self._cfg.risk.circuit_breaker.data_feed_stale_sec
            for sym in self._cfg.watchlist.symbols:
                if self._feed.is_stale(sym, stale_threshold):
                    logger.warning("Data stale for %s", sym)
                    self._risk.trip_circuit_breaker(f"data_feed_stale: {sym}")

            # ---- Finalize bars every N minutes ----
            if now_tz >= next_bar_time:
                bar_ts = datetime.now(timezone.utc)
                for sym in self._cfg.watchlist.symbols:
                    self._feed.finalize_bar(sym, bar_ts)
                bar_interval_sec = self._ol.get_params().or_minutes * 60
                next_bar_time = now_tz + timedelta(seconds=bar_interval_sec)

            # ---- Signal scan (every 5 seconds) ----
            if now_mono - last_signal_scan >= 5:
                last_signal_scan = now_mono
                await self._scan_and_enter()

            # ---- Monitor open orders ----
            current_prices = {
                sym: (self._feed.get(sym).last_price if self._feed.get(sym) else 0.0)
                for sym in self._contracts
            }
            await self._order_mgr.monitor(current_prices)

            # ---- PnL snapshots ----
            if now_mono - last_pnl_snapshot >= pnl_snap_interval:
                last_pnl_snapshot = now_mono
                self._save_pnl_snapshot()

            # ---- Dashboard update ----
            self._update_dashboard()

            await asyncio.sleep(1)

        logger.info("Trading phase ended.")

    async def _wind_down_phase(self) -> None:
        """Wait for open positions to close naturally, then force-flatten."""
        self._phase = Phase.WIND_DOWN
        logger.info("=== WIND DOWN ===")

        flatten_at = self._parse_schedule_time(self._cfg.schedule.eod_flatten_time)

        while not self._shutdown_requested:
            now_tz = datetime.now(self._tz)
            open_trades = self._order_mgr.get_open_trades()

            if not open_trades:
                logger.info("All positions closed naturally.")
                break
            if now_tz >= flatten_at:
                logger.info("EOD flatten time reached — forcing close.")
                await self._order_mgr.flatten_all("eod_flatten")
                break

            current_prices = {
                sym: (self._feed.get(sym).last_price if self._feed.get(sym) else 0.0)
                for sym in self._contracts
            }
            await self._order_mgr.monitor(current_prices)
            self._update_dashboard()
            await asyncio.sleep(2)

        self._phase = Phase.DONE

    async def _shutdown(self) -> None:
        """Graceful shutdown: flatten, disconnect, generate report."""
        logger.info("Shutting down …")
        self._dashboard.stop()

        if not self._dry_run:
            try:
                await self._order_mgr.flatten_all("shutdown")
            except Exception as exc:
                logger.error("Flatten during shutdown failed: %s", exc)

            try:
                await self._broker.disconnect()
            except Exception:
                pass

        # Finalise run record
        self._storage.update_run_end(
            self._run_id, datetime.now(timezone.utc).isoformat()
        )
        self._save_pnl_snapshot()

        # Generate EOD report
        try:
            report_dir = self._reporter.generate_all(
                self._run_id, self._date_str,
                ol_session_log=self._ol.get_session_log(),
            )
            logger.info("EOD report: %s", report_dir)
            print(f"\nEOD report generated: {report_dir}")
        except Exception as exc:
            logger.error("EOD report generation failed: %s", exc)

        logger.info("Agent shutdown complete. Run ID: %s", self._run_id)
        print(f"Run complete. ID: {self._run_id}")

    # ------------------------------------------------------------------
    # Signal scan & entry
    # ------------------------------------------------------------------

    async def _scan_and_enter(self) -> None:
        """Scan all symbols for signals and submit brackets if approved."""
        live_params = self._ol.get_params()
        banned = set(live_params.symbol_banlist.keys())
        symbols = [s for s in self._cfg.watchlist.symbols if s != "SPY"]  # SPY = benchmark only

        signals = self._signals.scan_all(
            symbols,
            live_or_minutes=live_params.or_minutes,
            live_vwap_strength=live_params.vwap_filter_strength,
            banned_symbols=banned,
        )

        # Sort by conviction score descending
        signals.sort(key=lambda s: s.score, reverse=True)

        for sig in signals:
            if sig.symbol in self._order_mgr.get_open_trades():
                continue  # already have a position in this symbol

            # Size the trade
            qty = self._risk.compute_position_size(
                sig.entry_price,
                sig.stop_price,
                multiplier=live_params.position_size_multiplier,
            )
            if qty < 1:
                log_decision(
                    self._app_logger,
                    symbol=sig.symbol, action="SKIP",
                    rationale=f"qty=0 after sizing (entry={sig.entry_price:.2f} stop={sig.stop_price:.2f})",
                    market_snapshot=sig.snapshot,
                    risk_checks={"qty_check": "fail"},
                )
                continue

            sig.qty = qty

            # Risk approval
            approved, reason = self._risk.approve_entry(
                sig.symbol, "BUY" if sig.action == "ENTER_LONG" else "SELL",
                sig.entry_price, sig.stop_price, qty,
            )

            snap = self._feed.get_snapshot(sig.symbol)
            risk_checks = {"approved": approved, "reason": reason, "qty": qty}

            if not approved:
                log_decision(
                    self._app_logger,
                    symbol=sig.symbol, action="SKIP",
                    rationale=f"risk_veto: {reason}",
                    market_snapshot=snap, risk_checks=risk_checks,
                )
                self._storage.insert_decision(DecisionRecord(
                    run_id=self._run_id,
                    ts_utc=datetime.now(timezone.utc).isoformat(),
                    ts_local=datetime.now(self._tz).isoformat(),
                    symbol=sig.symbol, action="SKIP",
                    rationale=f"risk_veto: {reason}",
                    market_snapshot=json.dumps(snap),
                    risk_checks=json.dumps(risk_checks),
                    params_snapshot=json.dumps(self._ol.get_params().__dict__),
                ))
                continue

            action = sig.action
            log_decision(
                self._app_logger,
                symbol=sig.symbol, action=action,
                rationale=sig.rationale,
                market_snapshot=snap, risk_checks=risk_checks,
                score=sig.score,
            )
            self._storage.insert_decision(DecisionRecord(
                run_id=self._run_id,
                ts_utc=datetime.now(timezone.utc).isoformat(),
                ts_local=datetime.now(self._tz).isoformat(),
                symbol=sig.symbol, action=action,
                rationale=sig.rationale,
                market_snapshot=json.dumps(snap),
                risk_checks=json.dumps(risk_checks),
                params_snapshot=json.dumps({"position_size_multiplier": live_params.position_size_multiplier}),
            ))

            self._signal_states[sig.symbol] = "LONG!" if sig.action == "ENTER_LONG" else "SHORT!"

            ot = await self._order_mgr.submit_bracket(sig)
            if ot:
                logger.info("Bracket submitted for %s qty=%d", sig.symbol, qty)
            else:
                logger.error("Bracket submission failed for %s", sig.symbol)

            # Only one entry per scan cycle
            break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_circuit_breaker(self) -> bool:
        """Returns True if circuit breaker is tripped."""
        if self._broker.circuit_breaker.is_tripped:
            reason = self._broker.circuit_breaker.reason
            self._risk.trip_circuit_breaker(f"broker_circuit: {reason}")

        if self._risk.is_circuit_broken():
            reason = self._risk.get_daily_stats().get("circuit_reason", "unknown")
            logger.critical("Circuit breaker active: %s", reason)
            log_decision(
                self._app_logger,
                symbol="ALL", action="FLATTEN",
                rationale=f"circuit_breaker: {reason}",
                market_snapshot={}, risk_checks={"circuit_broken": True},
            )
            return True
        return False

    def _parse_schedule_time(self, time_str: str) -> datetime:
        """Parse HH:MM schedule time into a timezone-aware datetime for today."""
        h, m = map(int, time_str.split(":"))
        now = datetime.now(self._tz)
        return now.replace(hour=h, minute=m, second=0, microsecond=0)

    async def _wait_for_phase(self, phase: str, start_time: str) -> None:
        """Sleep until start_time arrives."""
        target = self._parse_schedule_time(start_time)
        now = datetime.now(self._tz)
        if now >= target:
            return

        wait_sec = (target - now).total_seconds()
        logger.info(
            "Waiting %.0f seconds until %s for phase %s",
            wait_sec, start_time, phase,
        )
        self._phase = Phase.WAITING
        self._update_dashboard()

        # Sleep in 1-second chunks so dashboard stays live and Ctrl-C works
        while not self._shutdown_requested:
            now = datetime.now(self._tz)
            if now >= target:
                break
            self._update_dashboard()
            await asyncio.sleep(1)

    def _save_pnl_snapshot(self) -> None:
        stats = self._risk.get_daily_stats()
        self._storage.insert_pnl_snapshot(PnlSnapshot(
            run_id=self._run_id,
            ts=datetime.now(timezone.utc).isoformat(),
            realized_pnl=stats["realized_pnl"],
            unrealized_pnl=stats["unrealized_pnl"],
            total_pnl=stats["total_pnl"],
            trades_count=stats["trades_today"],
            daily_loss_remaining=stats["daily_loss_remaining"],
        ))

    def _update_dashboard(self) -> None:
        stats = self._risk.get_daily_stats()
        live_params = self._ol.get_params()

        # Build watchlist entries
        wl_entries: list[WatchlistEntry] = []
        for sym in self._cfg.watchlist.symbols:
            sd = self._feed.get(sym)
            if sd is None:
                wl_entries.append(WatchlistEntry(symbol=sym))
                continue

            state = self._signal_states.get(sym, "WAIT")
            if sym in live_params.symbol_banlist:
                state = "BANNED"
            elif self._phase == Phase.OR_RECORDING:
                state = "RECORDING"
            elif not sd.or_complete and self._phase == Phase.TRADING:
                state = "WAIT"

            wl_entries.append(WatchlistEntry(
                symbol=sym,
                price=sd.last_price,
                vwap=sd.vwap,
                or_high=sd.or_high,
                or_low=sd.or_low,
                spread_bps=sd.spread_bps,
                signal_state=state,
                or_complete=sd.or_complete,
            ))

        # Build position entries
        pos_entries: list[PositionEntry] = []
        for p in self._order_mgr.get_open_position_info():
            sd = self._feed.get(p["symbol"])
            cur_price = sd.last_price if sd else 0.0
            side = p.get("side", "BUY")
            entry = p.get("entry_price", 0.0)
            qty = p.get("entry_filled", p.get("qty", 0))
            if side == "BUY":
                upnl = (cur_price - entry) * qty
            else:
                upnl = (entry - cur_price) * qty

            pos_entries.append(PositionEntry(
                symbol=p["symbol"],
                side=side,
                qty=qty,
                entry_price=entry,
                stop_price=p.get("stop", 0.0),
                tp1_price=p.get("tp1", 0.0),
                tp2_price=p.get("tp2", 0.0),
                current_price=cur_price,
                unrealized_pnl=round(upnl, 2),
            ))

        state = AgentState(
            connected=self._broker.is_connected() or self._dry_run,
            mode=self._mode_label,
            phase=self._phase,
            circuit_broken=self._risk.is_circuit_broken(),
            circuit_reason=stats.get("circuit_reason", ""),
            watchlist=wl_entries,
            positions=pos_entries,
            realized_pnl=stats["realized_pnl"],
            unrealized_pnl=stats["unrealized_pnl"],
            trades_today=stats["trades_today"],
            trades_remaining=stats["trades_remaining"],
            daily_loss_remaining=stats["daily_loss_remaining"],
            consecutive_losses=stats["consecutive_losses"],
            ol_size_mult=live_params.position_size_multiplier,
            ol_cooldown=live_params.cooldown_minutes,
            ol_vwap_str=live_params.vwap_filter_strength,
            ol_or_min=live_params.or_minutes,
            tz=self._cfg.schedule.timezone,
        )
        self._dashboard.update(state)

    def request_shutdown(self) -> None:
        self._shutdown_requested = True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="IBKR Trading Agent — Gap & Go / ORB with VWAP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config", default="config/settings.yaml",
        help="Path to settings.yaml (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate orders without sending to IBKR (overrides config)",
    )
    args = parser.parse_args()

    # Load and validate config
    try:
        cfg = load_config(args.config)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    agent = TradingAgent(cfg, dry_run_override=args.dry_run)

    # Handle signals for graceful shutdown
    loop = asyncio.new_event_loop()

    def _handle_signal(*_):
        print("\nShutdown requested …")
        agent.request_shutdown()
        loop.call_soon_threadsafe(loop.stop)

    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except Exception:
        pass  # Windows doesn't support all signals

    try:
        loop.run_until_complete(agent.run())
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt — shutting down.")
    finally:
        loop.close()


if __name__ == "__main__":
    main()
