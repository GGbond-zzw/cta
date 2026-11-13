# 原生账户结果层 + 报告（2026-11）

## 为什么

上一版把结果层换成了 RQAlpha 原生账户，但有两个问题：

1. **开盘竞价的 1 跳滑点其实没生效**。`rqalpha` 的
   `BaseMatcher._get_execution_price` 在 `open_auction=True` 时直接返回 deal price，
   完全跳过滑点模型；只配 `TickSizeSlippage(1)` 时成交价就是裸开盘价。
   证据：归因残差恰好等于滑点金额（678,415 元）。
2. 输出只有"两遍 + 单因子净值"，缺三段夏普、年度表、品种表、成本与逐笔记录。

## 改了什么

| 文件 | 改动 |
| --- | --- |
| `china_cta/formal_backtest/native_account.py` | 新增 `_install_opening_slippage(ticks, tick_sizes)`，替换 `DefaultBarMatcher._open_auction_deal_price_decider`，把 1 跳烘进成交价；tick 由 bundle `future_info.json` 按品种传入。新增带方向的持仓快照、`segment_metrics()`、`attribute_pnl()`、`write_attribution()`。 |
| `scripts/70_native_backtest.py` | 原 `60_native_backtest.py` 改名（编号与 `60_render_run_chart.py` 冲突）；新增 `--factor-books`、`segments(_by_book).csv`、`by_year(_by_book).csv`、`by_instrument(_by_book).csv`、`equity_comparison.png`。 |
| `tests/test_native_account.py` | 新增 6 个纯函数测试（sleeve 合并、手数取整、保证金预算、指标、三段切分、归因恒等式）。 |
| `tests/test_environment_contract.py` | 拆成核心依赖（必须装）与厂商 SDK（缺失即跳过），不再把 `rqalpha-plus`/`rqfactor` 当成硬依赖。 |
| `tests/test_formal_backtest*.py` | 旧 RQAlpha Plus 适配器的测试改为 `importorskip`，避免被策略拦截时整库收集失败。 |
| `tests/test_liquid_futures_monthly.py` | 指向改名后的 `scripts/15_select_liquid_universe.py`。 |
| `china_cta/formal_backtest/__init__.py.legacy` | 删除（不再有引用）。 |
| `README.md`、`docs/PIPELINE.md`、`docs/NATIVE_ACCOUNT_SPEC.md` | 补结果层章节、阶段 70、最新数字与滑点坑。 |

## 结果（2016-01-04..2026-09-04，2593 个交易日，5000 万 / 50% 保证金 / 1 跳 / 原生手续费）

| 版本 | 夏普 | 年化 | 波动 | 最大回撤 |
| --- | --- | --- | --- | --- |
| pass1（研究杠杆原样） | 1.4502 | 13.19% | 8.81% | −9.05% |
| pass2（校准 ×2.270） | 1.3532 | 18.51% | 13.19% | −15.05% |

三段（pass2）：训练 1.7097 / 验证 0.5157 / 测试 0.9250。

摩擦：手续费 745 万（14.90%×C0）、滑点 2,593 万（51.86%×C0），合计占毛收益 12.3%。

## 验证

- `attr attribution_reconciliation.csv` 残差 −1.2e-05 元（约 2e-13×C0），账户权益与归因逐分对齐。
- 滑点落地抽查：AG2502 7631→7632、AL2502 19920→19925、AU2504 627.04→627.06、CF2505 13560→13555。
- `pytest tests` → **165 passed, 16 skipped**；`compileall china_cta scripts tests` exit 0。
- 回归：补上滑点后 pass2 由 1.4706 降到 1.3532，说明旧数字确实透支了滑点。
