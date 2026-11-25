# china-cta 十因子期货 CTA 策略（可运行版）

本目录是项目的**最终可复现版本**：只有代码、配置、文档与因子所必需的成品信号，
不含中间过程记录、结果文件、数据文件与本地环境。

## 结果（对外口径）

十腿等权组合，原生 RQAlpha 期货账户，5,000 万本金、50% 保证金预算（按账户实时
权益）、开盘价 1 跳滑点、逐笔原生手续费，2016-01-04 .. 2026-09-04（2,593 个交易日）：

| 区间 | 夏普 | 年化 | 年化波动 | 最大回撤 |
|---|---:|---:|---:|---:|
| 全区间 | **1.78** | 40.6% | 20.3% | −26.6% |
| 训练 2016-2021 | 1.92 | 43.9% | 20.0% | −26.6% |
| 验证 2022-2024 | 1.50 | 29.1% | 18.2% | −14.8% |
| 测试 2025-2026 | 1.79 | 50.7% | 24.6% | −16.3% |

期末权益 16.66 亿（33.31 倍）；摩擦成本（手续费 8,490 万 + 滑点 2.74 亿）占毛利 18.2%。
逐年夏普 1.93 / 2.73 / 0.23 / 1.16 / 3.76 / 1.44 / 1.89 / 1.98 / 0.57 / 2.43 / 0.93。

## 快速开始

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
conda env create -f environment.yml               # 或按 pyproject.toml 用 pip 安装
python scripts/00_doctor.py                      # 检查环境与可跑阶段
```

能连米筐（RQData 网络授权）的机器：

```bash
python scripts/10_fetch_research_inputs.py --refresh --end 2026-10-30
python scripts/30_tune_factors.py --trials 300                # 可选，重新调参
python scripts/50_backtest_portfolio.py --factors <...> --weights 0.1 --vol-target 0.2
python scripts/70_native_backtest.py --package-factors qualified --book-factors none
```

不能连米筐、但有本地 RQAlpha bundle 的机器：把 `scripts/10` 换成
`scripts/20_rebuild_inputs_from_bundle.py` + `scripts/12_add_open_from_bundle.py`。

## 目录

```
china_cta/            策略包（数据层、11 个因子包、研究层回测、贝叶斯调优、原生账户）
scripts/              编号流水线 00/10/11/12/15/20/30/31/32/40/50/60/70
tests/                108 passed / 6 skipped
docs/                 口径、数据、流水线、原生账户规范、配置说明
config/               固定品种池、品种分类、本地配置样例
```

## 已知边界

- 原生账户结果层受本地 bundle 限制，止于 2026-09-04；研究层可到 2026-10-30。
- 四个表达式因子的成品信号随包携带（`signals.parquet`）：它们的公式依赖品种级量仓额
  聚合，本地只用主力合约口径重算只能得到 0.93–0.99 的相关，无法逐位还原。
- `our_reg35_transformer` 需要 PyTorch 与三个 `.pt` 权重，本仓库不含权重，默认跳过。
- 滑点按 1 跳建模，未包含冲击成本；换手越高的 sleeve 对成本假设越敏感。
