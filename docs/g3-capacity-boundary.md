# 第三个 LoRA 名额的容量边界

## 结果

2026-11-19 在 RTX 5070 上实跑 24 轮、768 条请求。请求全部在 36 秒测量窗内完成，身份、token 和 usage 校验通过。未出现超时、未准入或抢占，最大测得发包滞后约 0.981 ms。12 对轨迹哈希一致，实测配置与冻结配置文件一致。

表中变化为 L3 减 L2，再取三个种子的配对中位数。冷门与热门 P95 的负值表示排队缩短。四种均匀组用 C/D 作为固定对照分组，两组实际份额相等。

| 负载 | 第三种准入次数 | 冷门 P95 | 热门 P95 | Goodput | 三项达标 |
|---|---:|---:|---:|---:|---:|
| 两种、偏斜 | 0 | −0.100 s | −0.057 s | 持平 | 负对照 |
| 三种、偏斜 | 3 | +0.147 s | −7.660 s | +0.333 请求/s（+60.0%） | 1/3 |
| 四种、偏斜 | 8 | −2.005 s | −0.706 s | +0.111 请求/s（+16.0%） | 2/3 |
| 四种、均匀 | 6 | −1.451 s | −1.082 s | +0.250 请求/s（+56.3%） | 2/3 |

- **两种负对照。** 两档每轮均为 32/32 条请求达到 SLO。尽管第三个名额全程没有使用，seed 20149 的冷门 P95 仍从 1.617 秒变成 0.451 秒，给出了单次测量波动的一个实例。
- **三种、偏斜。** L3 三对均提高 Goodput。逐适配器时间解释了冷门 P95 为何没有同步改善。在 seed 19301 的 L2 组，B 排队 P95 约 8.55 秒，C 则约 1.0 ms。换到 L3 后，B/C 分别约 120/148 ms。seed 21713 的 L2 慢端主要落在 A，seed 20149 才落在 C。报告冷门百分比时应同时给出绝对时间。
- **四种负载。** 两种份额模式的 Goodput 均在三对中提高。偏斜组冷门 P95 在种子 21713 上反而增加 1.221 秒。均匀组种子 21713 虽通过 20% 相对门槛，绝对只缩短约 0.681 ms。当前每轮冷门样本为 8 条或 16 条，结果适合说明现有负载下的边界。
- **容量成本。** L2 启动 KV 容量为 43,904 token，L3 为 43,808，六次启动均符合各档数值。增加一个名额的代价为 96 token，约 0.22%。三种或四种负载在此设置下共观察到 17 次由两种进入三种活跃适配器的准入。

本轮支持三名额 B0 在三种和四种持续负载下提高 Goodput，冷门排队改善随具体请求轨迹变化。只发送两种适配器时，第三个名额没有用于准入，Goodput 持平。当前结论限于固定 4 请求/秒、64 输出 token、单卡及四个 rank 8 合成 LoRA。

结果位于 `results/g3/capacity-boundary-01/`。逐种子结论见 `capacity-boundary-pairs.csv`，逐适配器见 `cohorts.csv`，实际使用额外名额见 `third-slot-admissions.csv`。在 WSL 临时目录重新生成的九张表与归档一致，移除第三名额证据后，新增分析命令拒绝生成配对报告。完整快照为 `results/archive/vllm-multi-lora-capacity-boundary.zip`。

## 实验设计与复跑

本轮只比较原版 B0 的两个和三个活跃 LoRA 名额。用三个独立种子，每组固定 4 请求/秒、8 秒发包、每条 64 输出 token、并发上限 8。每轮计划 32 条，测量窗为 36 秒。模型、rank、四个已注册适配器、预热和观测配置相同。容量档按种子轮换启动顺序。

| 场景 | 实际发送的适配器 | 请求份额 | 用途 |
|---|---|---|---|
| `demand2-skewed` | A、C | 75% / 25% | 负对照。两种同时活跃仍有足够的种类额度 |
| `demand3-skewed` | A、B、C | 37.5% / 37.5% / 25% | 把热门请求分到 A/B，观察第三个名额是否实际使用 |
| `demand4-skewed` | A、B、C、D | 37.5% / 37.5% / 12.5% / 12.5% | 将一半冷门请求改用 D，保持冷热请求总占比 |
| `demand4-balanced` | A、B、C、D | 各 25% | 固定四种适配器，改变请求份额与交错次序。C/D 沿用对照分组 |

