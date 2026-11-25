"""Stage 60: replay the four-factor book into a native RQAlpha futures account.

Signals and the volatility overlay come from the research pipeline (stage 50).
This stage answers a different question: what does a 50m futures account own
after integer lots, exchange margin, a 25% previous-session volume cap, one tick
of slippage and the exchange's own per-contract commission?

Because the native book carries frictions the proxy does not, the overlay is
calibrated once against its own realised volatility: pass 1 runs the research
overlay, pass 2 rescales it so the account actually lands on the 20% target (the
calibration factor is written to ``vol_calibration.csv``).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from china_cta.formal_backtest import native_account as native  # noqa: E402
from china_cta.research import bayesian_tuning as bt  # noqa: E402
from china_cta.factors.cta_catalog import AVAILABLE_FACTORS
from china_cta.factors.qualified import BUILDERS as QUALIFIED_BUILDERS  # noqa: E402
from china_cta.research.fast_backtest import run_fast_research_backtest  # noqa: E402
from china_cta.runtime_paths import require_rqalpha_bundle_path  # noqa: E402

DEFAULT_FACTORS = (
    "historical_skewness_252d",
    "fixed_maturity_carry_90_180d",
    "xsmom_252_21",
    "oi_participation_trend_60d",
)
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data/research_inputs/cta_alpha22"
DEFAULT_TUNED_DIR = PROJECT_ROOT / "results/tuning/qualified4_300"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/final_4f_native_vol20"

_INPUTS: dict[str, pd.DataFrame] = {}


def _init_worker(input_dir: str) -> None:
    global _INPUTS
    _INPUTS = bt.load_inputs(Path(input_dir))


def _build_sleeve(task: tuple[str, str]) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    name, tuned_dir = task
    payload = json.loads(
        (Path(tuned_dir) / name / "best_params.json").read_text(encoding="utf-8")
    )
    table = bt.build_factor(name, payload["best_params"], _INPUTS)
    signals = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(table["trading_date"]),
            "product": table["instrument"].astype(str),
            "signal": table["signal"].astype(float),
            "sleeve": name,
        }
    )
    signals = signals.loc[signals["signal"].ne(0)].reset_index(drop=True)
    result = run_fast_research_backtest(
        table,
        _INPUTS["continuous_prices"],
        _INPUTS["universe"],
        execution_lag=1,
        cost_rate=0.0001,
        execution_price_field="open",
        include_breakdowns=False,
    )
    detail = result["detail"]
    daily = (
        detail.groupby("realization_date")["net_signal_return"]
        .mean()
        .rename("net_signal_return")
        .reset_index()
    )
    daily["sleeve"] = name
    return name, signals, daily


def _build_package_sleeve(task: tuple[str, str]) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Build one of the eleven in-repo qualified packages (parameters live in the package)."""

    name, _ = task
    table = QUALIFIED_BUILDERS[name](_INPUTS)
    signals = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(table["trading_date"]),
            "product": table["instrument"].astype(str),
            "signal": table["signal"].astype(float),
            "sleeve": name,
        }
    )
    signals = signals.loc[signals["signal"].ne(0)].reset_index(drop=True)
    result = run_fast_research_backtest(
        table,
        _INPUTS["continuous_prices"],
        _INPUTS["universe"],
        execution_lag=1,
        cost_rate=0.0001,
        execution_price_field="open",
        include_breakdowns=False,
    )
    detail = result["detail"]
    daily = (
        detail.groupby("realization_date")["net_signal_return"]
        .mean()
        .rename("net_signal_return")
        .reset_index()
    )
    daily["sleeve"] = name
    return name, signals, daily


def _build_any(task: tuple[str, str, str]) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    kind, name, directory = task
    if kind == "package":
        return _build_package_sleeve((name, directory))
    return _build_sleeve((name, directory))


