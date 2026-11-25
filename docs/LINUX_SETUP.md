# 在 Linux（WSL2）里取数

## 1. 为什么需要

Windows 的**智能应用控制（Smart App Control）**会拦截 RQData 客户端里未签名的扩展模块，
表现为 `ImportError: DLL load failed while importing connection: 应用程序控制策略已阻止此文件`。
这是系统级策略，不是 Python 环境问题，重装包也无法绕过。WSL2 里没有这层策略，可以正常取数。

## 2. 安装

以管理员身份打开 PowerShell：

```powershell
wsl --install -d Ubuntu-24.04
```

安装完成后重启，首次进入设置用户名密码。

## 3. 依赖

在 WSL 里进入项目目录后执行：

```bash
bash scripts/11_setup_linux_env.sh
```

脚本会创建 `.venv-linux/`、安装 `rqdatac`、`pandas`、`pyarrow` 等依赖，并验证 `import rqdatac`。

## 4. 授权

授权是网络授权（不绑定机器），可以在 Windows 与 WSL 之间共用同一个值：

```bash
printf "%s" "$RQDATAC_CONF" > ~/.rqdatac_conf
chmod 600 ~/.rqdatac_conf
```

如果在 PowerShell 里设置后再进 WSL，注意用 `WSLENV=RQDATAC_CONF` 透传，
并且**用 `printf` 而不是管道重定向**写文件——Windows 换行符会破坏 URI 校验。

## 5. 取数

```bash
.venv-linux/bin/python scripts/10_fetch_research_inputs.py --start 2016-01-01 --end 2026-11-01 --refresh
```

注意：WSL 里跑脚本要保证 `PYTHONPATH` 含项目根目录（`export PYTHONPATH="$PWD"`），
否则会报 `ModuleNotFoundError: No module named 'china_cta'`。

## 6. 验证

1. `continuous_prices` 行数应等于"交易天数 × 品种数"（30 品种、2016 起约 70,000+ 行）；
2. `open` 列不应有缺失；
3. 与旧版输入对照，**日收益**应逐位一致，价格水平差异来自复权基准。
