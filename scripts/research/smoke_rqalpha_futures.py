"""Run the Phase 0 one-lot futures smoke test with RQAlpha Plus."""

from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd
from rqalpha.apis import order_to, update_universe
from rqalpha_plus import run_func

from china_cta.runtime_paths import get_rqalpha_bundle_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_PATH = get_rqalpha_bundle_path()
OUTPUT_ROOT = PROJECT_ROOT / "data" / "rqalpha_smoke"
RESULT_PATH = OUTPUT_ROOT / "result.pkl"
REPORT_PATH = OUTPUT_ROOT / "report"
CONTRACT = "AG1612"
START_DATE = "2016-06-01"
END_DATE = "2016-06-10"


def init(context) -> None:
    """Subscribe to one sample futures contract and submit only once."""

    context.contract = CONTRACT
    context.order_submitted = False
    update_universe(context.contract)


def handle_bar(context, bar_dict) -> None:
    """Set the target to one long contract on the first available bar."""

    if context.order_submitted:
        return
    order_to(context.contract, 1)
    context.order_submitted = True


def main() -> int:
    if not BUNDLE_PATH.is_dir():
        raise FileNotFoundError(f"RQAlpha sample bundle not found: {BUNDLE_PATH}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    result = run_func(
        init=init,
        handle_bar=handle_bar,
        config={
            "base": {
                "start_date": START_DATE,
                "end_date": END_DATE,
                "frequency": "1d",
                "accounts": {"future": 1_000_000},
                "data_bundle_path": str(BUNDLE_PATH),
                "margin_multiplier": 1,
                "futures_time_series_trading_parameters": False,
                "auto_update_bundle": False,
                "capital_gain_tax_rate": 0,
            },
            "extra": {"log_level": "info"},
            "mod": {
                "sys_progress": {"enabled": False},
                "sys_simulation": {
                    "enabled": True,
                    "matching_type": "current_bar",
                    "slippage_model": "PriceRatioSlippage",
                    "slippage": 0,
                },
                "sys_transaction_cost": {
                    "enabled": True,
                    "futures_commission_multiplier": 1,
                },
                "sys_analyser": {
                    "enabled": True,
                    "record": True,
                    "benchmark": None,
                    "output_file": str(RESULT_PATH),
                    "report_save_path": str(REPORT_PATH),
                    "plot": False,
                },
            },
        },
    )

    if not isinstance(result, dict):
        raise RuntimeError("RQAlpha Plus returned no analyser result")

    if not RESULT_PATH.is_file():
        raise RuntimeError(f"RQAlpha Plus did not save its result: {RESULT_PATH}")
    with RESULT_PATH.open("rb") as result_file:
        result = pickle.load(result_file)
    if not isinstance(result, dict):
        raise RuntimeError("RQAlpha Plus result pickle does not contain a dictionary")

    trades = result.get("trades")
    portfolio = result.get("portfolio")
    if not isinstance(trades, pd.DataFrame) or trades.empty:
        raise RuntimeError("The one-lot futures order produced no trade")
    if not isinstance(portfolio, pd.DataFrame) or portfolio.empty:
        raise RuntimeError("RQAlpha Plus returned no portfolio history")

    contract_trades = trades.loc[trades["order_book_id"].eq(CONTRACT)]
    if contract_trades.empty:
        raise RuntimeError(f"No trade was recorded for {CONTRACT}")

    quantity_column = next(
        (name for name in ("last_quantity", "quantity") if name in trades.columns),
        None,
    )
    if quantity_column is None:
        raise RuntimeError("Trade result has no recognizable quantity column")
    first_quantity = int(contract_trades.iloc[0][quantity_column])
    if abs(first_quantity) != 1:
        raise RuntimeError(f"Expected a one-lot fill, received {first_quantity}")

    nav_column = next(
        (name for name in ("unit_net_value",) if name in portfolio.columns),
        None,
    )
    final_nav = (
        float(portfolio.iloc[-1][nav_column]) if nav_column is not None else float("nan")
    )

    print("RQAlpha Plus one-lot futures smoke test succeeded!")
    print(f"Contract: {CONTRACT}")
    print(f"Date range: {START_DATE} to {END_DATE}")
    print(f"Filled quantity: {first_quantity}")
    print(f"Trade rows: {len(contract_trades)}")
    print(f"Portfolio rows: {len(portfolio)}")
    print(f"Final unit NAV: {final_nav:.8f}")
    print(f"Result pickle: {RESULT_PATH}")
    print(f"CSV report: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
