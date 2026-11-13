"""Check whether flipping a factor's signal yields exactly the mirrored Sharpe.

For each factor we rebuild the signal once, then run the canonical engine twice
(original and negated signal) and compare:

* ``sharpe_flipped`` vs ``-sharpe_original``
* the predicted gap, which comes from the fact that turning the signal around
  negates the gross return but *not* the turnover cost:
  ``r_flipped = -r_original - 2 * cost_daily``.
"""

from __future__ import annotations

import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))

from china_cta.factors import cta_catalog  # noqa: E402
from china_cta.research import bayesian_tuning as bt  # noqa: E402
from china_cta.research import fast_backtest as fb  # noqa: E402

INPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22"
FACTORS = ("receipt_mom_20", "ts_slope", "lowvol")

_INPUTS: dict[str, pd.DataFrame] | None = None


def _init_worker() -> None:
    global _INPUTS
    _INPUTS = bt.load_inputs(INPUT_DIR)


def _build(name: str) -> pd.DataFrame:
    assert _INPUTS is not None
    return cta_catalog.BUILDERS[name](_INPUTS)


def _run(name: str) -> dict[str, object]:
    assert _INPUTS is not None
    factor = _build(name)
    base = fb.run_fast_research_backtest(
        factor,
        _INPUTS["continuous_prices"],
        _INPUTS["universe"],
        execution_lag=bt.EXECUTION_LAG,
        cost_rate=bt.COST_RATE,
        execution_price_field="open",
        include_breakdowns=False,
    )
    flipped_factor = factor.copy()
    flipped_factor["raw_factor"] = -flipped_factor["raw_factor"]
    flipped_factor["signal"] = -flipped_factor["signal"]
    flipped = fb.run_fast_research_backtest(
        flipped_factor,
        _INPUTS["continuous_prices"],
        _INPUTS["universe"],
        execution_lag=bt.EXECUTION_LAG,
        cost_rate=bt.COST_RATE,
        execution_price_field="open",
        include_breakdowns=False,
    )
    base_daily = base["detail"].groupby("realization_date")["net_signal_return"].mean()
    flip_daily = flipped["detail"].groupby("realization_date")["net_signal_return"].mean()
    cost_daily = base["detail"].groupby("realization_date")["rough_cost"].mean()
    return {
        "name": name,
        "base": base["overall"].iloc[0].to_dict(),
        "flip": flipped["overall"].iloc[0].to_dict(),
        "base_daily": base_daily,
        "flip_daily": flip_daily,
        "cost_daily": cost_daily,
    }


def _stats(series: pd.Series) -> dict[str, float]:
    clean = series.dropna()
    vol = float(clean.std(ddof=1) * (252 ** 0.5))
    return {
        "sharpe": float(clean.mean() * 252 / vol) if vol > 0 else float("nan"),
        "annualized": float(clean.mean() * 252),
        "volatility": vol,
    }


def main() -> int:
    with ProcessPoolExecutor(max_workers=3, initializer=_init_worker) as pool:
        items = list(pool.map(_run, FACTORS))

    rows = []
    for item in items:
        name = item["name"]
        base = item["base"]
        flip = item["flip"]
        cost_daily = float(item["cost_daily"].mean())
        base_stats = _stats(item["base_daily"])
        flip_stats = _stats(item["flip_daily"])
        predicted = _stats(-item["base_daily"] - 2 * item["cost_daily"])
        rows.append(
            {
                "factor": name,
                "sharpe_original": base_stats["sharpe"],
                "sharpe_flipped": flip_stats["sharpe"],
                "minus_original": -base_stats["sharpe"],
                "gap_vs_mirror": flip_stats["sharpe"] + base_stats["sharpe"],
                "predicted_flip_sharpe": predicted["sharpe"],
                "ann_original": base_stats["annualized"],
                "ann_flipped": flip_stats["annualized"],
                "vol_original": base_stats["volatility"],
                "vol_flipped": flip_stats["volatility"],
                "mdd_original": float(base["max_drawdown"]),
                "mdd_flipped": float(flip["max_drawdown"]),
                "turnover_original": float(base["mean_turnover_proxy"]),
                "turnover_flipped": float(flip["mean_turnover_proxy"]),
                "daily_cost_bps": cost_daily * 1e4,
                "annual_cost_pct": cost_daily * 252 * 100,
                "overall_engine_flip_sharpe": float(flip["sharpe"]),
                "overall_engine_base_sharpe": float(base["sharpe"]),
            }
        )

    frame = pd.DataFrame(rows)
    frame.to_csv(
        PROJECT / "results" / "all_factors_open" / "flip_check.csv",
        index=False,
        float_format="%.17g",
    )
    display = frame[
        [
            "factor",
            "sharpe_original",
            "sharpe_flipped",
            "minus_original",
            "gap_vs_mirror",
            "predicted_flip_sharpe",
            "ann_original",
            "ann_flipped",
            "vol_original",
            "vol_flipped",
            "mdd_original",
            "mdd_flipped",
            "daily_cost_bps",
            "annual_cost_pct",
        ]
    ]
    print(display.to_string(index=False, float_format=lambda value: f"{value:.4f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
