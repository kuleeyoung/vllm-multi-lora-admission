# G3 实验归档复核与源码讲解

本阶段对应计划书 G3 的结果整理与可复现交付。推荐服务采用三名额 B0，实验归档保留各自的策略与容量。运行以下命令可用 Python 标准库从已归档的原始数据重算统计，Windows 和 WSL 均可使用。

```text
python -m bench.audit_g3 results/g3 --suite paired-01 --suite clean-01 --suite guard-midpoint-01 --suite decision-matrix-01
python -m bench.audit_g3 results/g3 --suite guard-midpoint-01
```

| 归档 | 实验运行 | 请求 | 复核表 |
|---|---:|---:|---:|
| 正式评估 `paired-01` | 36 | 675 | 4 |
| 干净环境复跑 `clean-01` | 3 | 81 | 4 |
| 4 秒／5 秒对照 `guard-midpoint-01` | 6 | 288 | 6 |
| 最终选型 `decision-matrix-01` | 18 | 684 | 8 |
| 合计 | 63 | 1,728 | 22 |

默认命令现已纳入容量边界、完整顺序和短前缀消融。新版打包和复算入口见 [离线复核包](g3-audit-bundle.md)。

Windows 与 WSL 的复核结果一致，现有 17 项单元测试通过。在临时副本中改写一项冷门 P95 降幅，复核报告 `pairs.csv` 不一致。在轨迹末尾追加一处换行，分析器的 SHA-256 校验拒绝了该输入。

复核使用已有的那一批实测请求。需要现场再测一次 GPU 时，使用各实验报告的回放入口。归档通过 `results/` 下的本地目录或历史 ZIP 提供，仓库的忽略规则会排除原始产物。

## 代码在流程中的位置

| 步骤 | 入口 | 输入与输出 |
|---|---|---|
| 发请求 | [run_g3.py](../bench/run_g3.py) 的 `workload`、`replay` | 用种子生成计划发包时刻、LoRA 和输出长度。按计划发送并保存 `trajectory.json`、实际发送和返回记录 `client.jsonl` |
| 决定何时准入 | [scheduler_integration.py](../patches/scheduler_integration.py)、[admission_policy.py](../patches/admission_policy.py) 的 `begin` 和 `admitted` | EngineCore 每轮读取运行中适配器和候选请求，执行排空与交接规则，输出带请求 ID 和单调时钟的 `events.jsonl` |
| 从请求算统计 | [analyze_g3.py](../bench/analyze_g3.py) 的 `measure`、`compare` | 验证轨迹哈希和实际加载模式，关联客户端和服务端。用同一个请求的首次 `admit` 减去 `queued` 求排队时间，再按同种子、同场景比较 |
| 复核报告 | 新增 [audit_g3.py](../bench/audit_g3.py) 的 `stage_inputs`、`audit`、`matches` | 复制原始输入到临时目录，调用既有分析器生成新表并对照归档。某一步失败时返回非零退出码和文件位置 |

`stage_inputs` 只复制配置、事件、轨迹、请求和采样，以及容量分析需要的启动日志。旧统计表留在原目录供对照。分析器必须自己生成临时目录的统计结果。对三份早期归档，复核允许当前分析器新增的 `max_loras` 与 `peak_active_loras_observed` 两列。CSV 按列名匹配，行顺序和单元格值仍须一致。当前选型归档使用完整字段。

## 用 8167 的一个请求把代码串起来

打开 `results/g3/guard-midpoint-01/8167/B3-5s/events.jsonl`，搜索 D 的 ID 后缀 `015-0-afb83544` 和 A 的 `008-0-81883fa3`。

1. A 的 `queued` 时间是 `134439580414 ns`。在 `cold_followup_selected` 的事件时刻 `138544577343 ns`，它已排队约 4.105 秒，低于本轮 5 秒热门保护阈值。这个小数是依据日志中的事件时刻重建的。
2. B3 选中 D 做额外交接，排空对象为 C。等 C 的在途请求自然完成后，日志先出现 `slot_released`，再出现 `handoff_attempt`。
3. D 在 `140100543200 ns` 实际 `admit`，入队时刻是 `134607613164 ns`，因此它的排队时间约为 5.493 秒。紧随其后的 `target_admitted` 证明这是一次完成的交接。数学上，排队时间取同一请求的两次服务端时间差，热门保护检查取决策时刻减去当时最老热门请求的入队时间。
4. `guard-decisions.csv` 回答当时热门请求等了多久，`followup-requests.csv` 回答优先机会是否实际兑现，`pairs.csv` 回答整轮的冷门尾延迟是否值得这笔代价。8167 的冷门 P95 下降约 31.5%，热门 P95 增加约 1.87 秒，超过 1 秒门槛。

## 三道模拟面试题

1. **如果 `max_loras=2` 且当前已有 A、B，为什么 C 排在队首也可能一直等？B1 和 B2 各改了哪里？**  
   **参考答案**　两类活跃 LoRA 已用完种类额度。只要 A、B 各有请求在途，同类新请求可以继续获得准入，C 需要的类别名额仍无法释放。B1 暂停一个适配器接收新请求，让正在运行的请求自然完成。B2 在这个基础上，腾出名额后把触发排空的请求优先送进原有 token、KV 和并发检查。收到 `admit` 才算成功。取消、超时或资源约束会释放预留。
2. **两档 B3 的计划轨迹哈希相同，为什么还要看 `scheduler_loaded` 和 `target_admitted`？**  
   **参考答案**　哈希确认两档输入的发包计划、适配器和长度一致。`scheduler_loaded` 确认引擎进程实际加载了对应策略和阈值，`target_admitted` 确认某次被选中的请求确实拿到准入。8167 中，5 秒档三次额外交接都兑现了，同时热门 P95 增加 1.87 秒，所以该配对仍未达标。
3. **两名额 B3 持续场景的冷门 P95 降幅更大，为什么最终推荐三名额 B0？怎么做归因？**  
   **参考答案**　用两名额 B3 对两名额 B0 隔离策略影响，用三名额 B0 对两名额 B0 隔离容量影响。以两名额 B0 为基线，三名额 B0 在突发流量 3/3 组同时通过门槛，持续流量 Goodput 三组都提升；两名额 B3 的持续 Goodput 配对中位下降 31.8%。三名额 B0 也有代价，启动 KV 容量减少 96 token，持续冷门 P95 只有一组达到 20% 降幅。推荐在当前单卡和负载范围成立。
