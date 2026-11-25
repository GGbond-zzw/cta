# 流水线

所有阶段都是独立脚本，按编号顺序执行。每一步只读取上一步的产物，不做隐式状态传递。

| 阶段 | 脚本 | 作用 | 输入 → 产物 |
| --- | --- | --- | --- |
| 00 | `00_doctor.py` | 环境自检：路径、依赖、数据、bundle，列出本机可跑的阶段 | 无 → 终端报告 |
| 10 | `10_fetch_research_inputs.py` | 从 RQData 取六个研究输入 | RQData → `data/research_inputs/cta_alpha22/` |
| 11 | `11_setup_linux_env.sh` | 在 WSL2 里建虚拟环境并装依赖 | 无 → `.venv-linux/` |
| 12 | `12_add_open_from_bundle.py` | 用本地 bundle 给连续价格补 `open` 列（备用路线） | bundle + 已有输入 → 就地更新 |
| 15 | `15_select_liquid_universe.py` | 每月流动性筛选，产出固定 30 品种池（口径见 `docs/LIQUIDITY_UNIVERSE.md`） | 快照行情 → `results/liquidity_monthly_*/` |
| 20 | `20_rebuild_inputs_from_bundle.py` | 完全用 bundle 重建六个输入（无 RQData 时） | bundle → 新输入目录 |
| 30 | `30_tune_factors.py` | 单进程 Optuna 调优（默认 300 trials，`signal_scale` 参与） | 输入 → `results/tuning/<run>/` |
| 31 | `31_tune_factors_by_process.py` | 每因子一个进程的并行调优 | 输入 → `results/tuning/<run>/` |
| 32 | `32_verify_tuning_outputs.py` | 校验调优产物完整性（trial 数、参数、约束） | 调优目录 → 报告 |
| 40 | `40_correlation_report.py` | 因子日收益与信号截面相关性 | 输入 + 调优目录或因子包 → CSV/图 |
| 50 | `50_backtest_portfolio.py` | 研究层等权组合回测（连续敞口、1bp） | 输入 + 参数 → `results/<run>/` |
| 60 | `60_render_run_chart.py` | 画某次 run 的净值对比图 | `results/<run>/` → PNG |
| 70 | `70_native_backtest.py` | 原生账户结果层（整数手、保证金、滑点、手续费） | 输入 + bundle + 因子包 → `results/<run>/` |

## 阶段 70 的常用参数

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `--package-factors` | `none` | `all`／`qualified`／`none`／逗号列表：从仓库内因子包构建 |
| `--factors` | 四个手写因子 | 从调优目录读取参数的手写因子 |
| `--capital` | 5000 万 | 初始资金 |
| `--margin-budget` | 0.50 | 保证金预算占**实时权益**比例 |
| `--slippage-ticks` | 1.0 | 成交价滑点（跳数） |
| `--volume-percent` | 0.25 | 单笔成交量占上一交易日成交量上限 |
| `--vol-target` | 0.20 | 目标年化波动（用在校准上） |
| `--calibration` | `rolling` | `rolling`（250 日慢速反馈）或 `one-shot`（一次性） |
| `--books` | `all` | 是否为每个 sleeve 单独跑一个子账户 |

## 参数来源

- 四个手写因子：`results/tuning/qualified4_300/<因子>/best_params.json`（300 次贝叶斯调优的最优点），已固化到各包的 `parameters.json`
- 五个表达式因子：`crowded_trend_reversal_60d` 由包内公式现算；其余四个把成品信号 `signals.parquet` 放在各自包内（表达式、方向与尺度见 `parameters.json`）
- `our_close_carry_smooth5`：固定参数（5 日平滑、scale 0.05、死区 0.05）

## 验收标准

1. `pytest tests` 全绿（离线可跑，缺可选依赖时会 skip）
2. `70` 的 `attribution_reconciliation.csv` 残差应接近 0（当前实现约 1e-5 元量级）
3. `daily_risk.csv` 的 `margin_over_equity` 中位数应在 20%~30%，且不应长期顶在 50%
4. 同一输入、同一参数重复运行，`daily_equity.csv` 应逐位一致
