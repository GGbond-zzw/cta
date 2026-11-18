"""Registered sleeves that were mined by the expression search and exported as frozen signals.

The mining project (a sibling checkout) searches expressions over price/volume/open
interest features, fits a direction and a scale, and freezes the resulting signal into a
portable package.  Those signals are already ``clip(raw * direction / scale, -1, 1)`` and
are dated on the information day, exactly like the factor tables produced by
``china_cta.research.bayesian_tuning.build_factor``.  This module keeps the small amount of
metadata needed to treat a package directory as another sleeve source, and validates the
files before they enter a book.

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
    source: str
    direction: int
    scale: float
    description: str
    expression: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "folder": self.folder,
            "source": self.source,
            "direction": self.direction,
            "scale": self.scale,
            "description": self.description,
            "expression": self.expression,
        }


# name -> frozen sleeve.  ``folder`` is the directory inside the exported package; ``source``
# is the identifier minted by the mining run, kept so results can be traced back.
#
# Naming convention: the descriptive part says what the expression actually measures, the
# numeric suffix is the window that matters most.  The mining labels (原8号 / 原2号 / 本轮1号)
# live in ``description`` so the two vocabularies stay linked.
EXPORTED_SLEEVES: dict[str, ExportedSleeve] = {
    "crowded_trend_reversal_60d": ExportedSleeve(
        name="crowded_trend_reversal_60d",
        folder="old_08",
        source="mined_4a51bf38703a",
        direction=1,
        scale=0.7073720289720415,
        description="原8号：趋势与“通道位置×波动”的 60 日相关性取负——趋势越是被高波动/高位推动，越反向做",
        expression="neg(corr(mean(return_60, 60), mul(channel_position_20, volatility_20), 60))",
    ),
    "volume_oi_coflow_10d": ExportedSleeve(
        name="volume_oi_coflow_10d",
        folder="old_02",
        source="mined_7dffc88fcdec",
        direction=1,
        scale=0.7148378264008488,
        description="原2号：成交量变化与持仓量超预期同向共振（量仓同增=新资金进场）的 10 日相关性，正向做多",
        expression="corr(volume_change, oi_surprise_20, 10)",
    ),
    "volume_burst_vol_reversal_60d": ExportedSleeve(
        name="volume_burst_vol_reversal_60d",
        folder="new_01_previous_round",
        source="mined_8eb423cac50b",
        direction=-1,
        scale=0.3029101622490162,
        description="本轮1号：放量加速与波动放大（vol20/vol60）20 日相关性、再取 60 日均值后取负——放量拉升后反转",
        expression="mul(-1, mean(corr(delta(volume_surprise_20, 20), mean(volatility_ratio, 60), 20), 60))",
    ),
}

EXPORTED_NAMES: tuple[str, ...] = tuple(EXPORTED_SLEEVES)


def resolve(names: str | list[str] | tuple[str, ...]) -> tuple[ExportedSleeve, ...]:
    """Turn a comma separated list (or ``"all"``) into sleeves, rejecting unknown names."""

    if isinstance(names, str):
        raw = [item.strip() for item in names.split(",") if item.strip()]
    else:
        raw = [str(item).strip() for item in names if str(item).strip()]
    if not raw or raw == ["all"]:
        raw = list(EXPORTED_NAMES)
    unknown = [item for item in raw if item not in EXPORTED_SLEEVES]
    if unknown:
        raise SystemExit(
            f"unknown exported sleeve(s): {unknown}; available: {', '.join(EXPORTED_NAMES)}"
        )
    return tuple(EXPORTED_SLEEVES[item] for item in raw)


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
        if payload.get("name") not in (None, sleeve.source):
            raise SystemExit(
                f"{sleeve.name}: definition name {payload.get('name')!r} != registry {sleeve.source!r}"
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
