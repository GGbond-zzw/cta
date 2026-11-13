"""Re-render the comparison chart of a finished portfolio run from its saved CSVs.

The chart is produced by ``scripts/50_backtest_portfolio.py`` in the same run; this
script rebuilds it from ``sleeve_daily_net_return.csv`` and the combo
``daily_net_return.csv`` files, so a window or rebase date can be changed without
re-running the (slow) factor rebuild.

Example
-------
    python scripts/60_render_run_chart.py --results-dir results/final_4f --start 2025-01-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "results" / "final_4f"
DEFAULT_WINDOW = ("2016-01-04", "2025-12-31")
FACTORS = (
    "fixed_maturity_carry_90_180d",
    "xsmom_252_21",
    "oi_participation_trend_60d",
    "historical_skewness_252d",
)
COMBOS = ("ew4_fixed_carry", "ew4_fixed_carry_vol20")


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "portfolio_backtest", HERE / "50_backtest_portfolio.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["portfolio_backtest"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description="re-render a finished run's comparison chart")
    parser.add_argument("--results-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--start", default=DEFAULT_WINDOW[0])
    parser.add_argument("--end", default=DEFAULT_WINDOW[1])
    args = parser.parse_args()

    out_dir = Path(args.results_dir)
    window = (args.start, args.end)
    module = _load_module()
    sleeves = pd.read_csv(out_dir / "sleeve_daily_net_return.csv", index_col=0)
    sleeves.index = pd.to_datetime(sleeves.index)
    combos = {}
    for name in COMBOS:
        daily = pd.read_csv(out_dir / name / "daily_net_return.csv", index_col=0)["daily_net_return"]
        daily.index = pd.to_datetime(daily.index)
        combos[name] = {"daily": daily}
    target = module._plot_comparison(
        combos=combos,
        sleeve_equity=sleeves,
        factors=FACTORS,
        out_dir=out_dir,
        window=window,
    )
    print("wrote", target)
    return 0 if target else 1


if __name__ == "__main__":
    raise SystemExit(main())
