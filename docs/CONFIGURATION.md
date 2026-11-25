# 机器配置

本仓库**不含任何机器绝对路径**。所有与机器相关的位置都通过环境变量或 `config/local.json` 提供，
读取顺序为：**命令行参数 > 环境变量 > `config/local.json` > 默认值**。

## 1. 可配置项

| 变量 | 作用 | 默认值 |
| --- | --- | --- |
| `CTA_RESEARCH_INPUT_DIR` | 研究输入目录（六个 parquet） | `data/research_inputs/cta_alpha22` |
| `CTA_RESULTS_DIR` | 结果根目录 | `results` |
| `CTA_RQDATA_CACHE_DIR` | RQData 本地缓存 | `data/cache/rqdata` |
| `CTA_RQALPHA_BUNDLE_PATH` | RQAlpha bundle 目录（结果层与离线重建必需） | 无，未设置时相关阶段直接报错并提示 |
| `CTA_LOCAL_CONFIG` | 本地配置文件路径 | `config/local.json` |

示例 `config/local.json`（已在 `.gitignore` 中，不会进仓库）：

```json
{
  "research_input_dir": "data/research_inputs/cta_alpha22",
  "results_dir": "results",
  "rqdata_cache_dir": "data/cache/rqdata",
  "rqalpha_bundle_path": "/mnt/d/rqalpha/bundle"
}
```

也可以用命令行参数覆盖，例如 `scripts/70_native_backtest.py --bundle <路径>`。

## 2. 两条取数路线

两条路线的产物 schema 完全一致，后续阶段无需区分。

**路线 A：能直连 RQData**

```bash
export RQDATAC_CONF="tcp://用户:密码@rqdatad-pro.ricequant.com:16011"
python scripts/10_fetch_research_inputs.py --start 2016-01-01 --refresh
```

**路线 B：只能用本地 RQAlpha bundle（无授权、或在被策略拦截的机器上）**

```bash
export CTA_RQALPHA_BUNDLE_PATH=<bundle 目录>
python scripts/20_rebuild_inputs_from_bundle.py      # 完全用 bundle 重建六个输入
```

若已有 RQData 输入但缺 `open` 列（早期版本），用 `scripts/12_add_open_from_bundle.py` 补列即可。

## 3. 各阶段前置条件

| 阶段 | 需要 |
| --- | --- |
| `00_doctor.py` | 无 |
| `10` | RQData 授权 |
| `12` | 已有输入 + bundle |
| `14` | RQData 或 bundle |
| `15` | 快照行情 |
| `20` | bundle |
| `30` / `31` / `32` | 研究输入（`14` 的产物是挖掘因子的前提） |
| `40` / `50` | 研究输入 |
| `70` | 研究输入 + bundle |

## 4. 自检

```bash
python scripts/00_doctor.py
```

输出会列出四类信息：路径解析结果、可选依赖（如 `torch`）、关键数据是否存在、以及**本机可跑的阶段编号**。

## 5. 常见报错

| 报错 | 原因与处理 |
| --- | --- |
| `research inputs missing` | 先跑 `10` 或 `20` |
| `RQAlpha bundle not configured` | 设置 `CTA_RQALPHA_BUNDLE_PATH` |
| `rqdatac` 初始化失败 / DLL 被拦截 | 换到 WSL2 取数，见 `docs/LINUX_SETUP.md` |
