# china-cta 项目总览

> 更新于 2026-11-24。本文是项目的单一入口：做了什么、口径是什么、结果是多少、边界在哪。
> 细节文档：`docs/PIPELINE.md`（分阶段流程）、`docs/NATIVE_ACCOUNT_SPEC.md`（原生账户口径清单）、
> `docs/DATA.md`（数据契约）、`docs/CONFIGURATION.md`（机器配置）。

## 1. 项目定位

商品期货 CTA 的**研究 + 回测**系统，一条完整可复现的链路：

```
RQData 取数 → 11 个单因子包 → 贝叶斯调优 → 相关性体检 → 组合
        → RQAlpha 原生账户回放（整数手 / 保证金 / 量上限 / 1 跳滑点 / 原生手续费）
        → 三段与逐年归因、成本与交易明细、净值对比
```

不产生交易指令、不接实盘接口；产出是"这套因子组合在真实撮合约束下值多少夏普、钱怎么赚的、钱花在哪"。

## 2. 目录结构

```
china_cta/
  data/            取数适配（rqdata_adapter / contracts / liquidity_screen / rqalpha_bundle）
  factors/
    qualified/     11 个单因子包，每包 factor.py + parameters.json + README.md
    schema.py panel_features.py cta_catalog.py
  research/        fast_backtest（向量化研究层） bayesian_tuning（TPE）
  portfolio/       allocation / volatility（Phase 5 目标持仓，原生层不依赖）
  formal_backtest/ native_account（RQAlpha 账户回放）+ results（指标计算）
scripts/           编号流水线：10 取数 · 12 补开盘价 · 15 选池 · 20 bundle 重建
                   30/31 调优 · 32 校验 · 40 相关性 · 50 研究层组合
                   60 画图 · 70 原生账户回测
tests/             108 passed / 6 skipped（`--basetemp` 见第 9 节）
docs/               文档
data/  results/    数据与结果，不进仓库
```

## 3. 数据

| 表 | 内容 | 覆盖 |
|---|---|---|
| `continuous_prices` | 主力连续价（open/high/low/close/volume/OI） | 2016-01-04 .. 2026-10-30 |
| `contract_snapshots` | 真实合约收盘价、到期日、OI | 同上 |
| `dominant_map` | 每日主力合约（rule 0 / rank 1） | 同上 |
| `universe` | 当日可交易品种（上市满 120 日 + 流动性） | 同上 |
| `member_rank` | 会员持仓（仅历史因子用，十腿不依赖） | 同上 |

- 复权口径：`pre` + `prev_close_ratio`，与 RQData 一致（用变体 B 链式重建可逐位复现，见 `docs/DATA.md`）。
- 开盘价：首选 RQData 原生 `open`（WSL + 网络授权取数）；离线回退用 RQAlpha bundle 的 `open × cached_close / raw_close`。
- 原生账户需要**逐合约**行情，来自本地 RQAlpha bundle，因此结果层止于 bundle 最后交易日 **2026-09-04**（研究层可到 2026-10-30）。

## 4. 因子库（11 个包）

| 包 | 类型 | 参数来源 | 状态 |
|---|---|---|---|
| `fixed_maturity_carry_90_180d` | 期限结构 carry（80/170 日插值） | 本地 300 次调优 | 合格 |
| `historical_skewness_252d` | 截面偏度反转（441 日） | 本地 300 次调优 | 合格 |
| `oi_participation_trend_60d` | 趋势 × 持仓参与度 | 本地 300 次调优 | 合格 |
| `xsmom_252_21` | 截面动量（246/53） | 本地 300 次调优 | 合格 |
| `crowded_trend_reversal_60d` | 拥挤趋势反转（表达式） | 包内公式现算 | 合格 |
| `volume_burst_vol_reversal_60d` | 放量波动反转（表达式） | 包内成品信号 | 合格 |
| `turnover_surprise_channel_ratio` | 换手意外 × 通道（表达式） | 包内成品信号 | 合格 |
| `inverse_oi_turnover_surprise_ratio` | 持仓/换手意外倒数（表达式） | 包内成品信号 | 合格 |
| `volume_variability_weighted_reversal` | 量能波动加权反转（表达式） | 包内成品信号 | 合格 |
| `our_close_carry_smooth5` | 近月 close carry 的 5 日平滑 | 规格固定参数 | 合格（十腿计入） |
| `our_reg35_transformer` | 挖掘：三种子正则 Transformer | 需 `.pt` 权重 + torch | **不可用** |

