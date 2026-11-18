# 成交时点标注（execution_time）

## 为什么改

RQAlpha 把所有日线成交都记成"交易日 T 00:00"。审计 `trades.csv` 时这会被读成"午夜成交"，
于是产生一个合理但错误的怀疑：信号是 T-1 日 15:00 收盘后生成的，为什么不在当晚 21:00 夜盘成交，
而要等到第二天？

结论是：**成交本来就发生在当晚 21:00**，只是标签没写清楚。期货日线 bar 覆盖整个交易日
（T-1 日 21:00 夜盘 + T 日 09:00 日盘），bar 的 `open` 就是这段时段的第一个成交价。

## 改了什么

| 文件 | 改动 |
|---|---|
| `china_cta/data/rqalpha_bundle.py` | `load_instruments` 多返回 `trading_hours` |
| `china_cta/formal_backtest/native_account.py` | 新增 `product_of` / `night_products` / `annotate_execution_time`；两个回放函数都接收 `night_products` 并给 `trades` 加 `product`、`night_session`、`execution_time` |
| `scripts/70_native_backtest.py` | 从 `market["instruments"]` 解析夜盘品种并传给回放 |
| `tests/test_native_account.py` | 覆盖夜盘/日盘两种换算与品种前缀解析 |
| `docs/NATIVE_ACCOUNT_SPEC.md` | 新增第 12 节，写清时点口径与判别方法 |
| `docs/PIPELINE.md` | 阶段 70 产物说明补上两个新列 |

## 验证

* `pytest tests/test_native_account.py` → 8 passed。
* 七因子账户 72,287 笔成交里 **94.0%** 落在"前一交易日晚 21:00"，其余为 `JD`/`LH` 的次日 09:00；
  四因子账户 70,097 笔里 93.7%。
* 独立核对：夜盘品种周一隔夜跳空倍率 1.36、纯日盘 2.08/2.87（`night_session_check.csv`）。

## 没有改什么

价格、滑点、手数、保证金、手续费与所有收益数字均不变，本次只是标注与文档。
