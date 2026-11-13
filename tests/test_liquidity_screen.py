import pandas as pd

from china_cta.data.liquidity_screen import ScreenConfig, screen_products


def test_daily_score_uses_real_commodity_contracts_only():
    dates = [f"2025-01-{day:02d}" for day in range(1, 6)]
    master = pd.DataFrame([
        ("AA2501", "AA", "DCE", "Commodity", 10),
        ("AA2505", "AA", "DCE", "Commodity", 10),
        ("BB2501", "BB", "DCE", "Commodity", 5),
        ("IF2501", "IF", "CFFEX", "Index", 300),
        ("T2503", "T", "CFFEX", "Government", 10000),
        ("AA888", "AA", "DCE", "Commodity", 10),
    ], columns=["order_book_id", "underlying_symbol", "exchange", "product", "contract_multiplier"])
    bars = pd.DataFrame([
        (day, contract, volume, oi, 10)
        for day in dates
        for contract, volume, oi in [
            ("AA2501", 100, 200), ("AA2505", 50, 100),
            ("BB2501", 20, 40), ("IF2501", 10000, 10000),
            ("T2503", 10000, 10000), ("AA888", 10000, 10000),
        ]
    ], columns=["trading_date", "order_book_id", "volume", "open_interest", "settlement"])
    result = screen_products(master, bars, dates, ScreenConfig(window=5, top=1))
    assert result["underlying_symbol"].tolist() == ["AA", "BB"]
    assert result.iloc[0]["median_turnover_cny"] == 15000
    assert result.iloc[0]["median_oi_notional_cny"] == 30000
    assert result["selected"].tolist() == [True, False]


def test_missing_settlement_fails_price_coverage():
    dates = [f"2025-01-{day:02d}" for day in range(1, 6)]
    master = pd.DataFrame([("AA2501", "AA", "DCE", "Commodity", 10)],
                          columns=["order_book_id", "underlying_symbol", "exchange", "product", "contract_multiplier"])
    bars = pd.DataFrame([(day, "AA2501", 100, 200, float("nan")) for day in dates],
                        columns=["trading_date", "order_book_id", "volume", "open_interest", "settlement"])
    result = screen_products(master, bars, dates, ScreenConfig(window=5, top=1))
    assert "insufficient_price_coverage" in result.iloc[0]["exclusion_reason"]
