"""
Broker connectivity — wraps ib_insync with reconnect logic and circuit breaker.

Supports both TWS and IB Gateway. Handles:
  - Initial connection with exponential backoff retry
  - Automatic reconnect on disconnect events
  - Market data type fallback (real-time → delayed)
  - Circuit breaker: data staleness, order rejects, latency
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from ib_insync import IB, Contract, ContractDetails, Stock, Ticker

from .config_loader import BrokerConfig, CircuitBreakerConfig
from .storage import ErrorRecord, Storage

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Tracks conditions that warrant halting trading."""

    def __init__(self, cfg: CircuitBreakerConfig):
        self._cfg = cfg
        self._tripped = False
        self._reason = ""
        self._reject_times: deque[float] = deque()

    def trip(self, reason: str) -> None:
        if not self._tripped:
            self._tripped = True
            self._reason = reason
            logger.critical("CIRCUIT BREAKER TRIPPED: %s", reason)

    def reset(self) -> None:
        self._tripped = False
        self._reason = ""
        self._reject_times.clear()

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def reason(self) -> str:
        return self._reason

    def record_order_reject(self) -> None:
        now = time.monotonic()
        self._reject_times.append(now)
        # Prune outside window
        cutoff = now - self._cfg.order_reject_window_sec
        while self._reject_times and self._reject_times[0] < cutoff:
            self._reject_times.popleft()
        if len(self._reject_times) >= self._cfg.order_reject_count:
            self.trip(
                f"{len(self._reject_times)} order rejects in "
                f"{self._cfg.order_reject_window_sec}s window"
            )

    def check_latency(self, latency_sec: float) -> None:
        if latency_sec > self._cfg.order_latency_sec:
            self.trip(
                f"Order latency {latency_sec:.2f}s exceeds "
                f"threshold {self._cfg.order_latency_sec}s"
            )


