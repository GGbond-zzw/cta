"""The eleven qualified factors must each be a self-contained package."""

from __future__ import annotations

import json
from pathlib import Path

from china_cta.factors import cta_catalog
from china_cta.factors.qualified import BUILDERS

QUALIFIED = Path(__file__).resolve().parents[1] / "china_cta" / "factors" / "qualified"

EXPECTED = {
    "fixed_maturity_carry_90_180d",
    "historical_skewness_252d",
    "oi_participation_trend_60d",
    "xsmom_252_21",
    "our_close_carry_smooth5",
    "our_reg35_transformer",
    "crowded_trend_reversal_60d",
    "volume_burst_vol_reversal_60d",
    "turnover_surprise_channel_ratio",
    "inverse_oi_turnover_surprise_ratio",
    "volume_variability_weighted_reversal",
}


def test_builders_cover_the_eleven_factors() -> None:
    assert set(BUILDERS) == EXPECTED


def test_every_package_ships_factor_init_parameters_and_readme() -> None:
    for name in EXPECTED:
        package = next(
            (folder for folder in QUALIFIED.iterdir() if folder.is_dir() and (folder / "parameters.json").is_file()
             and json.loads((folder / "parameters.json").read_text(encoding="utf-8")).get("name") == name),
            None,
        )
        assert package is not None, f"no package directory declares {name}"
        for required in ("factor.py", "__init__.py", "parameters.json", "README.md"):
            assert (package / required).is_file(), f"{package.name} misses {required}"


def test_catalog_matches_the_packages() -> None:
    names = [spec.name for spec in cta_catalog.FACTOR_SPECS]
    assert len(names) == 11 and set(names) == EXPECTED
    assert set(cta_catalog.AVAILABLE_FACTORS) == EXPECTED - {"our_reg35_transformer"}
    assert cta_catalog.UNAVAILABLE_FACTORS == ("our_reg35_transformer",)
