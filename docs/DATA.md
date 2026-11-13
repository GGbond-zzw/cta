# Data

## Tables

`data/research_inputs/cta_alpha22/` holds six parquet files:

| table | columns | used by |
| --- | --- | --- |
| `continuous_prices` | `trading_date, underlying_symbol, close, open, high, low, volume, open_interest` | every sleeve |
| `contract_snapshots` | `contract, trading_date, ..., maturity_date, days_to_maturity, open_interest, close` | carry, OI participation |
| `dominant_map` | `trading_date, underlying_symbol, contract` | continuous series construction |
| `member_rank` | member long/short ranks | historical research only |
| `universe` | `trading_date, instrument, eligible` | every sleeve |
| `warehouse_stocks` | registered warehouse stocks | basis/carry research |

Price adjustment follows RQData's `pre` / `prev_close_ratio` convention. The
`open` column is the first traded price of the trading day (the 21:00 night-session
open for night products), i.e. the earliest executable price after a close
signal. RQData does not deliver it, so `scripts/12_add_open_from_bundle.py`
reconstructs it from the local RQAlpha bundle as
`open = raw_open * cached_close / raw_close` and writes the column in place.
Rows the bundle does not reach can be filled with `close` through
`--fill-missing-with-close`; the parquet metadata then records
`open_source=bundle=N;close_fallback=M`. The current checkout was built that
way: 69,762 rows from the bundle and 1,020 rows (after 2026-09-04) filled with
close, out to 2026-10-30.

## Sources

* **RQData** (`china_cta/data/rqdata_adapter.py`): the original source for all
  six tables, driven by `scripts/10_fetch_research_inputs.py`. Requires
  `RQDATAC_CONF` / `RQDATAC2_CONF`.
* **RQAlpha bundle** (`.rqalpha/bundle/futures.h5` + `instruments.pk`): a local
  fallback that provides per-contract bars and maturity dates. It does not carry
  member rank, so `member_rank` is copied from the cached table and the OI
  participation sleeve uses total open interest, not member positions.

## Rebuilding an extension

```bash
python scripts/20_rebuild_inputs_from_bundle.py \
    --input-dir data/research_inputs/cta_alpha22 \
    --output-dir data/research_inputs/cta_alpha22_extended \
    --bundle C:/Users/ct/Desktop/python/CTA/Mikuang_data/.rqalpha/bundle \
    --extension-start 2026-01-01
```

The rebuild keeps the cached history unchanged and appends the extension with
the dominant contract chosen by open interest. It prints two validations:

* `chaining check`: continuous returns of the rebuilt 2016-2025 segment against
  the cache (expected correlation 1.000000, max absolute difference ~4e-16);
* `snapshot overlap`: rebuilt contract snapshots against the cache
  (expected 707,431/707,431 rows with zero price and OI difference).

Known limitation: RQData's dominant-contract rule is smoothed, while the rebuild
uses a pure open-interest argmax, so contract names agree on roughly 96.5% of
days, mostly around rolls. Continuous returns are unaffected because the
chaining uses each contract's own `prev_close`.

## Conventions

* Trading calendar: Chinese futures exchange sessions, 2016-01-04 onwards.
* Signal date `t` uses close prices; execution at open of `t+1`; evaluation
  window ends at open of `t+2`.
* Missing or ineligible instruments are dropped cross-sectionally; the sleeve
  return is the mean over names available on that date.
