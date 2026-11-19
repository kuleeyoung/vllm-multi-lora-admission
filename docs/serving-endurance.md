# 选项 A 耐久运行与停服资源检查

上一次验收验证约 78 秒连续运行及真实回退。两档退出时 Python 都报告了 1 个 semaphore 的清理警告。本轮在同一台 WSL 机器上延长持续时间，并分别记录告警、旧进程是否退出和 `/dev/shm` 中可见的命名对象。

推荐档在同一 EngineCore 上连续运行 12 轮，每轮 32 条突发及 14 条持续请求。随后关闭并用回退档重启，重放一轮相同轨迹。负载、SLO 与身份校验延续短时验收。服务启动、每轮结束时采样 API/EngineCore 的 RSS、文件描述符和整卡显存。在两次启动前、运行中、退出后分别列出 `/dev/shm`。若退出后有新增对象，验证程序等待至多五秒再采一次。程序只读采样这些对象。

另做只启动再停服的对照，检查无生成请求时能否出现同一警告。这个对照会读取健康接口和模型列表，没有发送生成请求。它有助于区分服务生命周期的告警和压测期间新增的资源变化。

在 WSL 项目目录复跑：

```bash
python3 -m bench.validate_serving results/serving/option-a-endurance-replay \
  --config configs/serving-endurance.json
python -m bench.analyze_endurance results/serving/option-a-endurance-replay --plot
python3 -m bench.validate_serving results/serving/option-a-shutdown-only-replay \
  --config configs/serving-endurance.json --startup-only
python3 -m bench.probe_semaphore_origin results/serving/semaphore-origin-replay
```

## 耐久结果

推荐档在同一 API/EngineCore 上完成 12 轮、552 条请求，启动采样至最后一轮约 306.7 秒。两名额回退档使用新进程重放 46 条相同计划请求。合计 598 条均在窗口内完成并通过身份、token 和 usage 校验。推荐档 12 个突发窗口各有 16/32 条达到 SLO，持续窗口每轮有 12–13/14 条达到 SLO。推荐档 TTFT P95 在突发窗口为 3.05–4.03 秒，在持续窗口为 2.42–3.93 秒。

第 1 轮结束到第 12 轮结束，API RSS 增加 152 KiB，EngineCore RSS 增加 260 KiB，两个进程的文件描述符在 12 次采样中分别固定为 37、63。推荐档每轮结束时整卡显存采样在 8,738–9,846 MiB 之间。测试期间按计算进程查询 GPU 显存得到 `N/A`，因此无法从整卡曲线判断 vLLM 自身显存趋势。5 分钟的数据适合短期验收，无法证明长期无泄漏。

每个档位运行中只出现一个新增的可见命名 semaphore，推荐档 12 轮始终是同一个名字。两个档位停服均报告 1 个 semaphore 待清理，停服后均未发现残留的新增 `/dev/shm` 对象，旧 EngineCore 均已退出。

## 告警来源

两档无生成请求的启动对照均复现了同一警告，停服后无该对象。进一步在三名额 B0 的单独诊断中，记录 Python 资源跟踪器的 register/unregister 以及调用栈。观察到两个分开的对象：

| 创建位置 | 观察到的行为 |
|---|---|
| vLLM `UniProcExecutor._init_executor` 创建的 `shared_worker_lock` | 登记与注销均有记录 |
| vLLM 的 safetensors 权重迭代器调用 tqdm，`TqdmDefaultWriteLock.create_mp_lock` 创建进程间 `RLock` | 登记后没有显式注销记录，运行时同名 semaphore 可见，退出告警出现后对象已消失 |

这是一次调用栈跟踪，使用固定版本的现有环境。Python 的资源跟踪器是在退出时先报告仍登记的条目，再执行清理。本轮现象与启动加载进度条创建并保留的锁一致，未观察到每轮请求不断新增 semaphore。实际启动入口保留原版代码和告警。

数据位于 `results/serving/option-a-endurance-01/`、`results/serving/option-a-shutdown-only-01/`、`results/serving/semaphore-origin-01/`。完整快照为 `results/archive/vllm-multi-lora-2026-11-19-endurance.zip`。
