"""
SQLite-backed durable storage for all trading events.

Tables: runs, decisions, orders, fills, positions, pnl_snapshots, errors
"""

from __future__ import annotations

import json
import sqlite3
import traceback
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional


# ---------------------------------------------------------------------------
# Record dataclasses (lightweight DTOs)
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    run_id: str
    start_ts: str
    end_ts: str
    mode: str           # "paper" | "dry_run" | "live"
    config_snapshot: str  # JSON


@dataclass
class DecisionRecord:
    run_id: str
    ts_utc: str
    ts_local: str
    symbol: str
    action: str         # ENTER_LONG | ENTER_SHORT | SKIP | EXIT | FLATTEN
    rationale: str
    market_snapshot: str  # JSON
    risk_checks: str      # JSON
    params_snapshot: str  # JSON


@dataclass
class OrderRecord:
    run_id: str
    order_id: int
    symbol: str
    order_type: str     # entry | stop | take_profit_1 | take_profit_2
    action: str         # BUY | SELL
    qty: int
    limit_price: float
    status: str         # submitted | filled | partial | cancelled | rejected
    submitted_ts: str
    last_update_ts: str


@dataclass
class FillRecord:
    order_id: int
    exec_id: str
    fill_price: float
    fill_qty: int
    commission: float
    ts: str


@dataclass
class PositionRecord:
    run_id: str
    symbol: str
    entry_price: float
    qty: int
    stop_price: float
    tp1_price: float
    tp2_price: float
    open_ts: str
    close_ts: str
    realized_pnl: float
    r_multiple: float
    mae: float
    mfe: float


@dataclass
class PnlSnapshot:
    run_id: str
    ts: str
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    trades_count: int
    daily_loss_remaining: float


@dataclass
class ErrorRecord:
    run_id: str
    ts: str
    module: str
    error_type: str
    message: str
    traceback: str


# ---------------------------------------------------------------------------
# Storage class
# ---------------------------------------------------------------------------

