# 2026-11 nine qualified sleeves

## 为什么

到 2026-11，项目对外口径已经是"原生账户结果层 + 九条 sleeve 等权"，但代码里的
合格因子登记表还停留在四因子阶段：`china_cta/factors/classification.py` 只认四个手写
因子，五个挖掘 sleeve 只能通过命令行临时指定包目录，既不在登记表里，也没有测试守着。
本次把"合格 = 九条"这件事写进代码。

## 改了什么

| 文件 | 改动 |
|---|---|
| `china_cta/factors/exported.py` | `ExportedSleeve` 增加 `status`（`qualified` / `retired`）；`volume_oi_coflow_10d` 与 `volume_channel_price_oi_volatility` 标为 `retired` 并写明原因；新增 `QUALIFIED_EXPORTED_SLEEVES`、`RETIRED_EXPORTED_SLEEVES`、`qualified_sleeves()`；`resolve()` 接受 `qualified` / `retired` 两个集合名 |
| `china_cta/factors/classification.py` | 新增 `QUALIFIED_EXPORTED`、`RETIRED_EXPORTED`、`QUALIFIED_SLEEVES`（9 条，手写在前）、`QUALIFIED_SLEEVE_COUNT`、`qualified_sleeve_names()`；`classification()` 返回 `qualified` / `retired` / `unqualified` 三态 |
| `scripts/70_native_backtest.py` | `--extra-factors` 的帮助文本补上 `qualified` / `retired` 集合名 |
| `tests/test_qualification_registry.py` | 新增 8 个测试，锁住"九条 = 4 手写 + 5 挖掘"、两条退役、三态分类、集合名解析 |

## 没有改什么

- 研究层与原生账户的计算口径、成本、保证金、滑点一律未动。
- `bayesian_tuning.TUNING_SPECS` 仍是四个手写因子的调优空间（挖掘 sleeve 的参数是冻结的）。
- 退役的两条 sleeve 仍留在登记表里，只是不进组合，保证历史结果可复现。

## 验证

```
pytest tests/test_qualification_registry.py -q      # 8 passed
pytest tests -q --basetemp=<workspace>              # 175 passed, 16 skipped
python -m compileall -q china_cta scripts tests     # exit 0
```

复现九条组合：

```
python scripts/70_native_backtest.py \
  --factors historical_skewness_252d,fixed_maturity_carry_90_180d,xsmom_252_21,oi_participation_trend_60d \
  --extra-package C:\Users\ct\Desktop\一轮三因子 \
  --extra-package C:\Users\ct\Desktop\二轮四因子 \
  --extra-factors qualified \
  --book-factors none \
  --start 2016-01-04 --end 2026-09-04 \
  --out-dir results/final_9f_native
```
