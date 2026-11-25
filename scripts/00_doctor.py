'''Report what this machine can run before touching the pipeline.

Every stage has an explicit precondition; this script checks them and prints a
capability matrix plus the stages that can run here.  It never writes to
``data/`` or ``results/`` and never imports an optional dependency just to look
for it.

Usage::

    python scripts/00_doctor.py
'''

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from china_cta.runtime_paths import (  # noqa: E402
    describe_paths,
    get_rqalpha_bundle_path,
    get_research_input_dir,
)

CORE_PACKAGES = ("pandas", "numpy", "pyarrow", "h5py", "optuna")
OPTIONAL_PACKAGES = {
    "rqdatac": "stage 10 (data fetch)",
    "torch": "factor our_reg35_transformer",
}

STAGE_REQUIREMENTS = (
    ("10", "fetch research inputs", ("rqdatac",)),
    ("12", "add open from bundle", ("bundle", "cache")),
    ("20", "rebuild inputs from bundle", ("bundle",)),
    ("30", "tune factors (in process)", ("cache", "optuna")),
    ("31", "tune factors (by process)", ("cache", "optuna")),
    ("32", "verify tuning outputs", ("tuned",)),
    ("40", "correlation report", ("cache",)),
    ("50", "portfolio backtest (research layer)", ("cache", "tuned")),
    ("60", "render run chart", ("results",)),
    ("70", "native account backtest", ("cache", "bundle")),
)


def _installed(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _research_inputs() -> dict[str, object]:
    directory = get_research_input_dir()
    prices = directory / "continuous_prices.parquet"
    if not prices.is_file():
        return {"ok": False, "detail": f"missing {prices}"}
    frame = pd.read_parquet(prices, columns=["trading_date"])
    window = pd.to_datetime(frame["trading_date"])
    return {
        "ok": True,
        "detail": f"{window.min().date()} .. {window.max().date()} | rows {len(frame):,}",
    }


def _bundle() -> dict[str, object]:
    bundle = get_rqalpha_bundle_path()
    if bundle is None:
        return {"ok": False, "detail": "not configured"}
    missing = [name for name in ("futures.h5", "instruments.pk") if not (bundle / name).is_file()]
    if missing:
        return {"ok": False, "detail": f"{bundle} lacks {', '.join(missing)}"}
    return {"ok": True, "detail": str(bundle)}


def _shipped() -> dict[str, object]:
    directory = PROJECT / "china_cta" / "factors" / "qualified"
    if not directory.is_dir():
        return {"ok": False, "detail": "package folder missing"}
    count = sum(1 for child in directory.iterdir() if (child / "signals.parquet").is_file())
    return {"ok": count > 0, "detail": f"{count} packages ship their signal table"}


def _tuned() -> dict[str, object]:
    directory = PROJECT / "results" / "tuning" / "qualified4_300"
    if not directory.is_dir():
        return {"ok": False, "detail": f"missing {directory}"}
    found = sum(1 for child in directory.iterdir() if (child / "best_params.json").is_file())
    return {"ok": found > 0, "detail": f"{found} tuned factors"}


def main() -> int:
    paths = describe_paths()
    inputs = _research_inputs()
    bundle = _bundle()
    checks: list[tuple[str, bool, str]] = [
        ("python", sys.version_info >= (3, 11), sys.version.split()[0]),
        ("research_inputs", bool(inputs["ok"]), str(inputs["detail"])),
        ("rqalpha_bundle", bool(bundle["ok"]), str(bundle["detail"])),
        ("shipped_signals", bool(_shipped()["ok"]), str(_shipped()["detail"])),
        ("tuned_params", bool(_tuned()["ok"]), str(_tuned()["detail"])),
    ]
    for name in CORE_PACKAGES:
        checks.append((f"pkg:{name}", _installed(name), "installed" if _installed(name) else "missing"))
    optional = {name: _installed(name) for name in OPTIONAL_PACKAGES}
    for name, ok in optional.items():
        checks.append((f"opt:{name}", ok, OPTIONAL_PACKAGES[name] + ("" if ok else " (unavailable)")))

    print("paths")
    for key, value in paths.items():
        print(f"  {key:16s} {value or '-'}")
    print()
    print("capabilities")
    for name, ok, detail in checks:
        print(f"  {name:20s} {'OK  ' if ok else 'MISS'} {detail}")

    available = {
        "cache": bool(inputs["ok"]),
        "bundle": bool(bundle["ok"]),
        "rqdatac": optional["rqdatac"],
        "torch": optional["torch"],
        "optuna": _installed("optuna"),
        "tuned": bool(_tuned()["ok"]),
        "shipped": bool(_shipped()["ok"]),
        "results": (PROJECT / "results").is_dir(),
    }
    available["rqdatac_or_bundle"] = available["rqdatac"] or available["bundle"]

    runnable: list[str] = []
    blocked: list[tuple[str, str, list[str]]] = []
    for stage, label, needs in STAGE_REQUIREMENTS:
        missing = [need for need in needs if not available.get(need, False)]
        if missing:
            blocked.append((stage, label, missing))
        else:
            runnable.append(stage)

    print()
    print("runnable: " + " ".join(runnable))
    for stage, label, missing in blocked:
        print(f"blocked:  {stage} {label} -> needs {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