这些对照改变适配器映射，份额与交错次序的影响需结合解读。每个场景内的 L2/L3 使用完全相同的发包计划。容量变化同时包含可用 KV 预算变化，这正是实际配置的成本。

沿用三项门槛：冷门排队 P95 降幅至少 20%、热门排队 P95 增量至多 1 秒、Goodput 降幅至多 5%。L3 实际用到第三个名额的配对才进入收益门槛判定。负对照保留延迟和 Goodput 差值用于理解运行波动。Goodput 按测量窗内完成且 TTFT ≤ 2 秒、TPOT ≤ 120 ms 的请求数除以窗长计算。报告每种负载的配对差值中位数、实际占用第三个名额的次数，以及请求失败、未准入、抢占与 KV 预算。

```bash
LORA_PORT=8021 ~/work/vllm-lora-admission/.venv/bin/python -m bench.run_g3 \
  results/g3/capacity-boundary-replay --config configs/g3-capacity-boundary.json
python3 -m bench.analyze_g3 results/g3/capacity-boundary-replay
python3 -m bench.analyze_decision_matrix results/g3/capacity-boundary-replay
python3 -m bench.analyze_capacity results/g3/capacity-boundary-replay
python3 -m bench.analyze_capacity_boundary results/g3/capacity-boundary-replay
```

## 读代码顺序

1. [g3-capacity-boundary.json](../configs/g3-capacity-boundary.json) 指定种子、容量档、请求模式与验收条件。[run_g3.py](../bench/run_g3.py) 旋转每个种子的启动顺序，为两个容量档重放相同的到达轨迹。核对 `trajectory.json` 时，同一个种子下的四种场景使用相同的发包时刻、提示词和输出长度，适配器的映射由场景决定。
2. [analyze_g3.py](../bench/analyze_g3.py) 用 `scheduler_capacity` 核对 EngineCore 的实际配置，再用请求 ID 关联客户端记录和服务端事件。它按同场景、同种子生成 L3/L2 配对统计。
3. [analyze_capacity.py](../bench/analyze_capacity.py) 从 `admit` 的 `active_before` 重建种类数变化。例如当前种类为 A/B，这次准入的 C 形成 A/B/C，就计一次从两种到三种的变化。已有 A/B/C 时，再准入一个 A 请求属于复用，并且增加的是请求数。
4. [analyze_capacity_boundary.py](../bench/analyze_capacity_boundary.py) 把配对指标、第三个名额的使用记录、启动 KV token 容量按场景、种子和配置合到一行。若事件证据与配对结果对第三个名额的使用判断不一致，或者任一档存在请求失败、未准入或抢占，复核会报出具体配对。

实际例子在 `19301/B0-L3/events.jsonl`。搜索 `demand4-skewed-005-0-bc5156ad`，其中 `admit` 记录的 `active_before` 为 `[1, 2]`，`adapter` 为 C，正对应 A/B 已占两个名额而 C 成为第三种。观察同组索引 002 的事件还会看到 B 成为第三种，所以额外名额既可能帮助冷门请求，也可能被热门请求使用。

## 模拟面试

1. **为什么需要发送两种 LoRA 的负对照？**  
   **参考答案**　两名额已经覆盖全部请求使用的适配器。在这个场景里，三名额配置应有零次两种到三种的变化。两档延迟或 Goodput 仍可能随运行波动和 KV 预算变化而不同。这组能帮助解释扩容场景的变化。
2. **在三种适配器的负载中，把容量从 2 提到 3 后，如何确认收益和容量机制有关？**  
   **参考答案**　先核对同种子两个容量档的轨迹哈希，再核对 EngineCore 实际加载的 `max_loras`。对第三种首次准入寻找事件证据，例如 `active_before=[1,2]` 且准入适配器为 C。再查看冷门 P95、热门 P95 和 Goodput 的配对变化。存在第三种准入说明触发了机制，指标阈值用于判断收益和代价是否达标。
3. **每轮冷门 P95 只有 8 个样本，三种子应该怎么讲结果？**  
   **参考答案**　每种子独立算 P95 和配对变化，报告三对的方向、范围与中位数，并给出样本量。用三个配对描述这个负载下的证据。若要做稳定的尾部分位点估计，应增加每轮冷门样本和独立轨迹。