class BrokerManager:
    """
    Manages ib_insync connection lifecycle.

    Usage:
        bm = BrokerManager(config, storage)
        connected = await bm.connect()
        ticker = bm.req_market_data(contract)
    """

    def __init__(self, cfg: BrokerConfig, cb_cfg: CircuitBreakerConfig, storage: Storage):
        self._cfg = cfg
        self._storage = storage
        self._run_id: str = ""
        self.ib = IB()
        self.circuit_breaker = CircuitBreaker(cb_cfg)
        self._market_data_type: int = 1    # 1=live, 3=delayed
        self._reconnecting = False
        self._should_reconnect = True

        # Register ib_insync event callbacks
        self.ib.disconnectedEvent += self._on_disconnect
        self.ib.errorEvent += self._on_error

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """
        Attempt connection with exponential backoff.
        Returns True on success, False after all retries exhausted.
        """
        attempts = self._cfg.reconnect_attempts
        backoff = self._cfg.reconnect_backoff_sec

        for attempt in range(1, attempts + 1):
            try:
                logger.info(
                    "Connecting to IBKR %s:%d (clientId=%d) — attempt %d/%d",
                    self._cfg.host, self._cfg.port, self._cfg.client_id,
                    attempt, attempts,
                )
                await self.ib.connectAsync(
                    host=self._cfg.host,
                    port=self._cfg.port,
                    clientId=self._cfg.client_id,
                    timeout=self._cfg.timeout_sec,
                )
                logger.info("Connected to IBKR successfully.")
                await self._request_market_data_type()
                return True
            except Exception as exc:
                logger.warning("Connection attempt %d failed: %s", attempt, exc)
                if attempt < attempts:
                    sleep_sec = backoff * (2 ** (attempt - 1))
                    logger.info("Retrying in %.1fs …", sleep_sec)
                    await asyncio.sleep(sleep_sec)

        logger.error("All %d connection attempts failed.", attempts)
        return False

    async def disconnect(self) -> None:
        self._should_reconnect = False
        if self.ib.isConnected():
            self.ib.disconnect()
            await asyncio.sleep(0.5)

    def is_connected(self) -> bool:
        return self.ib.isConnected()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def _request_market_data_type(self) -> None:
        """Try real-time first; fall back to delayed if subscription missing."""
        try:
            self.ib.reqMarketDataType(1)  # real-time
            await asyncio.sleep(0.2)
            self._market_data_type = 1
            logger.info("Market data type: REAL-TIME")
        except Exception:
            logger.warning("Real-time data unavailable, requesting DELAYED (type 3).")
            self.ib.reqMarketDataType(3)
            self._market_data_type = 3

    def req_market_data(self, contract: Contract, snapshot: bool = False) -> Ticker:
        """
        Subscribe to market data for *contract*.
        Automatically uses the correct data type (real-time or delayed).
        """
        return self.ib.reqMktData(
            contract,
            genericTickList="",
            snapshot=snapshot,
            regulatorySnapshot=False,
        )

    def cancel_market_data(self, contract: Contract) -> None:
        try:
            self.ib.cancelMktData(contract)
        except Exception as exc:
            logger.debug("cancelMktData failed: %s", exc)

    @property
    def using_delayed_data(self) -> bool:
        return self._market_data_type != 1

    # ------------------------------------------------------------------
    # Contract details
    # ------------------------------------------------------------------

    async def get_contract_details(self, contract: Contract) -> Optional[ContractDetails]:
        """Fetch contract details (minTick, trading hours, etc.)."""
        try:
            details = await self.ib.reqContractDetailsAsync(contract)
            if details:
                return details[0]
        except Exception as exc:
            logger.error("reqContractDetails failed for %s: %s", contract.symbol, exc)
        return None

    async def qualify_contract(self, contract: Contract) -> Optional[Contract]:
        """Qualify contract to fill in conId and exchange details."""
        try:
            qualified = await self.ib.qualifyContractsAsync(contract)
            if qualified:
                return qualified[0]
        except Exception as exc:
            logger.error("qualifyContracts failed for %s: %s", contract.symbol, exc)
        return None

    def make_stock(self, symbol: str, exchange: str = "SMART",
                   currency: str = "USD") -> Stock:
        return Stock(symbol, exchange, currency)

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account_values(self) -> dict[str, str]:
        vals = {v.tag: v.value for v in self.ib.accountValues()}
        return vals

    def get_net_liquidation(self) -> float:
        vals = self.get_account_values()
        try:
            return float(vals.get("NetLiquidation", 0))
        except (ValueError, TypeError):
            return 0.0

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_disconnect(self) -> None:
        logger.warning("IBKR disconnected.")
        if self._should_reconnect and not self._reconnecting:
            asyncio.ensure_future(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        self._reconnecting = True
        backoff = self._cfg.reconnect_backoff_sec
        for attempt in range(1, self._cfg.reconnect_attempts + 1):
            await asyncio.sleep(backoff * (2 ** (attempt - 1)))
            if not self._should_reconnect:
                break
            try:
                logger.info("Reconnect attempt %d …", attempt)
                await self.ib.connectAsync(
                    host=self._cfg.host,
                    port=self._cfg.port,
                    clientId=self._cfg.client_id,
                    timeout=self._cfg.timeout_sec,
                )
                logger.info("Reconnected successfully.")
                await self._request_market_data_type()
                self._reconnecting = False
                return
            except Exception as exc:
                logger.warning("Reconnect attempt %d failed: %s", attempt, exc)

        logger.critical("Could not reconnect to IBKR after %d attempts.",
                        self._cfg.reconnect_attempts)
        self.circuit_breaker.trip("Failed to reconnect to IBKR")
        self._reconnecting = False

    def _on_error(self, req_id: int, error_code: int, error_string: str,
                  contract: Optional[Contract]) -> None:
        symbol = contract.symbol if contract else "N/A"

        # IBKR informational codes (not real errors)
        informational = {2104, 2106, 2158, 2107, 2108, 2103, 10167, 10182}
        if error_code in informational:
            logger.debug("IBKR info [%d] %s (%s)", error_code, error_string, symbol)
            return

        # Order rejects
        if error_code in {201, 202, 110, 104}:
            logger.warning("Order rejected [%d] %s (%s)", error_code, error_string, symbol)
            self.circuit_breaker.record_order_reject()
        else:
            logger.error("IBKR error [%d] %s (%s)", error_code, error_string, symbol)

        # Persist to DB
        if self._run_id:
            try:
                self._storage.insert_error(ErrorRecord(
                    run_id=self._run_id,
                    ts=datetime.now(timezone.utc).isoformat(),
                    module="broker",
                    error_type=f"IBKR_{error_code}",
                    message=f"[{error_code}] {error_string} (symbol={symbol})",
                    traceback="",
                ))
            except Exception:
                pass
