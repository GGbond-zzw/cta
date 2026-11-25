import json
from pathlib import Path

import pytest

from china_cta.data.fixed_universe import DEFAULT_FIXED_POOL_FILE, load_fixed_product_pool


def test_current_fixed_pool_has_thirty_unique_products():
    candidates = (
        DEFAULT_FIXED_POOL_FILE,
        Path(__file__).resolve().parents[1] / "config" / "fixed_pool_2026_09.json",
    )
    path = next((item for item in candidates if Path(item).is_file()), None)
    if path is None:
        pytest.skip("no fixed product pool snapshot in this checkout")
    pool = load_fixed_product_pool(path)
    assert pool.holding_month == "2026-09"
    assert len(pool.products) == len(set(pool.products)) == 30
    assert pool.run_suffix == "fixedpool_2026_09"
    assert "IF" not in pool.products


def test_invalid_fixed_pool_is_rejected(tmp_path: Path):
    path = tmp_path / "selected_products.json"
    path.write_text(json.dumps({
        "holding_month": "2026-09", "ranking_month": "2026-08",
        "daily_top_share": 0.6, "daily_lookback_days": 60,
        "monthly_ordering": "median of daily v2 liquidity scores",
        "products": ["AU"] * 30,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="30 unique"):
        load_fixed_product_pool(path)
