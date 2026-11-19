# 2026-11 十腿组合（4 手写 + 6 挖掘）

## 为什么

二轮四因子导出包交付后，需要把它和既有 sleeve 合成一个组合评估。原 7 腿组合里的
`volume_oi_coflow_10d` 在样本外为负（−0.27）且没有可调维度，按用户要求退出组合；
其余六条与新四条合成十腿等权。

## 改了什么

| 文件 | 改动 |
|---|---|
| `china_cta/factors/exported.py` | 登记表扩到 7 条（新增二轮四条），每条带 `package` 标记；新增 `locate()` 支持多包混装；`validate_package` 同时接受 `factor_name` 与旧版 `name` |
| `scripts/70_native_backtest.py` | `--extra-package` 可重复，按 sleeve 逐个定位所属包；`config.json` 记录 `exported_packages` 列表 |
| `scripts/40_correlation_report.py` | 新增 `--extra-package` / `--extra-factors`，相关性分析覆盖挖掘 sleeve；保存 `sleeve_daily_returns.csv`、`sleeve_metrics.csv`、`equal_weight_research.csv`；修正热力图只标注四个名字的 bug |
| `docs/EXPORTED_SLEEVES.md` | 登记表、多包用法、十腿结果 |
| `docs/PIPELINE.md` | 阶段 40/70 的多包说明 |

## 验证

* 混装冒烟（3 条 sleeve、9 个交易日）：归因 `equity change == attributed`，逐笔成交带
  `product / night_session / execution_time`。
* 十腿全量（2593 个交易日，68415 个持仓日、68,627 笔成交）：归因零残差
  （1,383,384,203 = 1,383,384,203），手续费 9,189 万、滑点 3.07 亿。
* 相关性面板 10×10，日收益覆盖 2016-01-06..2026-10-30（2626 天）。
* `pytest tests` 通过（新增逻辑有单测覆盖的部分保持绿）。
