# 开发记录

## 2026-11-19 作品集本地候选

完成首页、三分钟讲解和干净 GPU 复跑。新 venv 重装锁定依赖，重新下载固定模型并生成适配器，单种子 4 轮共 256 条请求完成。首次满额集合和冷热后缀排队方向复现，冷前缀的扩容 Goodput 方向与原归档不同。分享版证据包缩短事件中的本机路径后仍重算通过 49 张表。见 [复现入口和本轮验收](reproduce.md) 与 [发布审查](release-review.md)。

## 2026-11-19 短前缀消融

只重排最初四条的 LoRA 标签，在两档容量、三个新种子上完成 12 轮、768 条实测请求。六个配对的共同后缀均表现为冷前缀下热门 P95 上升、冷门 P95 下降。新增后缀校验、后缀等待统计、逐请求时间线和三条回归测试。离线复核包升级到七组实验。见 [短前缀消融](g3-prefix-order.md)。

## 2026-11-19 固定份额的到达顺序消融

实跑 12 轮、768 条请求，完成 6 对固定容量的顺序比较。首次满额集合和最慢适配器随顺序转移，两档均在三个种子复现。新增可选固定适配器相位与场景先后平衡，以及顺序分析入口。见 [消融报告和教学](g3-arrival-order.md)。

## 2026-11-19 路线 B 容量边界

完成两、三、四种适配器需求下的四类负载、三个配对种子，共 24 轮、768 条请求。两种负对照未使用第三个名额且 Goodput 持平，其余三个场景 Goodput 在所有配对中提高。冷门 P95 的收益因场景和种子而异。见 [容量边界报告](g3-capacity-boundary.md)。

## 2026-11-19 G3 独立复核包

归档脚本新增 `--g3-audit-only`。它复用复核命令的输入清单，生成 ZIP 和 SHA-256 校验文件，并在发布到输出路径前从临时解压目录用标准库重算全部 22 张表。产物位于 `results/archive/vllm-multi-lora-g3-audit.zip`。后续方向见 [路线选择](next-route.md)。

## 2026-11-19 G3 归档复核

新增 `python -m bench.audit_g3 results/g3`，从原始记录重算并核对四份 G3 归档的 22 张统计表，覆盖 63 个实验运行、1,728 条已有请求。三份早期归档按当时的字段核对。见 [复核与源码讲解](g3-evidence-audit.md)。

## 2026-11-19 选项 A 耐久运行与停服诊断

推荐档约 306.7 秒连续 12 轮、回退档一轮，共完成 598 条请求。从首轮结束到最后一轮，API/EngineCore 的文件描述符分别固定为 37/63。停止后无新增的可见共享内存对象。无推理请求对照复现了 semaphore 警告，另用登记栈定位到 safetensors 加载时 tqdm 的进程间锁。见 `docs/serving-endurance.md` 与 `docs/learning-2026-11-19.md`。

## 2026-11-18 选项 A 连续运行验收

用实际入口启动三名额原版，在同一服务连续完成三轮突发与持续流量。停止后用两名额入口重启，重放相同轨迹一轮。184 条请求均完成，校验服务注册、响应身份和 token 数。记录 TTFT、TPOT、整卡显存和两个进程 RSS；两次退出的 semaphore 警告保留在日志。见 `docs/serving-acceptance.md`。

## 2026-11-18 选项 A 落地

用户选定三名额 B0 推荐档与两名额 B0 回退。新增 `scripts/serve.sh` 与复跑检查，真实服务启动日志验证两个容量选项，18 条流式请求均通过绑定检查。实验复跑继续使用冻结配置。命令、日志路径及归档见 [服务配置与回退](serving-option-a.md)。

## 2026-11-18 策略选型检查点

同轮配对原版两名额、原版三名额、B3-5s 两名额。两类负载、三新种子共 684 条全完成。三名额 B0 的突发组 3/3 达标，持续 Goodput 三组均改善，持续冷门结果混合。两名额 B3 换来冷门等待收益，持续 Goodput 中位下降 31.8%。完成 [选型报告](g3-strategy-decision.md)、决策 CSV 与源码和原始证据快照。现停在用户选择推荐策略的节点。

## 2026-11-18 容量对策略直接比较与教学归档

三个新种子配对比较 B3-5s 两名额与 B0 三名额，共完成 288 条请求。三名额 B0 的热门 P95 三组均下降，配对中位改善约 2.86 秒，Goodput 持平。冷门 P95 两组略升、一组下降 33.0%。见 `docs/g3-capacity-vs-policy.md`。当天工作的顺序、证据路径和逐行讲解入口整理到 `docs/learning-2026-11-18.md`。

## 2026-11-18 B0 容量对照

在 B0 原版准入中配对比较两个与三个 LoRA 名额，固定 8 条请求并发与其它配置。三配对均满足三项门槛，冷门 P95 的配对中位降幅 34.8%，Goodput 持平。KV 启动容量减少 96 token。证据和复跑入口见 `docs/g3-lora-capacity.md`。

