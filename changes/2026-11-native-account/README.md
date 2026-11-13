# 2026-11 原生账户结果层

## 为什么改

用户要求"对外结果层以 RQAlpha Plus 原生账户为准"：整数手、保证金、成交量上限、
5000 万资金、50% 保证金预算、trunc 取整、1 跳滑点、原生逐笔手续费。
此前 `results/final_4f_vol20*` 是向量化研究代理（连续敞口、1bp×换手成本估算），
与另一台电脑的原生结果不可比。

## 改了什么

| 文件 | 变化 |
| --- | --- |
| `china_cta/formal_backtest/native_account.py` | 新增：信号 → 目标手数（保证金预算 + trunc），RQAlpha 原生账户驱动，指标与落盘 |
| `china_cta/formal_backtest/__init__.py` | 改为导出原生账户接口（旧 `adapter` 保留为 `__init__.py.legacy` 依赖，不再默认导入，避免 `rqalpha_plus` 的 pyd 触发 Smart App Control） |
| `china_cta/data/rqalpha_bundle.py` | 新增 `load_trading_bars()`（含 settlement/limit/prev_settlement）、`load_future_info()`（手续费/保证金率/tick_size），`load_instruments()` 增加 `contract_multiplier` |
| `scripts/70_native_backtest.py` | 新增第 70 号流水线：构建四 sleeve → 研究代理杠杆 → 原生账户两遍（校准波动）→ 全部产物 |
| `docs/NATIVE_ACCOUNT_SPEC.md` | 新增口径清单（给另一台电脑对齐用） |

## 没改什么

因子定义、调优结果、sleeve 25% 等权、60 日 20% 波动目标、`50_backtest_portfolio.py`
的研究代理链路，全部保持原样；第 60 号是**新增**的一层，不替换第 50 号。

## 验证

- `pytest tests/qualified tests/unqualified tests/test_bayesian_tuning*.py` 仍通过（21 + 73 项）。
- 原生 pass2：2016-2025 夏普 1.518、波动 13.04%、最大回撤 −14.41%；2026 至 10-30 夏普 0.218。
- 与 stage 50 研究代理的日收益在 `shift(-1)` 下相关 0.82（相位差一天，属记账口径差异）。
- 手续费实测：2593 个交易日、67,282 笔成交、累计 755 万元。
