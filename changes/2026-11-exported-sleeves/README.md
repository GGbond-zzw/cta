# 2026-11 接入挖掘因子（exported sleeves）

## 为什么

同项目的另一台机器上用表达式搜索挖出了三个因子（原8号、原2号、上一轮新1号），导出成冻结信号包。
之前要用它们，只能在仓库外写一次性脚本把信号拼进回测；这一步把"外部信号"变成流水线的一等公民，
让 7 sleeve 组合能走和 4 sleeve 完全相同的原生账户口径。

## 改了什么

| 文件 | 改动 |
|---|---|
| `china_cta/factors/exported.py` | 新增。`ExportedSleeve` 登记表（名称、导出目录、挖掘编号、方向、尺度、表达式）、`resolve()`、`validate_package()`、`load_signals()`、`describe()` |
| `scripts/70_native_backtest.py` | 新增 `--extra-package` / `--extra-factors` / `--book-factors`；`_build_exported_sleeve()` 把冻结信号接成第 5..N 个 sleeve；`_book_selection()` 控制单因子账户；`config.json` 记录 sleeve 清单与权重；book 标签按 sleeve 数量生成（`equal_weight_7f`） |
| `docs/EXPORTED_SLEEVES.md` | 新增。命名规则、数据契约、与四因子合用时的口径 |
| `docs/PIPELINE.md` | 阶段 70 追加"追加挖掘因子"小节与示例命令 |

## 命名

| sleeve | 原标签 | 含义 |
|---|---|---|
| `crowded_trend_reversal_60d` | 原8号 | 趋势被"高位 × 高波动"推动时反向 |
| `volume_oi_coflow_10d` | 原2号 | 量仓同向流入的正动量 |
| `volume_burst_vol_reversal_60d` | 本轮1号 | 放量叠加波动放大后反转 |

## 没改什么

四因子的参数、信号、组合权重、成本与撮合口径都没有动；导出信号也不重新拟合方向或尺度。

## 验证

* 短窗口冒烟（2025Q1，1 个合格因子 + 1 个导出因子）：归因对账 `equity change = attributed net pnl`
  （误差 0），导出包中不在项目品种池的 `BU/C/FU/HC/RM` 被自动剔除并打印。
* 全样本（2016-01-04..2026-09-04，2593 个交易日，7 sleeve）：见
  `results/final_7f_native_vol20/` 的 `segments.csv`、`corr` 与 `equity_comparison.png`；归因残差
  与账户权益变化一致，`config.json` 里 `sleeves` 共 7 条、权重各 1/7。
