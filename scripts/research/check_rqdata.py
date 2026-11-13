"""Connect to RQData and fetch one recent rebar-futures daily bar."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from china_cta.data.rqdata_adapter import (  # noqa: E402
    RQDataAdapter,
    RQDataAdapterError,
    RQDataConfig,
)


def main() -> int:
    config = RQDataConfig.from_environment()
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    adapter = RQDataAdapter(config)

    try:
        adapter.connect(lazy=False)
        trading_dates = adapter.get_trading_calendar(start_date, end_date)
        if trading_dates.empty:
            print("RQData connected, but no recent trading dates were returned.")
            return 1

        completed_dates = [
            trading_date
            for trading_date in trading_dates
            if trading_date.date() < end_date
        ]
        if not completed_dates:
            print("RQData connected, but no completed trading day was found.")
            return 1

        # Today's daily bar may not exist until after settlement.  Using the
        # previous trading day makes this connectivity check deterministic.
        latest_date = completed_dates[-1]
        dominant = adapter.get_dominant_map(
            "RB", latest_date, latest_date
        )
        if dominant is None or dominant.empty:
            print(f"No RB dominant contract was found for {latest_date.date()}.")
            return 1

        contract = str(dominant.iloc[-1]["dominant_order_book_id"])
        bars = adapter.get_bars(contract, latest_date, latest_date)
    except RQDataAdapterError as exc:
        print(f"RQData check failed: {exc}")
        return 1
    except Exception as exc:
        print(f"RQData dominant-contract query failed: {exc}")
        return 1

    print("RQData connection and data query succeeded!")
    print(f"Latest trading date: {latest_date.date()}")
    print(f"RB dominant contract: {contract}")
    print(bars.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
