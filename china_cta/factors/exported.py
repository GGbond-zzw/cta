"""Registered sleeves that were mined by the expression search and exported as frozen signals.

The mining project (a sibling checkout) searches expressions over price/volume/open
interest features, fits a direction and a scale, and freezes the resulting signal into a
portable package.  Those signals are already ``clip(raw * direction / scale, -1, 1)`` and
are dated on the information day, exactly like the factor tables produced by
``china_cta.research.bayesian_tuning.build_factor``.  This module keeps the small amount of
metadata needed to treat a package directory as another sleeve source, and validates the
files before they enter a book.

Packages are versioned exports: ``package`` names the round an expression came from, and a
single book can mix packages as long as every requested sleeve is found in one of the
supplied directories.

Nothing here re-fits direction or scale: the frozen numbers are carried for the record only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

PACKAGE_REQUIRED_COLUMNS = (
    "trading_date",
    "instrument",
    "raw_factor",
    "signal",
    "factor_name",
)


@dataclass(frozen=True)
class ExportedSleeve:
    """One frozen sleeve from the mining export."""

    name: str
    folder: str
    package: str
    source: str
    direction: int
    scale: float
    description: str
    expression: str
    status: str = "qualified"

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "folder": self.folder,
            "package": self.package,
            "source": self.source,
            "direction": self.direction,
            "scale": self.scale,
            "description": self.description,
            "expression": self.expression,
            "status": self.status,
        }


# name -> frozen sleeve.  ``folder`` is the directory inside the exported package, ``package``
# groups sleeves exported in the same round, ``source`` is the identifier minted by the mining
# run, kept so results can be traced back.
#
# Naming convention: the descriptive part says what the expression actually measures, the
# numeric suffix is the window that matters most.
OLD_ROUND = "old-mined-20261116"
NEW_ROUND = "round2-20261119"

EXPORTED_SLEEVES: dict[str, ExportedSleeve] = {
    # ---- first mined round: 原8号 / 原2号 / 上一轮1号 -------------------------------
    "crowded_trend_reversal_60d": ExportedSleeve(
        name="crowded_trend_reversal_60d",
        folder="old_08",
        package=OLD_ROUND,
        source="mined_4a51bf38703a",
        direction=1,
        scale=0.7073720289720415,
        description="原8号：趋势与“通道位置×波动”的 60 日相关性取负，趋势若被高波动/高位推动则反向。",
        expression="neg(corr(mean(return_60, 60), mul(channel_position_20, volatility_20), 60))",
    ),
    "volume_burst_vol_reversal_60d": ExportedSleeve(
        name="volume_burst_vol_reversal_60d",
        folder="new_01_previous_round",
        package=OLD_ROUND,
        source="mined_8eb423cac50b",
        direction=-1,
        scale=0.3029101622490162,
        description="上一轮1号：放量加速与波动放大（vol20/vol60）的 20 日相关性，再取 60 日均值后取负。",
        expression="mul(-1, mean(corr(delta(volume_surprise_20, 20), mean(volatility_ratio, 60), 20), 60))",
    ),
    # ---- second mined round: 本轮 1号 / 6号 / 8号 / 20号 ----------------------------
    "turnover_surprise_channel_ratio": ExportedSleeve(
        name="turnover_surprise_channel_ratio",
        folder="current_01_turnover_surprise_channel_ratio",
        package=NEW_ROUND,
        source="mined_f0dd19ea2ff1",
        direction=1,
        scale=4.414286511620197,
        description="本轮1号：成交额相对前 20 日均值的偏离，除以收盘价在 20 日高低区间内的居中位置。",
        expression="turnover_surprise_20 / channel_position_20",
    ),
    "inverse_oi_turnover_surprise_ratio": ExportedSleeve(
        name="inverse_oi_turnover_surprise_ratio",
        folder="current_08_inverse_oi_turnover_surprise_ratio",
        package=NEW_ROUND,
        source="mined_cbe804196d96",
        direction=-1,
        scale=3.13168742823665,
        description="本轮8号：持仓量异动除以成交额异动的 10 日均值，训练拟合方向为负。",
        expression="oi_surprise_20 / mean(turnover_surprise_20, 10)",
    ),
    "volume_variability_weighted_reversal": ExportedSleeve(
        name="volume_variability_weighted_reversal",
        folder="current_20_volume_variability_weighted_reversal",
        package=NEW_ROUND,
        source="mined_57002a2d5f10",
        direction=-1,
        scale=0.0007038049575569826,
        description="本轮20号：一日收益乘以成交量变化的 20 日标准差、再取 5 日标准差，拟合方向为负。",
        expression="return_1 * std(std(volume_change, 20), 5)",
    ),
}

EXPORTED_NAMES: tuple[str, ...] = tuple(EXPORTED_SLEEVES)
EXPORTED_PACKAGES: tuple[str, ...] = tuple(
    dict.fromkeys(sleeve.package for sleeve in EXPORTED_SLEEVES.values())
)

#: Sleeves that belong to the live nine-sleeve book.
QUALIFIED_EXPORTED_SLEEVES: tuple[str, ...] = tuple(
    name for name, sleeve in EXPORTED_SLEEVES.items() if sleeve.status == "qualified"
)
#: Sleeves kept in the registry for reproducibility but excluded from the live book.
RETIRED_EXPORTED_SLEEVES: tuple[str, ...] = tuple(
    name for name, sleeve in EXPORTED_SLEEVES.items() if sleeve.status == "retired"
)


def resolve(names: str | list[str] | tuple[str, ...]) -> tuple[ExportedSleeve, ...]:
    """Turn a comma separated list (or ``"all"``) into sleeves, rejecting unknown names."""

    if isinstance(names, str):
        raw = [item.strip() for item in names.split(",") if item.strip()]
    else:
        raw = [str(item).strip() for item in names if str(item).strip()]
    if not raw or raw == ["all"]:
        raw = list(EXPORTED_NAMES)
    elif raw == ["qualified"]:
        raw = list(QUALIFIED_EXPORTED_SLEEVES)
    elif raw == ["retired"]:
        raw = list(RETIRED_EXPORTED_SLEEVES)
    unknown = [item for item in raw if item not in EXPORTED_SLEEVES]
    if unknown:
        raise SystemExit(
            f"unknown exported sleeve(s): {unknown}; available: {', '.join(EXPORTED_NAMES)}"
        )
    return tuple(EXPORTED_SLEEVES[item] for item in raw)


def qualified_sleeves() -> tuple[ExportedSleeve, ...]:
    """The exported sleeves that the live book uses, in registry order."""

    return tuple(EXPORTED_SLEEVES[name] for name in QUALIFIED_EXPORTED_SLEEVES)


def locate(
    sleeves: tuple[ExportedSleeve, ...], package_dirs: list[str] | tuple[str, ...]
) -> tuple[tuple[ExportedSleeve, Path], ...]:
    """Pair every requested sleeve with the package directory that actually holds it."""

    roots = [Path(item) for item in package_dirs]
    if not roots:
        raise SystemExit("no --extra-package given")
    pairs: list[tuple[ExportedSleeve, Path]] = []
    unresolved: list[str] = []
    for sleeve in sleeves:
        match = [root for root in roots if (root / sleeve.folder / "signals.parquet").exists()]
        if not match:
            unresolved.append(f"{sleeve.name} ({sleeve.folder})")
            continue
        if len(match) > 1:
            raise SystemExit(
                f"{sleeve.name}: found in more than one package: {[str(item) for item in match]}"
            )
        pairs.append((sleeve, match[0]))
    if unresolved:
        raise SystemExit(
            f"missing exported signals for {unresolved} under {[str(root) for root in roots]}"
        )
    return tuple(pairs)


def validate_package(package_dir: Path, sleeves: tuple[ExportedSleeve, ...]) -> None:
    """Fail fast when the package is not the one the registry was written for."""

    missing = [
        item for item in sleeves if not (package_dir / item.folder / "signals.parquet").exists()
    ]
    if missing:
        raise SystemExit(
            f"missing exported signals under {package_dir}: {[item.folder for item in missing]}"
        )
    for sleeve in sleeves:
        definition = package_dir / sleeve.folder / "definition.json"
        if not definition.exists():
            continue
        payload = json.loads(definition.read_text(encoding="utf-8"))
        declared = payload.get("factor_name", payload.get("name"))
        if declared not in (None, sleeve.source):
            raise SystemExit(
                f"{sleeve.name}: definition name {declared!r} != registry {sleeve.source!r}"
            )
        fitted = payload.get("fitted", {})
        if abs(float(fitted.get("scale", sleeve.scale)) - sleeve.scale) > 1e-12:
            raise SystemExit(f"{sleeve.name}: fitted scale changed in the package")
        if int(fitted.get("direction", sleeve.direction)) != sleeve.direction:
            raise SystemExit(f"{sleeve.name}: fitted direction changed in the package")


def load_signals(package_dir: Path, sleeve: ExportedSleeve) -> pd.DataFrame:
    """Read one frozen sleeve as a factor table the research/native engines can consume."""

    frame = pd.read_parquet(package_dir / sleeve.folder / "signals.parquet")
    missing = [column for column in PACKAGE_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise SystemExit(f"{sleeve.folder}/signals.parquet missing columns: {missing}")

    table = frame.loc[:, list(PACKAGE_REQUIRED_COLUMNS)].copy()
    table["trading_date"] = pd.to_datetime(table["trading_date"])
    table["instrument"] = table["instrument"].astype(str).str.upper()
    table["raw_factor"] = pd.to_numeric(table["raw_factor"], errors="coerce")
    table["signal"] = pd.to_numeric(table["signal"], errors="coerce")
    table["factor_name"] = sleeve.name

    duplicated = int(table.duplicated(subset=["trading_date", "instrument"]).sum())
    if duplicated:
        raise SystemExit(f"{sleeve.name}: {duplicated} duplicated (date, instrument) rows")
    if table["signal"].abs().max() > 1.0 + 1e-9:
        raise SystemExit(f"{sleeve.name}: signal exceeds [-1, 1]")
    if table["trading_date"].isna().any():
        raise SystemExit(f"{sleeve.name}: unparsable trading_date values")

    table.attrs["exported_sleeve"] = sleeve.as_dict()
    table.attrs["source"] = str(package_dir / sleeve.folder / "signals.parquet")
    return table.sort_values(["trading_date", "instrument"]).reset_index(drop=True)


def describe(sleeves: tuple[ExportedSleeve, ...] | None = None) -> pd.DataFrame:
    """Registry view used by reports and the manifest."""

    chosen = sleeves or tuple(EXPORTED_SLEEVES[name] for name in EXPORTED_NAMES)
    return pd.DataFrame([item.as_dict() for item in chosen])
