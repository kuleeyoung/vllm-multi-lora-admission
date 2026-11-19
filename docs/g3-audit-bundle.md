# vLLM 多 LoRA · G3 离线复核包

解压后，在包含本文件的目录运行以下命令。Windows 可用 `python`，WSL 如只有 `python3`，将命令中的解释器名称替换即可。已验证 Python 3.12 和 3.14，运行只用标准库。

```text
python -E -S -m bench.audit_g3 results/g3
python -E -S -m bench.audit_g3 results/g3 --suite decision-matrix-01
python -E -S -m bench.audit_g3 results/g3 --suite prefix-order-01
```

新版包含正式评估、干净环境复跑、保护阈值、策略选型、容量边界、完整顺序消融和短前缀消融。预期共 111 轮、4,032 条归档请求、49 张统计表。旧版 ZIP 内含其对应的四组数据和复核代码。

在原项目中，原始输出为 `results/archive/vllm-multi-lora-g3-audit-v2.zip`。候选分享包为 `results/archive/vllm-multi-lora-g3-audit-share.zip`，将调度加载事件中的本机路径缩为文件名。使用源码候选包时，将独立复核 ZIP 解压到单独目录，并在该目录执行复算命令。

压缩包包含统计所需的冻结配置、轨迹、请求记录、调度事件、GPU 采样、参考统计表和 Python 分析代码。用于容量分析的 `server.log` 仅保留计算 KV Cache 容量所需的两条启动日志。事件中的本机源码路径是历史记录，运行分析时无须访问这些路径。每个文件的 SHA-256 保存在 `ARCHIVE-MANIFEST.sha256`，压缩包整体的 SHA-256 随 ZIP 另附。

运行时会重算排队延迟、Goodput、交接次数和选型指标，并与包内参考结果逐项对照。GPU 在线重测需要原项目中的模型、LoRA、环境与回放脚本。
