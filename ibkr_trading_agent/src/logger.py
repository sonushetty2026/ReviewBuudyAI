"""
Structured logging — JSONL file per session + Rich console handler.

Every decision event is emitted as a single-line JSON object containing:
  timestamp_utc, timestamp_local, symbol, action, rationale,
  market_snapshot, risk_checks, and any extra kwargs.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import jsonlines


# ---------------------------------------------------------------------------
# Custom JSONL file handler
# ---------------------------------------------------------------------------

class JsonLinesHandler(logging.Handler):
    """Appends each log record as a JSON object on its own line."""

    def __init__(self, path: str):
        super().__init__()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._writer = jsonlines.open(path, mode="a", flush=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # The 'extra' dict is merged into the record's __dict__
            obj: dict = {}
            if hasattr(record, "json_payload"):
                obj = record.json_payload  # type: ignore[attr-defined]
            else:
                obj = {
                    "level": record.levelname,
                    "logger": record.name,
                    "message": self.format(record),
                }
            self._writer.write(obj)
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            self._writer.close()
        except Exception:
            pass
        super().close()


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_logging(log_dir: str, date_str: str, level: int = logging.INFO) -> logging.Logger:
    """
    Configure the root logger with:
      - A JSONL file handler writing to <log_dir>/<date_str>.jsonl
      - A Rich console handler for human-readable output

    Returns the root logger.
    """
    os.makedirs(log_dir, exist_ok=True)
    jsonl_path = os.path.join(log_dir, f"{date_str}.jsonl")

    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates on re-import
    root.handlers.clear()

    # JSONL file handler
    file_handler = JsonLinesHandler(jsonl_path)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Console handler (plain text, Rich-compatible)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)

    return root


# ---------------------------------------------------------------------------
# Decision logging helper
# ---------------------------------------------------------------------------

def log_decision(
    logger: logging.Logger,
    *,
    symbol: str,
    action: str,
    rationale: str,
    market_snapshot: dict,
    risk_checks: dict,
    ts_utc: Optional[str] = None,
    ts_local: Optional[str] = None,
    params_snapshot: Optional[dict] = None,
    **kwargs: Any,
) -> None:
    """
    Emit a structured JSONL decision event.

    action values: ENTER_LONG | ENTER_SHORT | SKIP | EXIT | FLATTEN | INFO
    """
    now_utc = datetime.now(timezone.utc)
    payload = {
        "event": "decision",
        "timestamp_utc": ts_utc or now_utc.isoformat(),
        "timestamp_local": ts_local or now_utc.astimezone().isoformat(),
        "symbol": symbol,
        "action": action,
        "rationale": rationale,
        "market_snapshot": market_snapshot,
        "risk_checks": risk_checks,
        "params_snapshot": params_snapshot or {},
        **kwargs,
    }

    record = logging.LogRecord(
        name="decision",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f"{action} {symbol}: {rationale}",
        args=(),
        exc_info=None,
    )
    record.json_payload = payload  # type: ignore[attr-defined]
    logger.handle(record)


def log_error(
    logger: logging.Logger,
    *,
    module: str,
    error_type: str,
    message: str,
    exc: Optional[Exception] = None,
) -> None:
    """Emit a structured error event."""
    payload = {
        "event": "error",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "module": module,
        "error_type": error_type,
        "message": message,
        "traceback": traceback.format_exc() if exc else "",
    }
    record = logging.LogRecord(
        name=f"error.{module}",
        level=logging.ERROR,
        pathname="",
        lineno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.json_payload = payload  # type: ignore[attr-defined]
    logger.handle(record)


def log_param_change(
    logger: logging.Logger,
    *,
    param: str,
    old_value: Any,
    new_value: Any,
    reason: str,
) -> None:
    """Emit a structured parameter-change event (online learning)."""
    payload = {
        "event": "param_change",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "param": param,
        "old_value": old_value,
        "new_value": new_value,
        "reason": reason,
    }
    record = logging.LogRecord(
        name="online_learning",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=f"param_change {param}: {old_value} → {new_value} ({reason})",
        args=(),
        exc_info=None,
    )
    record.json_payload = payload  # type: ignore[attr-defined]
    logger.handle(record)
