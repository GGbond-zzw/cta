# 数据

## 1. 输入表

位于 `data/research_inputs/cta_alpha22/`（可用 `CTA_RESEARCH_INPUT_DIR` 改）。行数按 2026-10-30 的版本统计。

| 文件 | 行数 | 用途 |
| --- | ---: | --- |
| `continuous_prices.parquet` | 70,782 | 主力连续价格（含 `open/close/high/low/volume/open_interest`），因子与撮合都用它 |
| `contract_snapshots.parquet` | 771,801 | 真实合约日快照（收盘价、持仓量、到期日），期限结构类因子用 |
| `dominant_map.parquet` | 70,782 | 每日每品种的主力合约（`rule=0, rank=1`） |
| `universe.parquet` | 70,782 | 每日每品种是否可交易（`eligible`）及原因 |
| `member_rank.parquet` | 2,729,398 | 会员多空持仓排名（历史研究用，当前十条腿不依赖） |
| `warehouse_stocks.parquet` | 64,558 | 注册仓单 |

## 2. 关键列

`continuous_prices`：`trading_date, underlying_symbol, close, open, high, low, volume, open_interest`。
前复权口径（`adjust_type=pre`、`adjust_method=prev_close_ratio`），价格带 attrs：
`usage=signal_research_only`、`cash_pnl_allowed=False`。

`contract_snapshots`：`trading_date, underlying_symbol, order_book_id, maturity_date, days_to_maturity, price, price_field, open_interest`，
`price_field` 恒为 `close`（未复权真实合约收盘）。

`dominant_map`：`trading_date, product, dominant_order_book_id`。
`universe`：`trading_date, instrument, eligible, reason`（`reason` 取 `eligible` / `insufficient_listing_history` / `insufficient_liquidity`）。

## 3. 生成方式

| 文件 | 生成脚本 |
| --- | --- |
| 六个基础输入（RQData 路线） | `scripts/10_fetch_research_inputs.py` |
| 六个基础输入（bundle 路线） | `scripts/20_rebuild_inputs_from_bundle.py` |
| 补 `open` 列 | `scripts/12_add_open_from_bundle.py` |
| 固定 30 品种池 | `scripts/15_select_liquid_universe.py` |

## 4. 约定

- **交易日**：以价格面板里的 `trading_date` 为准，不额外读交易日历；每个因子的窗口都按面板内的交易日计。
- **品种代码**：连续价格与快照用 `underlying_symbol`（品种级），快照另有 `order_book_id`（合约级）；挖掘因子的特征在品种级聚合后使用。
- **缺失**：不填充、不前向复制；窗口不满则该日不出信号。
- **时点**：所有因子只用 T 日及更早的数据；T 日收盘出信号，T+1 开盘成交。

## 5. 质量校验

变更数据后建议跑三项核对：

1. `continuous_prices` 与 `contract_snapshots` 的主力合约收盘价在重叠日应完全一致；
2. 新旧两版输入的**日收益**应逐位一致（价格水平可能因复权基准不同而变化，收益不应变化）；
3. `open/close` 比值分位应落在 0.95–1.05 区间，异常值说明复权或对齐有问题。
