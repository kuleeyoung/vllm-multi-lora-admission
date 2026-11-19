# 复现短前缀消融

## CPU 离线复核

在解压后的复核包目录运行 `python -E -S -m bench.audit_g3 results/g3`。全部七组应重算出 49 张匹配的统计表。只关注短前缀时，加 `--suite prefix-order-01`，应得到 12 轮、768 条请求和 9 张匹配表。 [复核包说明](g3-audit-bundle.md)

## 单卡 GPU 复跑

验证环境为 WSL2、Python 3.12、RTX 5070 和 vLLM 0.33.0。运行前用 `nvidia-smi` 确认 GPU 可见。首次安装需要访问 Python 软件包源和模型仓库，需要为运行环境、缓存和模型留出磁盘空间。

在源码目录运行，两个参数都使用尚不存在的目录。

```bash
LORA_PORT=8021 bash scripts/replay_prefix_clean.sh \
  "$HOME/work/vllm-lora-prefix-replay" results/g3/prefix-clean-replay
```

脚本依次创建 venv、安装 [锁定依赖](../env/requirements-wsl.txt)、运行 `pip check` 并比对 `pip freeze`，随后准备固定 revision 的 Qwen3-0.6B、生成四个合成 rank 8 LoRA。在新工作目录保留安装日志。回放脚本用 [调度器哈希](../env/g0-runtime.json) 核对安装源码，构建只供实验进程使用的观测副本。默认由当前用户的包和模型缓存加速重复下载。

复跑固定 seed 26813，共 4 轮，每轮 64 条请求。重点核对两个容量档的首次满额集合、共同后缀的冷热排队 P95 和身份校验。延迟会随环境和运行状态变化。离线复核用于从原始记录重算归档数字，GPU 复跑用于再次执行相同输入和检查机制。

| 输出文件 | 可核对的内容 |
|---|---|
| 每档的 `server.log` 与 `events.jsonl` | 启动版本、实际 LoRA 容量、逐请求入队、准入与完成 |
| 每场景的 `trajectory.json` 与 `client.jsonl` | 发送计划、请求身份、token 数和 SLO 字段 |
| `arrival-order-runs.csv` 与 `arrival-order-pairs.csv` | 首次满额集合、逐 LoRA 排队 P95 与共同后缀对照 |
| `capacity-boundary-pairs.csv` | 同前缀的 L2/L3 容量对照与 KV 预算 |

早期入口仍可按 [G1 基线报告](g1-baseline.md)、[G2 策略实验](g2-policy.md)和 [G3 正式评估](g3-evaluation.md)复跑。服务启动与回退见 [服务配置](serving-option-a.md)。

## 干净工作目录验收

2026-11-19 新建工作目录与 venv，重新安装锁定的 199 项依赖、下载固定 revision 的模型并生成适配器。依赖快照一致，四个适配器的哈希与四个回放轨迹的哈希均与归档一致。4 轮共 256 条请求全在测量窗内完成，无抢占。

| 容量 | 热前缀 → 冷前缀的首次满额集合 | 后缀热门 P95 变化 | 后缀冷门 P95 变化 |
|---|---|---:|---:|
| 两名额 | A/B → C/D | +12.52 秒 | −7.47 秒 |
| 三名额 | A/B/C → A/C/D | +2.42 秒 | −6.20 秒 |

表中变化为同容量下冷前缀减热前缀，方向与原归档对应种子一致。同前缀比较容量，三名额在热前缀下的 Goodput 增加 0.188 请求/秒，在冷前缀下减少 0.083 请求/秒。冷前缀的这个方向与原归档对应种子不同。短前缀影响排队的机制得到了再次观测，扩容后的 Goodput 仍随运行状态变化。本机输出位于 `results/g3/portfolio-clean-01/`。