## 2026-11-18 B3 5 秒阈值验证

三个新种子用 4 秒和 5 秒各运行一轮，共 288 条请求。后续交接 3/9 → 9/9。冷门 P95 配对中位降幅 31.5%，热门 P95 配对中位增量 1.17 秒，Goodput 持平，三组均未同时满足三项门槛。另保存了逐次决策时最老热门请求的等待时间。详见 `docs/g3-guard-midpoint.md`。

## 2026-11-18 B3 热门保护阈值对照

同一 B3 策略对比 4 秒和 6 秒热门保护阈值，三配对共 288 条请求。实际后续交接由 3/9 次增至 9/9 次，冷门 P95 配对中位下降 30.9%，热门 P95 配对中位增加 1.18 秒。仅一组同时达到冷门、热门和 Goodput 门槛。详见 `docs/g3-guard-sensitivity.md`。

## 2026-11-18 B3 有限后续交接

实现 B3 实验策略，在原 B2 基础上加入一次性的冷门后续优先和热门等待保护。三个新种子、六轮共完成 288 条请求。九波中七波触发热门保护，两波完成后续交接。Goodput 持平，冷门合并 P95 的配对中位降幅 1.2%，三对均未达到 20% 门槛。复跑命令和报告见 `docs/g3-bounded-followup.md`。

## 2026-11-18 冷门到达顺序诊断

原补充实验的九波 B2 排空目标均为 C → A → D。固定 seed 2063 的发包时间、提示词和输出长度，交换 C/D 后，对照的三波变为 D → A → C，B2 的成功交接均转移到先到的 D。镜像 B1/B2 共 96 条请求完成。证据、限制与复跑命令见 `docs/g3-cold-order.md`。

## 2026-11-18 突发竞争补充实验

三个新种子、三波突发、B1/B2 共完成 288 条请求。9 次 B1 错失名额均在 B2 对应轨迹中完成了交接。C 的排队明显下降，D 仍占据合并 P95 的慢端。三配对 Goodput 持平，无一达到合并冷门 P95 下降 20% 的门槛。逐目标证据、指标和复跑命令见 `docs/g3-competition.md`。

## 2026-11-18 G3 正式配对评估

四个场景、三个配对种子和三种模式共 36 个运行、675 条请求。B1 在两类长输出负载下降低冷门 P95，但部分场景存在 Goodput 代价。正式负载的 B1 未错失名额，B2 的预注册条件缺少合格配对。干净环境复跑高负载完成 81 条请求，结论方向一致。正式数据、图表、限制和复跑命令见 `docs/g3-evaluation.md`，讲解稿见 `docs/talk-3min.md`。

## 2026-11-18 G2 排空与定向交接

完成同一源码副本的 B0、B1、B2 切换，确定性状态测试与两次真实服务竞争复跑。日志中 B1 均有一次名额被先到的 A 请求占用，B2 两次都将对应的机会交给 C。三种模式各自通过绑定验证。竞争轨迹的 C 和 D 排队结果、版本差异、复跑命令与限制见 `docs/g2-policy.md`。

## 2026-11-18：G1 真实阻塞复现

完成 G1 观测副本、固定到达轨迹、开环回放、按请求 ID 对齐和复跑入口。三轮 `max_loras=2` 均观测到 C 被 LoRA 上限多次跳过、A/B 持续获得准入，以及 C 最终正常完成。`max_loras=4` 诊断组 C/D 均无 LoRA 跳过。完整事件链和实验边界见 `docs/g1-baseline.md`。

## 2026-11-18：完成 G0 流式绑定验收

生成四个 rank 8 的合成 LoRA，目标为 Qwen3 第 24–27 层的 `o_proj`。种子、配置及权重 SHA256 保存在 `env/adapters.json`。原版服务使用 `max_loras=2`、`max_cpu_loras=4`，启动入口为 `scripts/serve_g0.sh`。

32 token 探索轮的九条流式请求完整返回。D 的独立和并发输出在末尾出现差异，原因未单独测定。保留原始结果 `results/g0/streams-32.jsonl` 与 `binding-32.json`。随后将绑定用例固定为 24 token，三轮共 27 条请求全部通过。每轮五个独立输出互不相同，四路客户端请求时间区间重叠，并发文本分别匹配对应独立参考。原始结果见 `results/g0/streams-24-*.jsonl` 与 `binding-24-*.json`。

服务 EngineCore 日志报告 0.33.0。运行环境中安装的调度文件 SHA256 与候选 commit 的文件一致，记录见 `env/g0-runtime.json`，服务日志见 `results/g0/server.log`。G1 接入观测时将增加调度进程内的补丁加载确认，并用服务端事件验证实际同批与准入顺序。

## 2026-11-18：WSL 恢复与原版 BF16 验证

用户启用 Windows 功能并重启后，WSL GPU 查询成功。新证据在 `env/host-probe-after-reboot.json`、`env/wsl-probe.json`。