- 参数唯一来源是各自 `parameters.json`（含 `parameter_source`），不再有"模块默认值"第二条路径。
- 每个包自带 `factor.py`、`parameters.json`、`README.md`；表达式搜索产出的包在同目录携带 `signals.parquet`（sha256 与行数记在 `parameters.json`），`build()` 直接读取，不依赖研究输入。

## 5. 调优

- 引擎：Optuna TPE（`multivariate=True, group=True, n_startup_trials=10`），按因子独立 study，sqlite 可续跑。
- 政策：**新因子默认 300 次，且 `signal_scale` 参与调优**（`scripts/30_tune_factors.py` 默认值已改）。
- 窗口：训练 2016-01-04..2021-12-31（约 1461 日），样本外 2022-01-04..2025-12-31；约束 `MIN_OBSERVATIONS=10000`、`MAX_DRAWDOWN=-0.40`、`MAX_TURNOVER=0.50` 只在训练期计算。
- 历史教训：
  - `signal_scale` 是裁剪阈值，调小等于少持仓省成本，曾把 carry_ann 训练夏普从 0.88 推到 1.38 而样本外从 0.51 掉到 0.26 —— 采纳前必须同时看换手与成本占比。
  - 三个挖掘 sleeve 的 300 次调优在样本外全部变差（0.945→0.652、1.065→0.394、−0.272 无改善），因此保留固定参数。
- `results/tuning/qualified4_300/` 保留 trial 级记录，可用于复算。

## 6. 结果层口径（对外数字都按这一层）

**研究层**（`scripts/50_backtest_portfolio.py`）：向量化、单账本、次日开盘到次日开盘、1bp × 换手。用于因子体检与组合构建，不是对外口径。

**原生账户层**（`scripts/70_native_backtest.py`，RQAlpha 6.x + 本机 bundle）：

| 项目 | 取值 |
|---|---|
| 初始资金 / 保证金预算 | 5,000 万 / 每日权益的 50%（`margin_basis="live_equity"`） |
| 手数 | `trunc(名义 / (结算价 × 合约乘数))`，超预算同比例缩放后取整 |
| 成交时点 | 信号日为 T，T+1 首个交易时段开盘；有夜盘的品种即 T 日 21:00 |
| 滑点 | 1 跳（`tick_size` 按品种），**开盘竞价分支需手动注入**（RQAlpha 原生会跳过滑点模型） |
| 手续费 | 原生逐笔（19/30 品种按手数计费） |
| 成交约束 | 上一日成交量的 25% 上限、涨跌停、强制平仓 |
| 波动目标 | 20%，**慢速因果校准**：`k_t = 20% / 过去 250 日实现波动`，上限 2.0，预热期 k=1 |
| 标记 | 收盘价盯市（`futures_settlement_price_type="close"`），结算价只用于手数与保证金 |

## 7. 最终结果（十腿等权）

| 分段 | 夏普 | 年化 | 年化波动 | 最大回撤 |
|---|---:|---:|---:|---:|
| 训练 2016-01-04 .. 2021-12-31 | 1.92 | 43.9% | 20.0% | −26.6% |
| 验证 2022-01-04 .. 2024-12-31 | 1.50 | 29.1% | 18.2% | −14.8% |
| 测试 2025-01-02 .. 2026-09-04 | 1.79 | 50.7% | 24.6% | −16.3% |
| **全区间** | **1.78** | **40.6%** | **20.3%** | **−26.6%** |