class Storage:
    """Thread-safe (via connection-per-call) SQLite storage."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS runs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT    UNIQUE NOT NULL,
        start_ts        TEXT,
        end_ts          TEXT,
        mode            TEXT,
        config_snapshot TEXT
    );

    CREATE TABLE IF NOT EXISTS decisions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT,
        ts_utc          TEXT,
        ts_local        TEXT,
        symbol          TEXT,
        action          TEXT,
        rationale       TEXT,
        market_snapshot TEXT,
        risk_checks     TEXT,
        params_snapshot TEXT
    );

    CREATE TABLE IF NOT EXISTS orders (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id          TEXT,
        order_id        INTEGER,
        symbol          TEXT,
        order_type      TEXT,
        action          TEXT,
        qty             INTEGER,
        limit_price     REAL,
        status          TEXT,
        submitted_ts    TEXT,
        last_update_ts  TEXT,
        UNIQUE(run_id, order_id)
    );

    CREATE TABLE IF NOT EXISTS fills (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id    INTEGER,
        exec_id     TEXT    UNIQUE,
        fill_price  REAL,
        fill_qty    INTEGER,
        commission  REAL,
        ts          TEXT
    );

    CREATE TABLE IF NOT EXISTS positions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id       TEXT,
        symbol       TEXT,
        entry_price  REAL,
        qty          INTEGER,
        stop_price   REAL,
        tp1_price    REAL,
        tp2_price    REAL,
        open_ts      TEXT,
        close_ts     TEXT,
        realized_pnl REAL,
        r_multiple   REAL,
        mae          REAL,
        mfe          REAL
    );

    CREATE TABLE IF NOT EXISTS pnl_snapshots (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id               TEXT,
        ts                   TEXT,
        realized_pnl         REAL,
        unrealized_pnl       REAL,
        total_pnl            REAL,
        trades_count         INTEGER,
        daily_loss_remaining REAL
    );

    CREATE TABLE IF NOT EXISTS errors (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id     TEXT,
        ts         TEXT,
        module     TEXT,
        error_type TEXT,
        message    TEXT,
        traceback  TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_decisions_run   ON decisions(run_id);
    CREATE INDEX IF NOT EXISTS idx_orders_run      ON orders(run_id);
    CREATE INDEX IF NOT EXISTS idx_positions_run   ON positions(run_id);
    CREATE INDEX IF NOT EXISTS idx_pnl_run         ON pnl_snapshots(run_id);
    CREATE INDEX IF NOT EXISTS idx_errors_run      ON errors(run_id);
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _tx(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._tx() as conn:
            conn.executescript(self.SCHEMA)

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def insert_run(self, run: RunRecord) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO runs
                   (run_id, start_ts, end_ts, mode, config_snapshot)
                   VALUES (?, ?, ?, ?, ?)""",
                (run.run_id, run.start_ts, run.end_ts, run.mode, run.config_snapshot),
            )

    def update_run_end(self, run_id: str, end_ts: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE runs SET end_ts=? WHERE run_id=?", (end_ts, run_id)
            )

    def get_all_runs(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY start_ts").fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def insert_decision(self, dec: DecisionRecord) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO decisions
                   (run_id, ts_utc, ts_local, symbol, action, rationale,
                    market_snapshot, risk_checks, params_snapshot)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    dec.run_id, dec.ts_utc, dec.ts_local, dec.symbol,
                    dec.action, dec.rationale,
                    dec.market_snapshot, dec.risk_checks, dec.params_snapshot,
                ),
            )

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def upsert_order(self, order: OrderRecord) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO orders
                   (run_id, order_id, symbol, order_type, action, qty,
                    limit_price, status, submitted_ts, last_update_ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, order_id) DO UPDATE SET
                     status=excluded.status,
                     last_update_ts=excluded.last_update_ts""",
                (
                    order.run_id, order.order_id, order.symbol,
                    order.order_type, order.action, order.qty,
                    order.limit_price, order.status,
                    order.submitted_ts, order.last_update_ts,
                ),
            )

    def get_orders_for_run(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE run_id=? ORDER BY submitted_ts", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Fills
    # ------------------------------------------------------------------

    def insert_fill(self, fill: FillRecord) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO fills
                   (order_id, exec_id, fill_price, fill_qty, commission, ts)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    fill.order_id, fill.exec_id, fill.fill_price,
                    fill.fill_qty, fill.commission, fill.ts,
                ),
            )

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def insert_position(self, pos: PositionRecord) -> int:
        """Insert and return the new row id."""
        with self._tx() as conn:
            cur = conn.execute(
                """INSERT INTO positions
                   (run_id, symbol, entry_price, qty, stop_price, tp1_price, tp2_price,
                    open_ts, close_ts, realized_pnl, r_multiple, mae, mfe)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    pos.run_id, pos.symbol, pos.entry_price, pos.qty,
                    pos.stop_price, pos.tp1_price, pos.tp2_price,
                    pos.open_ts, pos.close_ts,
                    pos.realized_pnl, pos.r_multiple, pos.mae, pos.mfe,
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def update_position(self, row_id: int, **kwargs) -> None:
        if not kwargs:
            return
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [row_id]
        with self._tx() as conn:
            conn.execute(f"UPDATE positions SET {sets} WHERE id=?", vals)

    def get_positions_for_run(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE run_id=? ORDER BY open_ts", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_closed_positions_for_run(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM positions
                   WHERE run_id=? AND close_ts IS NOT NULL AND close_ts != ''
                   ORDER BY open_ts""",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_positions(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions ORDER BY open_ts"
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # PnL snapshots
    # ------------------------------------------------------------------

    def insert_pnl_snapshot(self, snap: PnlSnapshot) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO pnl_snapshots
                   (run_id, ts, realized_pnl, unrealized_pnl, total_pnl,
                    trades_count, daily_loss_remaining)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap.run_id, snap.ts, snap.realized_pnl,
                    snap.unrealized_pnl, snap.total_pnl,
                    snap.trades_count, snap.daily_loss_remaining,
                ),
            )

    def get_pnl_snapshots_for_run(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pnl_snapshots WHERE run_id=? ORDER BY ts", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------

    def insert_error(self, error: ErrorRecord) -> None:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO errors
                   (run_id, ts, module, error_type, message, traceback)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    error.run_id, error.ts, error.module,
                    error.error_type, error.message, error.traceback,
                ),
            )

    def get_errors_for_run(self, run_id: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM errors WHERE run_id=? ORDER BY ts", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]
