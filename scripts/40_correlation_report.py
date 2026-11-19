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
from china_cta.factors import exported as exported_sleeves  # noqa: E402

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


def _measure(
    name: str, table: pd.DataFrame, *, params: dict[str, object], sharpe: float
) -> dict[str, object]:
    """Run one sleeve through the research engine and keep what the report needs."""

    assert _INPUTS is not None
    result = run_fast_research_backtest(
        table,
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
    turnover = detail.groupby("signal_date", sort=True)["turnover_proxy"].mean()
    return {
        "name": name,
        "params": params,
        "daily": daily,
        "pivot": pivot,
        "turnover": float(turnover.mean()),
        "sharpe": float(sharpe),
    }


def _one_tuned(name: str, tuned_dir: Path) -> dict[str, object]:
    assert _INPUTS is not None
    payload = json.loads(
        (Path(tuned_dir) / name / "best_params.json").read_text(encoding="utf-8")
    )
    params = payload["best_params"]
    factor = bt.build_factor(name, params, _INPUTS)
    return _measure(name, factor, params=params, sharpe=payload["best_train"]["sharpe"])


def _one_exported(name: str, package_dir: Path) -> dict[str, object]:
    sleeve = exported_sleeves.resolve(name)[0]
    table = exported_sleeves.load_signals(package_dir, sleeve)
    frozen = {"signal_scale": sleeve.scale, "direction": sleeve.direction}
    return _measure(name, table, params=frozen, sharpe=float("nan"))


def _one_factor(job: tuple[str, str, str]) -> dict[str, object]:
    kind, name, target = job
    if kind == "exported":
        return _one_exported(name, Path(target))
    return _one_tuned(name, Path(target))


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
    parser.add_argument(
        "--extra-package",
        action="append",
        default=None,
        help="directory of a frozen mined-signal export; repeat the flag to mix packages",
    )
    parser.add_argument(
        "--extra-factors",
        default="none",
        help="comma separated exported sleeve names, or all/none",
    )
    args = parser.parse_args()

    tuned_dir = Path(args.tuned_dir)
    names = _factor_names(tuned_dir)
    print(f"tuned factors: {names}", flush=True)

    jobs: list[tuple[str, str, str]] = [("tuned", name, str(tuned_dir)) for name in names]
    requested = (
        exported_sleeves.resolve(args.extra_factors) if args.extra_package else ()
    )
    for sleeve, package_dir in exported_sleeves.locate(requested, args.extra_package):
        exported_sleeves.validate_package(package_dir, (sleeve,))
        jobs.append(("exported", sleeve.name, str(package_dir)))
        print(f"exported sleeve: {sleeve.name} <- {package_dir} / {sleeve.folder}", flush=True)

    with ProcessPoolExecutor(
        max_workers=args.processes, initializer=_init_worker
    ) as pool:
        items = []
        for item in pool.map(_one_factor, jobs):
            sharpe = item["sharpe"]
            shown = "frozen" if not np.isfinite(sharpe) else f"{sharpe:.4f}"
            print(
                f"built {item['name']:<34} days={len(item['daily']):<6} "
                f"train_sharpe={shown:<8} turnover={item['turnover']:.4f}",
                flush=True,
            )
            items.append(item)

    daily = _pivot_to_matrix(items, "daily")
    daily = daily.sort_index()
    print(f"\ndaily return frame: {daily.shape}, "
          f"{daily.index.min().date()} .. {daily.index.max().date()}")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    daily.to_csv(out / "sleeve_daily_returns.csv")
    stats = pd.DataFrame(
        {
            "name": [item["name"] for item in items],
            "turnover": [item["turnover"] for item in items],
            "days": [len(item["daily"]) for item in items],
        }
    )
    stats["ann_return"] = daily.mean() * 252
    stats["ann_vol"] = daily.std(ddof=1) * np.sqrt(252)
    stats["sharpe"] = stats["ann_return"] / stats["ann_vol"]
    stats.to_csv(out / "sleeve_metrics.csv", index=False)

    equal = daily.mean(axis=1)
    combined = pd.DataFrame(
        {
            "days": [len(equal)],
            "ann_return": [equal.mean() * 252],
            "ann_vol": [equal.std(ddof=1) * np.sqrt(252)],
        }
    )
    combined["sharpe"] = combined["ann_return"] / combined["ann_vol"]
    combined.to_csv(out / "equal_weight_research.csv", index=False)
    print(
        f"\nequal-weight research check: sharpe={combined['sharpe'].iloc[0]:.4f} "
        f"ann={combined['ann_return'].iloc[0]:.4f} vol={combined['ann_vol'].iloc[0]:.4f}",
        flush=True,
    )

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

        labels = [f"{i}:{item['name']}" for i, item in enumerate(items)]
        signal_limit = float(np.nanmax(np.abs(signal.to_numpy(dtype=float))))
        signal_limit = max(0.4, np.ceil(signal_limit * 10) / 10)
        side = max(20.0, 2.6 * len(items))
        fig, axes = plt.subplots(1, 3, figsize=(side, 0.55 * side + 2.0))
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
            tick_font = max(5.0, 9.0 - 0.25 * len(labels))
            if position == 0:
                axis.set_yticklabels(labels, fontsize=tick_font)
            else:
                axis.set_yticklabels([])
            for i in range(len(labels)):
                for j in range(len(labels)):
                    value = data[i, j]
                    if np.isfinite(value):
                        colour = "white" if abs(value) > 0.55 * high else "black"
                        axis.text(j, i, f"{value:.2f}", ha="center", va="center",
                                  fontsize=max(5.0, 8.0 - 0.3 * len(labels)), color=colour)
        legend = "\n".join(labels)
        fig.text(0.005, 0.5, legend, va="center", fontsize=max(6.0, 9.0 - 0.2 * len(labels)))
        fig.subplots_adjust(left=0.20, right=0.88, top=0.88, bottom=0.12, wspace=0.18)
        fig.colorbar(image, ax=axes, shrink=0.7, pad=0.015)
        fig.suptitle(
            f"CTA sleeve correlation matrices ({len(items)} sleeves, {out.name})"
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
