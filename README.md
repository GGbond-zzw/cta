# china-cta：商品期货 CTA 因子研究流水线

十条腿等权组合，原生账户口径（5000 万本金、50% 保证金、1 跳滑点、逐笔手续费）：
**夏普 1.78、年化 40.6%、波动 20.3%、最大回撤 −26.6%**，2016-01 至 2026-09 无负收益年份。

## 仓库里有什么

- `china_cta/factors/qualified/`：10 个可运行的合格因子包（每个包自带 `factor.py`、`parameters.json`、`README.md`）
- `china_cta/research/`：向量化研究引擎（次日开盘撮合、1bp 成本）与贝叶斯调优
- `china_cta/formal_backtest/`：RQAlpha 原生期货账户（整数手、保证金、成交量上限、1 跳滑点、原生手续费）
- `scripts/00`–`scripts/70`：编号流水线，从取数到最终回测
- `tests/`：测试套件（`pytest tests` 在干净环境应为全绿）

## 对外口径：十条腿等权（原生账户）

| 区间 | 夏普 | 年化 | 波动 | 最大回撤 |
| --- | ---: | ---: | ---: | ---: |
| 训练 2016-01-04 ~ 2021-12-31 | 1.92 | 43.9% | 20.0% | −26.6% |
| 验证 2022-01-01 ~ 2024-12-31 | 1.50 | 29.1% | 18.2% | −14.8% |
| 测试 2025-01-01 ~ 2026-09-04 | 1.79 | 50.7% | 24.6% | −16.3% |
| 全区间 | **1.78** | 40.6% | 20.3% | −26.6% |

前提：5000 万初始资金、保证金预算为**实时权益**的 50%、整数手（trunc）、涨跌停与成交量上限、1 跳滑点、RQAlpha 原生逐笔手续费；2016-01-04 至 2026-09-04 共 2593 个交易日；30 个固定品种池。

全区间摩擦：手续费 8490 万 + 滑点 2.737 亿 = 3.586 亿，占毛利 18.2%（约年均权益的 5%）。

> 校准方式说明：默认 `--calibration rolling`（250 日慢速反馈）。若改为一次性校准 `--calibration one-shot`，同一本书为夏普 1.80、波动 20.0%、回撤 −21.3%——夏普几乎不变，差别只在杠杆路径。

## 目录结构

```
china_cta/
  data/            RQData 适配器、合约工具、流动性筛选、bundle 读取
  factors/         因子契约（schema.py）、catalog、qualified/（11 个单因子包）
  research/        fast_backtest.py（研究引擎）、bayesian_tuning.py（调优）
  portfolio/       滚动波动率工具
  formal_backtest/ native_account.py（原生账户回测）
scripts/           00 ~ 70 编号流水线
docs/              流水线与口径文档
tests/             测试
```

## 环境

- Python ≥ 3.11，依赖见 `pyproject.toml`
- 取数需要 RQData 授权（`RQDATAC_CONF` 或 `RQSDK_LICENSE`）
- 结果层需要本地 RQAlpha bundle（`futures.h5`、`instruments.pk`、`future_info.json`），路径用 `CTA_RQALPHA_BUNDLE_PATH` 指定
- 不依赖 `rqalpha_plus`：结果层用的是纯 Python 的 `rqalpha` 6.x

```bash
pip install -e .
python scripts/00_doctor.py     # 先看这台机器能跑哪些阶段
```

## 快速开始（能直连 RQData 的机器）

```bash
export RQDATAC_CONF="tcp://用户:密码@rqdatad-pro.ricequant.com:16011"

python scripts/10_fetch_research_inputs.py --start 2016-01-01 --refresh
python scripts/70_native_backtest.py --package-factors qualified \
    --start 2016-01-04 --end 2026-09-04 --out-dir results/final_book

# 可选：调优与相关性
python scripts/30_tune_factors.py --trials 300
python scripts/40_correlation_report.py --package-factors qualified
```

## 不能直连 RQData 时（本地 bundle 路线）

```bash
python scripts/20_rebuild_inputs_from_bundle.py     # 用 bundle 重建六个输入
python scripts/70_native_backtest.py --package-factors qualified
```

## 因子清单

| 包名 | 类型 | 一句话说明 |
| --- | --- | --- |
| `fixed_maturity_carry_90_180d` | 手写 | 80/170 天期限插值的 carry（多 backwardation、空 contango） |
| `historical_skewness_252d` | 手写 | 441 日收益偏度截面排名，做多负偏、做空正偏 |
| `oi_participation_trend_60d` | 手写 | 63/126/252 多周期趋势投票 × 持仓量参与度 |
| `xsmom_252_21` | 手写 | 246 日动量的截面排名（跳过最近 53 日） |
| `crowded_trend_reversal_60d` | 挖掘 | 趋势被"高位 × 高波动"推动时反向 |
| `volume_burst_vol_reversal_60d` | 挖掘 | 放量叠加波动放大后的反转 |
| `turnover_surprise_channel_ratio` | 挖掘 | 换手意外 × 通道位置比率 |
| `inverse_oi_turnover_surprise_ratio` | 挖掘 | 持仓/换手意外比率的反向 |
| `volume_variability_weighted_reversal` | 挖掘 | 成交量变异度加权的反转 |
| `our_close_carry_smooth5` | 新因子 | 近月与主力的收盘价 carry，5 日平滑、±5% 死区 |
| `our_reg35_transformer`（待启用） | 新因子 | 正则 Transformer，需要 PyTorch 与三个 `.pt` 权重，本仓库未附二进制权重 |

每个因子包自带 `factor.py` / `parameters.json` / `README.md`；由表达式搜索产出的 5 个包把成品信号放在同目录的 `signals.parquet`，`parameters.json` 记录它的 sha256 与行数。对使用者来说，它们与手写因子没有任何区别。

## 三个口径层级

1. **研究层**（`scripts/50`）：连续敞口、1bp 成本、开盘到开盘，只用于比较因子强弱。
2. **原生账户**（`scripts/70`）：整数手、保证金、成交量上限、1 跳滑点、原生手续费——对外结果。
3. **杠杆/校准**：研究层给定基础杠杆，原生层按实现波动做 250 日慢速校准，保证金上限为实时权益的 50%。

## 已知边界

- 原生层受本地 bundle 限制，行情止于 2026-09-04；研究层可用 RQData 更新到最新
- 1 跳滑点不含冲击成本，实际换手较大的因子收益会被高估
- 2022-2025 已被反复用于观察与决策，视为"已污染"的验证集
- `our_reg35_transformer` 未纳入组合（缺权重）

## 常见问题

- **`00_doctor.py` 报 research_inputs MISS**：先跑 `10`（或 `20`）生成输入。
- **`70` 报 `futures.h5` 找不到**：设置 `CTA_RQALPHA_BUNDLE_PATH` 指向 bundle 目录。
- **Smart App Control 拦截 `rqdatac`**：改到 WSL2 里取数，见 `docs/LINUX_SETUP.md`。
