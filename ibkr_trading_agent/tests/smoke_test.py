"""
Smoke test — connect to IBKR, pull a SPY quote, and exit cleanly.

Requirements:
  - IB Gateway or TWS running in paper-trading mode
  - API access enabled in TWS/Gateway settings

Usage:
  python tests/smoke_test.py
  python tests/smoke_test.py --host 127.0.0.1 --port 7497 --client-id 99 --symbol SPY
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
import time
from datetime import datetime, timezone


async def run_smoke_test(
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 99,
    symbol: str = "SPY",
    timeout_sec: int = 15,
) -> bool:
    """
    Connect to IBKR, subscribe to a market data quote for *symbol*,
    verify bid and ask are valid, then disconnect.

    Returns True on success, False on failure.
    """
    try:
        from ib_insync import IB, Stock
    except ImportError:
        print("ERROR: ib_insync not installed. Run: pip install ib_insync")
        return False

    ib = IB()
    success = False

    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Connecting to {host}:{port} (clientId={client_id}) …")
        await ib.connectAsync(host=host, port=port, clientId=client_id, timeout=timeout_sec)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Connected ✓")

        # Request real-time data; fall back to delayed if not subscribed
        ib.reqMarketDataType(1)  # try real-time
        contract = Stock(symbol, "SMART", "USD")

        # Qualify the contract
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified:
            print(f"ERROR: Could not qualify contract for {symbol}")
            return False

        print(f"[{datetime.now().strftime('%H:%M:%S')}] Qualified {symbol} (conId={qualified[0].conId})")

        # Subscribe to market data
        ticker = ib.reqMktData(qualified[0], genericTickList="", snapshot=False)

        # Wait up to 10 seconds for a valid quote
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            bid = ticker.bid
            ask = ticker.ask
            last = ticker.last

            if (
                bid and not math.isnan(bid) and bid > 0
                and ask and not math.isnan(ask) and ask > 0
            ):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {symbol} quote received:")
                print(f"  Bid:  ${bid:.2f}")
                print(f"  Ask:  ${ask:.2f}")
                print(f"  Last: ${last:.2f}" if last and not math.isnan(last) else "  Last: n/a")
                print(f"  Spread: {(ask - bid) / ((ask + bid) / 2) * 10000:.1f} bps")
                success = True
                break
            else:
                print(
                    f"  Waiting for quote … bid={bid} ask={ask}",
                    end="\r",
                )

        if not success:
            # Try delayed data
            print("\nReal-time data unavailable. Requesting delayed data …")
            ib.reqMarketDataType(3)
            await asyncio.sleep(3)
            bid = ticker.bid
            ask = ticker.ask
            if bid and not math.isnan(bid) and bid > 0:
                print(f"  Delayed bid: ${bid:.2f}  ask: ${ask:.2f}")
                success = True
            else:
                print("ERROR: No quote received within timeout.")

    except Exception as exc:
        print(f"\nERROR: {exc}")
        return False
    finally:
        if ib.isConnected():
            ib.disconnect()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Disconnected.")

    if success:
        print(f"\n✓ Smoke test PASSED for {symbol}")
    else:
        print(f"\n✗ Smoke test FAILED for {symbol}")

    return success


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test: connect to IBKR and pull a quote."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497,
                        help="TWS paper=7497, TWS live=7496, Gateway paper=4002, Gateway live=4001")
    parser.add_argument("--client-id", type=int, default=99)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args()

    ok = asyncio.run(
        run_smoke_test(
            host=args.host,
            port=args.port,
            client_id=args.client_id,
            symbol=args.symbol,
            timeout_sec=args.timeout,
        )
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
