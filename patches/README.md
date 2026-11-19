# 调度补丁

G1 的 B0 观测由 `scripts/build_b0_overlay.py` 生成。脚本先核对安装版调度源码的 SHA256，再生成只在实验进程中导入的副本。记录进入队列、LoRA 上限跳过、准入、完成，以及实际加载副本的进程 ID 和文件路径。上游调度判断和队列顺序沿用原版，安装目录无需改动。

在 WSL 项目目录执行 `bash scripts/run_g1.sh results/g1/replay-001`，使用独立的结果目录。脚本先跑三次 `max_loras=2`，再用相同轨迹跑一次 `max_loras=4`。每组启动前预热，结束后关闭测试服务。不设置观测环境变量，直接运行 `bash scripts/serve_g0.sh` 即可启动原版服务。

G2 在同一副本生成器中接入 `scheduler_integration.py` 和 `admission_policy.py`。通过 `LORA_ADMISSION_MODE=B0|B1|B2|B3` 切换，默认 B0。B0 使用原队列和准入规则。B1 是排空，B2 加定向交接，B3 再增加受热门等待保护的一次性后续优先机会。策略支持单设备、FCFS、本地 KV 的 LoRA 服务。G2 实验采用 500 ms 等待阈值、10 秒预留期限、1 秒目标适配器冷却。B3 参数见 [有限后续交接实验](../docs/g3-bounded-followup.md)。

执行 `bash scripts/run_g2.sh results/g2/replay-001` 使用同一轨迹运行三种模式。原始调度事件、启动日志、流式绑定和逐请求记录会写入结果目录。