- 期末权益 16.66 亿（50M 的 33.3 倍），2,593 个交易日，68,792 笔成交，每日 27 个合约。
- 逐年夏普：1.93 / 2.73 / 0.23 / 1.16 / 3.76 / 1.44 / 1.89 / 1.98 / 0.57 / 2.43 / 0.93（无负年份，2018 最弱）。
- 摩擦：手续费 84.9M + 滑点 273.7M = 358.6M，占毛利 18.2%（约 5% 权益/年）。
- 风险占用：`gross/equity` 中位 2.46（最大 4.86）、`margin/equity` 中位 25.0%（最高 51.3%）。
- 各 book 对照（全区间夏普）：4 腿 1.35、6 腿 1.54、7 腿 1.57、9 腿 1.70、10 腿 1.78；4/6/7/9 腿用旧的一次性校准，口径不完全可比。

## 8. 已知局限

1. **样本外已被反复观察**：2022-2025 在因子筛选、参数选择、组合构成上都被用过多次，单次 study 的 OOS 干净，但"最终方案的 OOS 数字"有选择偏差。
2. **数据终点不对称**：研究层 2026-10-30、原生层 2026-09-04（bundle 限制）；2026 不足全年，年化指标需谨慎。
3. **成本模型偏乐观**：1 跳滑点不含市场冲击；25% 量上限是"上一日成交量"代理；未建模借券/资金成本。
4. **`our_reg35_transformer` 未纳入**：缺三个 `.pt` 权重且本机无 torch。
5. **慢速校准的滞后**：250 日窗口在体制切换时反应慢（2018 年 k=1.48 放大了回撤）；预热期（2016 年 16% 交易日）只有 11.2% 波动。
6. **换月口径**：风险/协方差用复权连续价，账户持真实合约；诊断显示组合层面影响可忽略（移仓日波动 27.3% vs 普通日 26.4%），但个券层面仍近似。
7. **调参自由度**：本地 4 个因子参数来自训练期调优，但"选哪 4 个因子"这一步本身用了全样本信息。

## 9. 复现

```powershell
# 1) 取数（Windows 需 WSL，rqdatac 被 Smart App Control 拦截时）
bash scripts/11_setup_linux_env.sh
wsl -d Ubuntu-24.04 -- bash /mnt/c/.../wsl_fetch.sh scripts/10_fetch_research_inputs.py --refresh

# 2) 因子体检与相关性
python scripts/40_correlation_report.py --tuned-dir results/tuning/qualified4_300 --out-dir results/tuning/factor_correlation_10f

# 3) 组合（研究层，快）
python scripts/50_backtest_portfolio.py --factors qualified --start 2016-01-04 --end 2025-12-31 --vol-target 0.2

# 4) 原生账户（对外口径，约 15 分钟）
python scripts/70_native_backtest.py --package-factors qualified --book-factors none ^
       --start 2016-01-04 --end 2026-09-04 --processes 4

# 5) 测试
pytest tests -q --basetemp=.pytest_tmp
```

注意：`ProcessPoolExecutor` 需要沙箱外运行；项目内 `.pytest_temp` 有 ACL 拒绝，必须显式 `--basetemp`。

## 10. 当前位置与下一步

**1.0 已完成**：11 个单因子包、可续跑调优、十腿组合、原生账户口径（整数手/保证金/量上限/1 跳/原生手续费/慢速校准）、三段与逐年归因、成本与交易明细、完整文档与变更记录。

**2.0 待做**（按价值排序）：

1. **样本外真检验**：冻结当前全部选择（因子、参数、权重、校准），2026-10 之后的数据只做观察，不再回头改。
2. **降换手**：摩擦占毛利 18.2%，其中挖掘 sleeve 日均换手 0.21–0.37。隔日/三日再平衡、信号死区、换手惩罚，是提升净值最直接的一条。
3. **权重优化**：当前等权。基于相关性矩阵做 cluster 风险平价（carry 簇、反转簇、量能簇），预期同波动下夏普 +0.05~0.10。
4. **补 transformer 因子**：补齐 `.pt` 权重并装 torch，把第 11 个 sleeve 纳入。
5. **冲击成本模型**：用实际成交量分位替代"1 跳 + 25% 上限"的粗近似。
