"""The qualification registry must describe exactly the nine-sleeve book."""

from __future__ import annotations

import pytest

from china_cta.factors import classification as registry
from china_cta.factors import exported


def test_the_book_has_nine_qualified_sleeves() -> None:
    assert registry.QUALIFIED_SLEEVE_COUNT == 9
    assert len(registry.QUALIFIED_SLEEVES) == 9
    assert len(set(registry.QUALIFIED_SLEEVES)) == 9


def test_the_four_package_sleeves_stay_qualified() -> None:
    assert registry.QUALIFIED_FACTORS == {
        "fixed_maturity_carry_90_180d",
        "historical_skewness_252d",
        "oi_participation_trend_60d",
        "xsmom_252_21",
    }


def test_five_exported_sleeves_are_qualified() -> None:
    assert registry.QUALIFIED_EXPORTED == (
        "crowded_trend_reversal_60d",
        "volume_burst_vol_reversal_60d",
        "turnover_surprise_channel_ratio",
        "inverse_oi_turnover_surprise_ratio",
        "volume_variability_weighted_reversal",
    )
    assert set(registry.QUALIFIED_EXPORTED) == {
        sleeve.name for sleeve in exported.qualified_sleeves()
    }


def test_retired_sleeves_are_kept_but_not_traded() -> None:
    assert set(registry.RETIRED_EXPORTED) == {
        "volume_oi_coflow_10d",
        "volume_channel_price_oi_volatility",
    }
    for name in registry.RETIRED_EXPORTED:
        assert registry.classification(name) == "retired"


def test_classification_labels() -> None:
    assert registry.classification("xsmom_252_21") == "qualified"
    assert registry.classification("crowded_trend_reversal_60d") == "qualified"
    assert registry.classification("volume_oi_coflow_10d") == "retired"
    assert registry.classification("breakout_55") == "unqualified"


def test_book_order_puts_package_sleeves_first() -> None:
    names = registry.qualified_sleeve_names()
    assert names[:4] == (
        "fixed_maturity_carry_90_180d",
        "historical_skewness_252d",
        "oi_participation_trend_60d",
        "xsmom_252_21",
    )
    assert len(names) == 9


def test_exported_resolve_accepts_the_qualified_sentinel() -> None:
    chosen = exported.resolve("qualified")
    assert len(chosen) == 5
    assert all(sleeve.status == "qualified" for sleeve in chosen)
    assert len(exported.resolve("retired")) == 2


def test_exported_registry_entries_carry_a_status() -> None:
    for sleeve in exported.EXPORTED_SLEEVES.values():
        assert sleeve.status in {"qualified", "retired"}
        assert sleeve.as_dict()["status"] == sleeve.status


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
