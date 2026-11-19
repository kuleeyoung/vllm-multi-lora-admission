# 选项 A 的本地服务入口与回退

用户选定三名额原版 B0 作为推荐配置，保留两名额原版 B0 回退。公共入口是 `scripts/serve.sh`。它显式设置 `max_loras`，清除实验观测副本所用的 Python 导入路径和策略变量，然后调用原有服务脚本。实验 runner 保留独立入口与冻结配置。

在 WSL 项目目录从前台启动推荐服务：

```bash
bash scripts/serve.sh
```

服务监听 `127.0.0.1:8018`，并发请求上限为 8，基础模型注册为 `Qwen/Qwen3-0.6B`，适配器为 A/B/C/D。回退时先在原终端按 Ctrl+C，等服务关闭后运行：

```bash
bash scripts/serve.sh --rollback
```

可用 `bash scripts/serve.sh --help` 核对参数。若使用其他本地端口，在启动前通过 `LORA_PORT` 设置，检查程序也读取同一变量。

以下复跑入口依次启动两档并做流式绑定检查，最后关闭测试服务。输出目录必须是新目录。

```bash
bash scripts/check_serving_profiles.sh results/serving/option-a-replay
```

三名额原版在项目的突发验证中较两名额更稳定地改善冷门排队；持续场景中整体 Goodput 改善而热门等待有所增加。遇到更紧的显存预算或持续流量优先保护热门等待时，可以使用两名额回退。本地服务配置采用项目现有 Qwen3-0.6B BF16 与四种 rank 8 LoRA。

## 落地验证

在 RTX 5070 的现有 WSL 环境顺序启动两个档位。启动日志确认推荐档为 `max_loras=3`、回退档为 `max_loras=2`。测试在调用入口前注入 `LORA_MAX_LORAS=4`，以确认入口按所选档位显式覆盖旧值。两档均通过九条流式验证，含基础模型、四个独立适配器和四路并发适配器请求。两档的独立输出参考都可区分，并发输出匹配各自参考。日志、逐请求 JSONL 和结果在 `results/serving/option-a-01/`。

测试服务已关闭。选型检查点归档保留，落地后的快照另存为 `results/archive/vllm-multi-lora-2026-11-18-option-a.zip`。

[连续运行与回退验收](serving-acceptance.md)进一步使用实际入口完成推荐档三轮、回退档一轮，共 184 条真实请求。