def _package_selection(spec: str, already: Sequence[str]) -> list[str]:
    """Resolve ``--package-factors`` into package names not already in the book."""

    text = (spec or "none").strip().lower()
    routable = set(AVAILABLE_FACTORS)
    available = [
        name for name in QUALIFIED_BUILDERS if name not in set(already) and name in routable
    ]
    if text == "none":
        return []
    if text in {"all", "qualified"}:
        return available
    wanted = [item.strip() for item in text.split(",") if item.strip()]
    unknown = [item for item in wanted if item not in QUALIFIED_BUILDERS]
    if unknown:
        raise SystemExit(f"unknown package factors: {unknown}")
    blocked = [item for item in wanted if item not in routable]
    if blocked:
        raise SystemExit(
            f"package factors that cannot run in this environment: {blocked}"
        )
    return [item for item in wanted if item not in set(already)]


def _book_selection(spec: str, sleeves: dict[str, pd.DataFrame]) -> set[str]:
    """``all`` (default), ``none``, or a comma separated list of sleeve names."""

    raw = [item.strip() for item in str(spec).split(",") if item.strip()]
    if not raw or raw == ["all"]:
        return set(sleeves)
    if raw == ["none"]:
        return set()
    unknown = [item for item in raw if item not in sleeves]
    if unknown:
        raise SystemExit(f"--book-factors: not part of this run: {unknown}")
    return set(raw)


def _calibration_path(
    equity: pd.Series,
    *,
    target: float,
    window: int,
    cap: float,
    min_periods: int,
) -> pd.Series:
    """Rolling correction from pass-1 realised volatility to the target."""

    returns = equity.pct_change()
    trailing = (
        returns.rolling(window, min_periods=min_periods).std(ddof=1).shift(1)
        * (252.0**0.5)
    )
    factor = (target / trailing.where(trailing > 0)).clip(lower=0.0, upper=cap)
    return factor.fillna(1.0).astype(float)


def _leverage(daily: pd.Series, *, window: int, target: float, cap: float) -> pd.Series:
    trailing = daily.rolling(window, min_periods=window).std(ddof=1).shift(1) * math.sqrt(252)
    leverage = (target / trailing.where(trailing > 0)).clip(upper=cap)
    return leverage.where(trailing.notna(), 1.0).fillna(1.0).astype(float)


def _risk_diagnostics(
    targets: pd.DataFrame,
    market: dict[str, pd.DataFrame],
    capital: float,
    output: Path,
    equity: pd.Series | None = None,
) -> dict[str, float]:
    if targets.empty:
        return {}
    settlement = market["bars"].set_index(["trading_date", "order_book_id"])["settlement"]
    instruments_index = market["instruments"].set_index("order_book_id")
    priced = (
        targets.join(instruments_index["contract_multiplier"], on="order_book_id")
        .join(settlement, on=["trading_date", "order_book_id"])
    )
    priced["gross_notional"] = (
        priced["target_quantity"].abs() * priced["settlement"] * priced["contract_multiplier"]
    )
    daily = priced.groupby("trading_date").agg(
        gross_notional=("gross_notional", "sum"),
        margin=("margin_used", "sum"),
        contracts=("order_book_id", "size"),
    )
    daily.index = pd.to_datetime(daily.index)
    if equity is not None and not equity.empty:
        reference = equity.reindex(daily.index)
        reference = reference.ffill().bfill()
    else:
        reference = pd.Series(capital, index=daily.index, dtype=float)
    daily["equity"] = reference
    daily["gross_over_equity"] = daily["gross_notional"] / daily["equity"]
    daily["margin_over_equity"] = daily["margin"] / daily["equity"]
    daily.to_csv(output / "daily_risk.csv", float_format="%.17g")
    summary = {
        "gross_over_equity_median": float(daily["gross_over_equity"].median()),
        "gross_over_equity_max": float(daily["gross_over_equity"].max()),
        "margin_over_equity_median": float(daily["margin_over_equity"].median()),
        "margin_over_equity_max": float(daily["margin_over_equity"].max()),
        "contracts_per_day_median": float(daily["contracts"].median()),
    }
    print(
        "risk: gross/equity median={gross_over_equity_median:.2f} max={gross_over_equity_max:.2f} "
        "| margin/equity median={margin_over_equity_median:.2%} max={margin_over_equity_max:.2%} "
        "| contracts/day median={contracts_per_day_median:.0f}".format(**summary)
    )
    return summary