在 `~/work/vllm-lora-admission/.venv` 新建 Python 3.12.3 环境，执行 `python -m pip install --only-binary=:all: vllm==0.33.0`。安装成功，`pip check` 通过，vLLM 实际导入路径在该环境的 `site-packages/vllm/`。依赖快照 `env/requirements-wsl.txt`，本机安装日志 `env/install-vllm.log`。torch 2.14.0、CUDA runtime 13.0、vLLM 0.33.0，FP32 和 BF16 GPU 矩阵乘法通过。

通过 `scripts/download_model.py` 下载 Qwen3-0.6B，锁定 revision `c1899de289a04d12100db370d81485cdf75e47ca`，路径在 Linux 文件系统的项目工作目录；记录见 `env/model.json`。

通过 `scripts/bf16_smoke.py` 完成原版 BF16 离线单请求，生成 16 个 token。配置：max_model_len=512、max_num_seqs=4、gpu_memory_utilization=0.5、enforce_eager=True、关闭 prefix caching。结果 `results/g0/bf16-offline.json`，完整日志 `results/g0/bf16-smoke.log`。首次运行含 FlashInfer JIT 编译和 autotune，其耗时不能当作正式性能基线。

G0 仍未完整通过：下一步准备 A/B/C/D 同 rank 合成 LoRA，保存种子/权重哈希与数值绑定参考；再启动 HTTP 流式服务，验证独立与交错请求。之后核对安装 wheel 内调度源码与锁定 commit 的对应关系，再生成启动与回滚入口。B1/B2 尚未开发，G1 真实阻塞未复现。

复跑命令（WSL）：

```bash
~/work/vllm-lora-admission/.venv/bin/python scripts/bf16_smoke.py \
  --model ~/work/vllm-lora-admission/models/Qwen3-0.6B \
  --output results/g0/bf16-offline.json
```

## 2026-11-17：启动 G0

已读取原计划书，初始化独立 Git 仓库，保留计划书原文。未创建提交，未配置远程仓库。

### 完成与证据

| 工作 | 目的 | 验证结果 |
|---|---|---|
| Windows/WSL 环境取证 | 在安装前确定阻塞层 | `env/host-probe.json` 保存 GPU、Python、包状态、WSL 错误和退出码 |
| 上游源码解析与下载 | 以完整 commit 定位待观测分支 | `env/upstream-source.json` 保存 commit、SHA256 和行号；本地副本在 `vendor/vllm/` |
| BF16/四适配器流式 smoke CLI | 服务就绪后可记录独立与并发请求 | 九条请求、逐条落盘、错误非零退出；当前只在 HTTP fixture 验证 |
| 流式错误处理回归 | 防止截断响应被算成成功 | 正常/空输出/截断/错误以及 CLI 成功/失败路径，6 项通过 |
| 设计与恢复文档 | 保持实施顺序和验收标准可复查 | README、design、WSL 恢复步骤、候选配置及结果边界已落盘 |

执行 `python -m unittest discover -s tests -v`：6/6 通过。`python -m compileall -q scripts bench tests` 通过。HTTP fixture 的输出不作为 GPU 性能或适配器绑定证据。

候选上游 `v0.33.0` 解析到 commit `4ba787ec9959e566d3b587a796dff07673324da5`。该 tag 为 annotated tag，Git 直接返回的 tag 对象 `3a4d82f...` 不能当作源码 commit；工具使用 peeled commit。GitHub API 出现 403 限流后，工具改用 `git ls-remote` 解析，无需配置凭据。

在此 commit 的 `vllm/v1/core/sched/scheduler.py`：

- 第 1037 行附近，从全部 running 请求收集活跃适配器；1047 行断言不超上限。
- 1091–1102 行，在活跃 LoRA 种类已满且请求适配器不在其中时调用 `skip_request(request_queue)` 并继续循环。
- 1549 行将请求追加到 running。后续观测必须区分首次准入和恢复运行，不能简单把所有 append 当作首次有效调度。

这些是源码事实，尚无真实负载中的阻塞事件链。

### 当前阻塞与下一步

G0 未通过。WSL2 发行版启动失败；两项 Windows 功能均为 Disabled，vmcompute 不存在。恢复步骤在 `windows-wsl-recovery.md`。本轮未启用系统功能、未重启，也未改动 NestQuant 环境。

重启恢复后依次验收：WSL GPU → 独立环境 torch 小算子 → 兼容 wheel 与 BF16 原版单请求 → 四个适配器独立和交错请求 → 数值绑定验证 → manifest 锁定。正式启动脚本待实际版本和路径验证后生成，避免把候选参数当作已通过配置。

尚未完成：安装 vLLM、下载模型、生成适配器、绑定数值验证、真实 BF16/LoRA 服务、B0 观测补丁、G1 三次阻塞复现、B1/B2 策略与正式性能实验。均保留原计划验收要求。
