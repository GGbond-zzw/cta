"""Correlation matrices for the qualified CTA factors.

Rebuilds every factor with its 300-trial optimal parameters, derives the daily
portfolio net-return series the backtest actually uses (mean of available
instrument net_signal_return per realization_date), and reports:

* Pearson (and Spearman) correlation of daily net returns, 2016-2025
* Pearson correlation of daily net returns, 2025 only
* Average cross-sectional Spearman correlation of the raw factor signals

Usage:
    python factor_correlation.py --processes 3
    python factor_correlation.py --tuned-dir results/tuning/qualified5_300 \
        --out-dir results/tuning/factor_correlation_5f
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from china_cta.research import bayesian_tuning as bt  # noqa: E402
from china_cta.research.fast_backtest import run_fast_research_backtest  # noqa: E402

INPUT_DIR = PROJECT / "data" / "research_inputs" / "cta_alpha22"
TUNED_DIR = PROJECT / "results" / "tuning" / "qualified4_300"
OUT_DIR = PROJECT / "results" / "tuning" / "factor_correlation_4f"

_INPUTS: dict[str, pd.DataFrame] | None = None


def _init_worker() -> None:
    global _INPUTS
    _INPUTS = bt.load_inputs(INPUT_DIR)


def _factor_names(tuned_dir: Path) -> list[str]:
    manifest = json.loads((tuned_dir / "manifest.json").read_text(encoding="utf-8"))
    return list(manifest["factors"])


def _one_factor(job: tuple[str, str]) -> dict[str, object]:
    name, tuned_dir = job
    assert _INPUTS is not None
    payload = json.loads(
        (Path(tuned_dir) / name / "best_params.json").read_text(encoding="utf-8")
    )
    params = payload["best_params"]
    factor = bt.build_factor(name, params, _INPUTS)
    result = run_fast_research_backtest(
        factor,
        _INPUTS["continuous_prices"],
        _INPUTS["universe"],
        execution_lag=bt.EXECUTION_LAG,
        cost_rate=bt.COST_RATE,
        include_breakdowns=False,
    )
    detail = result["detail"]
    daily = detail.groupby("realization_date", sort=True)["net_signal_return"].mean()
    daily.index = pd.to_datetime(daily.index)
    daily = daily.loc[daily.index.notna()]

    signals = detail.loc[:, ["signal_date", "instrument", "signal"]].copy()
    signals["signal_date"] = pd.to_datetime(signals["signal_date"])
    pivot = signals.pivot_table(
        index="signal_date", columns="instrument", values="signal", aggfunc="mean"
    )
    returns = detail.groupby("realization_date", sort=True)["net_signal_return"].mean()
    turnover = detail.groupby("signal_date", sort=True)["turnover_proxy"].mean()
    return {
        "name": name,
        "params": params,
        "daily": daily,
        "pivot": pivot,
        "turnover": float(turnover.mean()),
        "sharpe": float(payload["best_train"]["sharpe"]),
    }


def _rank_corr(a: np.ndarray, b: np.ndarray) -> float:
    ra = rankdata(a)
    rb = rankdata(b)
    ra = ra - ra.mean()
    rb = rb - rb.mean()
    denom = float(np.sqrt((ra * ra).sum() * (rb * rb).sum()))
    if denom == 0.0:
        return np.nan
    return float((ra * rb).sum() / denom)


def _signal_correlation(
    p1: pd.DataFrame, p2: pd.DataFrame, min_names: int = 8
) -> tuple[float, int]:
    dates = p1.index.intersection(p2.index)
    names = p1.columns.intersection(p2.columns)
    a = p1.reindex(index=dates, columns=names).to_numpy(dtype=float)
    b = p2.reindex(index=dates, columns=names).to_numpy(dtype=float)
    values: list[float] = []
    for i in range(a.shape[0]):
        mask = ~np.isnan(a[i]) & ~np.isnan(b[i])
        if mask.sum() < min_names:
            continue
        value = _rank_corr(a[i][mask], b[i][mask])
        if np.isfinite(value):
            values.append(value)
    if not values:
        return np.nan, 0
    return float(np.mean(values)), len(values)


def _pivot_to_matrix(items: list[dict[str, object]], key: str) -> pd.DataFrame:
    series = {item["name"]: item[key] for item in items}
    return pd.DataFrame(series)


def _corr_block(
    frame: pd.DataFrame, start: str, end: str, min_periods: int
) -> pd.DataFrame:
    window = frame.loc[start:end]
    return window.corr(method="pearson", min_periods=min_periods)


def _print_matrix(title: str, matrix: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    short = [name[:18] for name in matrix.columns]
    print(" " * 20 + " ".join(f"{i:>7d}" for i in range(len(short))))
    for index, name in enumerate(matrix.index):
        row = " ".join(f"{matrix.iloc[index, j]:>7.2f}" for j in range(len(short)))
        print(f"{short[index]:<20}{row}")
    print("legend: " + " | ".join(f"{i}={s}" for i, s in enumerate(short)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--processes", type=int, default=3)
    parser.add_argument("--tuned-dir", type=Path, default=TUNED_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    tuned_dir = Path(args.tuned_dir)
    names = _factor_names(tuned_dir)
    print(f"factors: {names}", flush=True)

    with ProcessPoolExecutor(
        max_workers=args.processes, initializer=_init_worker
    ) as pool:
        items = []
        for item in pool.map(_one_factor, [(name, str(tuned_dir)) for name in names]):
            print(
                f"built {item['name']:<32} days={len(item['daily']):<6} "
                f"train_sharpe={item['sharpe']:.4f} turnover={item['turnover']:.4f}",
                flush=True,
            )
            items.append(item)

    daily = _pivot_to_matrix(items, "daily")
    daily = daily.sort_index()
    print(f"\ndaily return frame: {daily.shape}, "
          f"{daily.index.min().date()} .. {daily.index.max().date()}")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    corr_10y = _corr_block(daily, "2016-01-01", "2025-12-31", 200)
    corr_2025 = _corr_block(daily, "2025-01-01", "2025-12-31", 60)
    corr_spear = daily.loc["2016-01-01":"2025-12-31"].corr(
        method="spearman", min_periods=200
    )

    corr_10y.to_csv(out / "corr_returns_10y.csv")
    corr_2025.to_csv(out / "corr_returns_2025.csv")
    corr_spear.to_csv(out / "corr_returns_10y_spearman.csv")

    signal = pd.DataFrame(
        index=[item["name"] for item in items], columns=[item["name"] for item in items],
        dtype=float,
    )
    date_counts = pd.DataFrame(0, index=signal.index, columns=signal.columns)
    for i, left in enumerate(items):
        signal.iloc[i, i] = 1.0
        for j in range(i + 1, len(items)):
            right = items[j]
            value, count = _signal_correlation(left["pivot"], right["pivot"])
            signal.iloc[i, j] = value
            signal.iloc[j, i] = value
            date_counts.iloc[i, j] = count
            date_counts.iloc[j, i] = count
    signal.to_csv(out / "corr_signals_10y.csv")

    _print_matrix("daily net return, Pearson, 2016-2025", corr_10y)
    _print_matrix("daily net return, Pearson, 2025 only", corr_2025)
    _print_matrix("daily net return, Spearman, 2016-2025", corr_spear)
    _print_matrix("cross-sectional signal, Spearman, 2016-2025", signal)

    mask = ~np.eye(len(items), dtype=bool)
    for label, matrix in (
        ("10y return", corr_10y),
        ("2025 return", corr_2025),
        ("signal", signal),
    ):
        values = matrix.to_numpy(dtype=float)[mask]
        values = values[np.isfinite(values)]
        print(
            f"\n{label}: mean off-diagonal {values.mean():.3f}, "
            f"median {np.median(values):.3f}, "
            f"max {values.max():.3f}, min {values.min():.3f}"
        )
        pairs = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                pairs.append((matrix.iloc[i, j], items[i]["name"], items[j]["name"]))
        pairs.sort(reverse=True)
        print("  top |corr| pairs:")
        for value, left, right in pairs[:5]:
            print(f"    {value:+.3f}  {left} ~ {right}")
        print("  most independent:")
        for value, left, right in sorted(pairs, key=lambda row: abs(row[0]))[:5]:
            print(f"    {value:+.3f}  {left} ~ {right}")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        labels = [f"{i}:{name[:16]}" for i, name in enumerate(names)]
        signal_limit = float(np.nanmax(np.abs(signal.to_numpy(dtype=float))))
        signal_limit = max(0.4, np.ceil(signal_limit * 10) / 10)
        fig, axes = plt.subplots(1, 3, figsize=(20, 6.4))
        panels = (
            ("Daily net return corr, 2016-2025", corr_10y, -1.0, 1.0),
            ("Daily net return corr, 2025", corr_2025, -1.0, 1.0),
            ("Signal cross-sectional rank corr", signal, -1.0, 1.0),
        )
        for position, (axis, (title, matrix, low, high)) in enumerate(zip(axes, panels)):
            data = matrix.to_numpy(dtype=float)
            if title.startswith("Signal"):
                low, high = -signal_limit, signal_limit
            image = axis.imshow(data, cmap="RdBu_r", vmin=low, vmax=high)
            axis.set_title(title, fontsize=11)
            axis.set_xticks(range(len(labels)))
            axis.set_yticks(range(len(labels)))
            axis.set_xticklabels(range(len(labels)))
            if position == 0:
                axis.set_yticklabels(labels, fontsize=8)
            else:
                axis.set_yticklabels([])
            for i in range(len(labels)):
                for j in range(len(labels)):
                    value = data[i, j]
                    if np.isfinite(value):
                        colour = "white" if abs(value) > 0.55 * high else "black"
                        axis.text(j, i, f"{value:.2f}", ha="center", va="center",
                                  fontsize=7, color=colour)
        legend = "\n".join(labels)
        fig.text(0.005, 0.5, legend, va="center", fontsize=8)
        fig.subplots_adjust(left=0.20, right=0.88, top=0.88, bottom=0.12, wspace=0.18)
        fig.colorbar(image, ax=axes, shrink=0.7, pad=0.015)
        fig.suptitle(
            f"CTA alpha22 factors: correlation matrices ({tuned_dir.name} optima)"
        )
        target = out / "correlation_matrices.png"
        try:
            fig.savefig(target, dpi=150, bbox_inches="tight")
        except OSError:
            # bbox_inches="tight" can raise OSError(22) on some Windows setups.
            fig.savefig(target, dpi=150)
        print(f"\nwrote {target}")
    except Exception as error:  # pragma: no cover - plotting is optional
        print(f"plot skipped: {error!r}")

    print(f"wrote {out / 'corr_returns_10y.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