def _plot_books(books: dict[str, pd.Series], target: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(13, 6.5))
    longest = max(len(series) for series in books.values())
    for name, equity in books.items():
        axis.plot(
            equity.index,
            equity / equity.iloc[0],
            lw=2.0 if len(equity) == longest and name == "equal_weight_4f" else 1.1,
            label=name,
        )
    axis.set_yscale("log")
    axis.set_title(
        "Native account net equity (50M capital, 50% margin budget, 1-tick slippage)"
    )
    axis.legend(loc="upper left", fontsize=9)
    axis.grid(alpha=0.3)
    figure.tight_layout()
    figure.savefig(target, dpi=150)
    plt.close(figure)
    print(f"wrote {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factors", default=",".join(DEFAULT_FACTORS))
    parser.add_argument(
        "--package-factors",
        default="none",
        help="comma separated in-repo qualified packages to build from code, or all/qualified/none",
    )
    parser.add_argument(
        "--extra-factors",
        default="all",
        help="comma separated exported sleeve names, or all/qualified/retired/none",
    )
    parser.add_argument(
        "--book-factors",
        default="all",
        help="comma separated sleeves to replay as single-sleeve accounts, or all/none",
    )
    parser.add_argument("--tuned-dir", default=str(DEFAULT_TUNED_DIR))
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--start", default="2016-01-04")
    parser.add_argument("--end", default="2026-10-30")
    parser.add_argument("--capital", type=float, default=50_000_000.0)
    parser.add_argument("--margin-budget", type=float, default=0.50)
    parser.add_argument("--slippage-ticks", type=float, default=1.0)
    parser.add_argument("--volume-percent", type=float, default=0.25)
    parser.add_argument("--vol-target", type=float, default=0.20)
    parser.add_argument(
        "--factor-books",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="also replay every factor as its own native book",
    )
    parser.add_argument("--vol-window", type=int, default=60)
    parser.add_argument("--max-leverage", type=float, default=10.0)
    parser.add_argument("--processes", type=int, default=3)
    parser.add_argument("--bundle", default=None)
    parser.add_argument("--log-level", default="error")
    parser.add_argument("--calibrate-vol", action="store_true", default=True)
    parser.add_argument("--no-calibrate-vol", dest="calibrate_vol", action="store_false")
    parser.add_argument(
        "--calibration",
        choices=("rolling", "one-shot"),
        default="rolling",
        help="rolling: re-estimate the correction from trailing realised volatility; "
        "one-shot: one scalar for the whole window",
    )
    parser.add_argument("--calibration-window", type=int, default=250)
    parser.add_argument("--calibration-min-periods", type=int, default=250)
    parser.add_argument("--max-calibration", type=float, default=2.0)
    parser.add_argument(
        "--sizing-smoothing",
        type=int,
        default=15,
        help="EWMA span applied to the ex-ante leverage ratio (0 disables it).",
    )
    parser.add_argument(
        "--structural-factor",
        type=float,
        default=None,
        help=(
            "Constant multiplier applied to the ex-ante leverage.  Default: derive it "
            "once from the pass-1 shortfall (target / realised), capped by "
            "--max-calibration.  Pass 1.0 to disable."
        ),
    )
    parser.add_argument(
        "--sizing",
        choices=("exante", "calibrate"),
        default="calibrate",
        help=(
            "exante: size the book so its *predicted* volatility (rollling 60 session "
            "covariance of the dominant contracts) hits the target; single pass, no "
            "calibration factor.  calibrate: keep the research overlay and scale it by "
            "the measured pass-1 shortfall."
        ),
    )
    args = parser.parse_args()

    factors = tuple(item.strip() for item in args.factors.split(",") if item.strip())
    tuned_dir = Path(args.tuned_dir)
    missing = [
        name
        for name in factors
        if not (tuned_dir / name / "best_params.json").exists()
        and name not in QUALIFIED_BUILDERS
    ]
    if missing:
        raise SystemExit(
            f"no tuned parameters for {missing} under {tuned_dir} and no in-repo package"
        )

    output = Path(args.out_dir)
    output.mkdir(parents=True, exist_ok=True)

    print(f"building {len(factors)} tuned sleeves from {tuned_dir}")
    tasks: list[tuple[str, str, str]] = []
    for name in factors:
        if (tuned_dir / name / "best_params.json").exists():
            tasks.append(("tuned", name, str(tuned_dir)))
        else:
            tasks.append(("package", name, ""))

    packages = _package_selection(args.package_factors, factors)
    tasks += [("package", name, "") for name in packages]
    if packages:
        print(f"appending {len(packages)} in-repo packages: {list(packages)}")
    signals_by_sleeve: dict[str, pd.DataFrame] = {}
    daily_by_sleeve: dict[str, pd.Series] = {}
    with ProcessPoolExecutor(
        max_workers=max(1, min(args.processes, len(tasks))),
        initializer=_init_worker,
        initargs=(args.input_dir,),
    ) as pool:
        for name, signals, daily in pool.map(_build_any, tasks):
            signals_by_sleeve[name] = signals
            daily_by_sleeve[name] = daily.set_index("realization_date")["net_signal_return"]
            print(f"  built {name:<34} signals={len(signals):>7} days={len(daily):>5}")

    weights = {name: 1.0 / len(signals_by_sleeve) for name in signals_by_sleeve}
    meta: dict[str, Any] = {
        "package_sleeves": list(packages),
        "sleeves": list(signals_by_sleeve),
        "sleeve_weights": dict(weights),
    }

    all_stamps = pd.to_datetime(
        sorted({stamp for series in daily_by_sleeve.values() for stamp in series.index})
    )
    proxy = pd.DataFrame(index=all_stamps)
    for name, series in daily_by_sleeve.items():
        proxy[name] = series.reindex(all_stamps)
    combo = proxy.fillna(0.0).mul(pd.Series(weights), axis=1).sum(axis=1)

    overlay_leverage = _leverage(
        combo, window=args.vol_window, target=args.vol_target, cap=args.max_leverage
    )
    window_mask = (overlay_leverage.index >= pd.Timestamp(args.start)) & (
        overlay_leverage.index <= pd.Timestamp(args.end)
    )
    overlay_leverage = overlay_leverage.loc[window_mask]
    overlay = pd.DataFrame(
        {
            "trading_date": overlay_leverage.index,
            "leverage": overlay_leverage.to_numpy(),
            "research_combo_return": combo.reindex(overlay_leverage.index).to_numpy(),
        }
    )
    overlay.to_csv(output / "research_overlay.csv", index=False, float_format="%.17g")
    print(
        f"research overlay: median leverage={overlay_leverage.median():.2f} "
        f"capped={int((overlay_leverage >= args.max_leverage - 1e-12).sum())}/{len(overlay_leverage)}"
    )

    signals = pd.concat(signals_by_sleeve.values(), ignore_index=True)
    signals = signals.loc[
        pd.to_datetime(signals["trading_date"]).between(
            pd.Timestamp(args.start), pd.Timestamp(args.end)
        )
    ].reset_index(drop=True)
    exposure = native.combine_sleeves(signals, weights)

    dominant = pd.read_parquet(Path(args.input_dir) / "dominant_map.parquet").rename(
        columns={"underlying_symbol": "product"}
    )
    dominant = dominant.loc[
        pd.to_datetime(dominant["trading_date"]).between(
            pd.Timestamp(args.start), pd.Timestamp(args.end)
        )
    ].reset_index(drop=True)
    dominant["product"] = dominant["product"].astype(str)

    bundle = (
        Path(args.bundle)
        if args.bundle
        else require_rqalpha_bundle_path("scripts/70_native_backtest.py")
    )
    market = native.load_market(
        bundle,
        sorted(signals["product"].unique().tolist()),
        cache_dir=PROJECT_ROOT / "data/cache/native",
    )

    config = native.NativeAccountConfig(
        start_date=args.start,
        end_date=args.end,
        bundle_path=bundle,
        output_dir=output,
        initial_capital=args.capital,
        margin_budget=args.margin_budget,
        slippage_ticks=args.slippage_ticks,
        volume_percent=args.volume_percent,
        log_level=args.log_level,
    )

    night_sessions = native.night_products(market["instruments"])
    session_calendar = sorted(pd.to_datetime(market["bars"]["trading_date"]).unique())
    print(f"night-session products: {len(night_sessions)} of {market['terms'].shape[0]}")
    term_tick = market["terms"].set_index("product")["tick_size"].astype(float)
    tick_sizes = {
        str(row.order_book_id): float(term_tick.get(row.product, 0.0) or 0.0)
        for row in market["instruments"].itertuples()
    }

    def replay(
        leverage_series: pd.Series, tag: str
    ) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
        exposures = native.build_target_exposures(
            exposure, dominant, market, leverage_series, config
        )
        if exposures.empty:
            raise SystemExit("no target positions were produced")
        result = native.run_native_account_dynamic(
            exposures,
            config,
            tick_sizes=tick_sizes,
            night_products=night_sessions,
            session_calendar=session_calendar,
        )
        targets = result["targets"]
        equity = native.daily_equity(result)
        metrics = native.performance_metrics(equity)
        print(
            f"[{tag}] sharpe={metrics.get('sharpe', float('nan')):.4f} "
            f"vol={metrics.get('annualized_volatility', float('nan')):.4f} "
            f"ann={metrics.get('annualized_return', float('nan')):.4f} "
            f"mdd={metrics.get('max_drawdown', float('nan')):.4f} "
            f"contracts={len(targets)}"
        )
        return targets, result, metrics

    print("=== native account, pass 1 (research overlay) ===")
    targets1, result1, metrics1 = replay(overlay_leverage, "pass1")
    targets1.to_csv(output / "target_positions_pass1.csv", index=False, float_format="%.17g")
    native.write_outputs(
        result1,
        config,
        targets=targets1,
        extra={
            "pass": "pass1",
            "leverage_median": float(overlay_leverage.median()),
            **meta,
        },
    )
    first_equity = output / "daily_equity.csv"
    (output / "daily_equity_pass1.csv").write_text(first_equity.read_text(encoding="utf-8"), encoding="utf-8")

    realised = float(metrics1.get("annualized_volatility", 0.0))

    if args.sizing == "exante":
        unit = exposure.rename(columns={"exposure": "capital_units"})
        continuous = pd.read_parquet(Path(args.input_dir) / "continuous_prices.parquet")
        scaled = native.ex_ante_leverage(
            unit,
            market,
            dominant,
            target=args.vol_target,
            window=args.vol_window,
            cap=args.max_leverage * args.max_calibration,
            min_periods=args.calibration_min_periods,
            prices=continuous,
            smoothing=args.sizing_smoothing,
        )
        if scaled.empty:
            raise SystemExit("ex-ante sizing produced no leverage path")
        structural = 1.0
        if args.structural_factor is not None:
            structural = float(args.structural_factor)
        if structural != 1.0:
            scaled = (scaled * structural).clip(upper=args.max_leverage * args.max_calibration)
            print(
                f"structural factor x{structural:.4f} "
                f"(pass-1 realised {realised:.4f} vs target {args.vol_target:.4f})"
            )
        scaled = scaled.reindex(overlay["trading_date"]).ffill().fillna(1.0)
        ceiling = args.max_leverage * args.max_calibration
        implied = args.vol_target / float(scaled.median()) if float(scaled.median()) else float("nan")
        print(
            "ex-ante sizing: median leverage={:.2f} min={:.2f} max={:.2f} capped={}/{} "
            "| implied book vol at median={:.4f}".format(
                float(scaled.median()),
                float(scaled.min()),
                float(scaled.max()),
                int((scaled >= ceiling - 1e-9).sum()),
                len(scaled),
                implied,
            )
        )
        pd.DataFrame(
            {
                "trading_date": scaled.index,
                "ex_ante_leverage": scaled.to_numpy(),
                "research_combo_return": overlay["research_combo_return"].to_numpy(),
            }
        ).to_csv(output / "exante_leverage.csv", index=False, float_format="%.17g")
        print("=== native account, ex-ante risk sizing (single pass) ===")
        targets, result, metrics = replay(scaled, "exante")
        native.write_outputs(
            result,
            config,
            targets=targets,
            extra={
                "pass": "exante",
                **meta,
                "sizing": "exante",
                "structural_factor": structural,
                "calibration_mode": "none",
                "vol_window": args.vol_window,
                "vol_target": args.vol_target,
                "leverage_median": float(scaled.median()),
                "pass1": metrics1,
            },
        )

    calibration_mode = args.calibration
    calibration: float | pd.Series = 1.0
    if args.sizing != "exante":
        targets, result, metrics = targets1, result1, metrics1
    if args.sizing != "exante" and args.calibrate_vol and realised > 1e-9:
        applied: pd.Series | float
        if calibration_mode == "rolling":
            pass1_equity = native.daily_equity(result1).astype(float)
            path = _calibration_path(
                pass1_equity.astype(float),
                target=args.vol_target,
                window=args.calibration_window,
                cap=args.max_calibration,
                min_periods=args.calibration_min_periods,
            )
            calibration = path
            applied = path.reindex(overlay_leverage.index).fillna(1.0)
            print(
                "calibration (rolling {w}d): pass-1 realised {r:.4f} vs target {t:.4f} -> "
                "x{mean:.3f} (min {low:.3f}, max {high:.3f}, capped {capped}d)".format(
                    w=args.calibration_window,
                    r=realised,
                    t=args.vol_target,
                    mean=float(path.mean()),
                    low=float(path.min()),
                    high=float(path.max()),
                    capped=int((path >= args.max_calibration - 1e-12).sum()),
                )
            )
            pass1_trailing = (
                pass1_equity.pct_change()
                .rolling(args.calibration_window, min_periods=args.calibration_min_periods)
                .std(ddof=1)
                .shift(1)
                * (252.0**0.5)
            )
            pd.DataFrame(
                {
                    "trading_date": path.index,
                    "pass1_trailing_volatility": pass1_trailing.reindex(path.index).to_numpy(),
                    "calibration": path.to_numpy(),
                }
            ).to_csv(output / "calibration_path.csv", index=False, float_format="%.17g")
        else:
            scalar = min(args.vol_target / realised, args.max_calibration)
            calibration = scalar
            applied = pd.Series(scalar, index=overlay_leverage.index)
            print(
                "calibration (one-shot): realised {r:.4f} vs target {t:.4f} -> x{s:.3f}".format(
                    r=realised, t=args.vol_target, s=scalar
                )
            )
        scaled = (overlay_leverage * applied).clip(
            upper=args.max_leverage * args.max_calibration
        )
        pd.DataFrame(
            {
                "trading_date": overlay["trading_date"],
                "leverage": scaled.reindex(overlay["trading_date"]).to_numpy(),
                "research_combo_return": overlay["research_combo_return"],
            }
        ).to_csv(
            output / "research_overlay_calibrated.csv", index=False, float_format="%.17g"
        )
        print("=== native account, pass 2 (calibrated overlay) ===")
        targets, result, metrics = replay(scaled, "pass2")
        factor_mean = (
            float(calibration.mean())
            if isinstance(calibration, pd.Series)
            else float(calibration)
        )
        factor_low = (
            float(calibration.min())
            if isinstance(calibration, pd.Series)
            else float(calibration)
        )
        factor_high = (
            float(calibration.max())
            if isinstance(calibration, pd.Series)
            else float(calibration)
        )
        native.write_outputs(
            result,
            config,
            targets=targets,
            extra={
                "pass": "pass2",
                **meta,
                "calibration_mode": calibration_mode,
                "calibration_window": (
                    args.calibration_window if calibration_mode == "rolling" else None
                ),
                "calibration_factor": factor_mean,
                "calibration_min": factor_low,
                "calibration_max": factor_high,
                "leverage_median": float(scaled.median()),
                "pass1": metrics1,
            },
        )

    # ---- attribution, segments and per-factor native books -------------------
    book_label = f"equal_weight_{len(signals_by_sleeve)}f"
    attribution = native.attribute_pnl(result.get("positions"), result.get("trades"), market)
    report = native.write_attribution(
        attribution, native.daily_equity(result), args.capital, output, label=book_label
    )
    print(
        f"attribution: equity change {report['reconciliation']['equity_change']:.0f} vs "
        f"attributed {report['reconciliation']['attributed_net_pnl']:.0f} "
        f"(commission {report['reconciliation']['commission']:.0f}, "
        f"slippage {report['reconciliation']['slippage']:.0f})"
    )

    if args.factor_books:
        books: dict[str, pd.Series] = {book_label: native.daily_equity(result)}
        selected = _book_selection(args.book_factors, signals_by_sleeve)
        print(f"single-sleeve books: {sorted(selected) if selected else 'none'}")
        for name in sorted(selected):
            single = native.combine_sleeves(signals_by_sleeve[name], {name: 1.0})
            leverage = _leverage(
                daily_by_sleeve[name],
                window=args.vol_window,
                target=args.vol_target,
                cap=args.max_leverage,
            )
            book_dir = output / "factors" / name
            book_config = dataclasses.replace(config, output_dir=book_dir)
            try:
                single_exposures = native.build_target_exposures(
                    single, dominant, market, leverage, book_config
                )
                if single_exposures.empty:
                    print(f"[{name}] no target positions, skipped")
                    continue
                single_result = native.run_native_account_dynamic(
                    single_exposures,
                    book_config,
                    tick_sizes=tick_sizes,
                    night_products=night_sessions,
                    session_calendar=session_calendar,
                )
                single_targets = single_result["targets"]
                single_equity = native.daily_equity(single_result)
                single_metrics = native.performance_metrics(single_equity)
                native.write_outputs(
                    single_result, book_config, targets=single_targets, extra={"book": name}
                )
                native.write_attribution(
                    native.attribute_pnl(
                        single_result.get("positions"), single_result.get("trades"), market
                    ),
                    single_equity,
                    args.capital,
                    book_dir,
                    label=name,
                )
                books[name] = single_equity
                print(
                    f"[{name}] sharpe={single_metrics.get('sharpe', float('nan')):.4f} "
                    f"vol={single_metrics.get('annualized_volatility', float('nan')):.4f}"
                )
            except Exception as error:  # noqa: BLE001 - a broken book must not kill the run
                print(f"[{name}] failed: {error}")

        segment_rows = []
        year_rows = []
        instrument_rows = []
        for name in books:
            book_output = output if name == book_label else output / "factors" / name
            segments = pd.read_csv(book_output / "segments.csv")
            segments.insert(0, "book", name)
            segment_rows.append(segments)
            year_table = pd.read_csv(book_output / "by_year.csv")
            year_table.insert(0, "book", name)
            year_rows.append(year_table)
            instrument_table = pd.read_csv(book_output / "by_instrument.csv")
            instrument_table.insert(0, "book", name)
            instrument_rows.append(instrument_table)
        pd.concat(segment_rows, ignore_index=True).to_csv(
            output / "segments_by_book.csv", index=False, float_format="%.17g"
        )
        pd.concat(year_rows, ignore_index=True).to_csv(
            output / "by_year_by_book.csv", index=False, float_format="%.17g"
        )
        pd.concat(instrument_rows, ignore_index=True).to_csv(
            output / "by_instrument_by_book.csv", index=False, float_format="%.17g"
        )
        _plot_books(books, output / "equity_comparison.png")

    equity_series = pd.read_csv(
        output / "daily_equity.csv", parse_dates=["date"]
    ).set_index("date")["total_value"]
    risk = _risk_diagnostics(targets, market, args.capital, output, equity=equity_series)
    pd.Series(
        {
            "calibration_factor": calibration,
            "pass1_annualized_volatility": metrics1.get("annualized_volatility", float("nan")),
            "pass1_sharpe": metrics1.get("sharpe", float("nan")),
            "final_annualized_volatility": metrics.get("annualized_volatility", float("nan")),
            "final_sharpe": metrics.get("sharpe", float("nan")),
            **risk,
        }
    ).to_csv(output / "vol_calibration.csv", float_format="%.17g")

    print("=== native account (final) ===")
    for name, value in metrics.items():
        print(f"{name:<24}{value:>16.6f}")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
