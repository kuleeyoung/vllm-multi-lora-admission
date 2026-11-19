# 发布内容与来源

候选交付分为源码与离线证据两个 ZIP。源码包包含代码、配置、复现脚本、合成 LoRA 生成器、锁定环境、报告和一张逐请求时间线。主机探测文件、安装日志、运行环境、模型权重、已生成的适配器、供应商源码副本和完整本地日志由忽略规则留在工作目录。复核包提供统计输入与离线分析器。

源码包使用工作区的待提交文件清单。历史记录中的本机绝对路径已替换为工作目录示例，模型 revision 与调度器 SHA-256 已保留。用于分享的 `vllm-multi-lora-g3-audit-share.zip` 将调度加载事件中的源码路径缩为文件名，打包时从解压目录重算全部 49 张表。完整本地归档继续保留原始路径。

项目从 vLLM v0.33.0 安装包生成临时调度副本，固定 commit 为 `4ba787ec9959e566d3b587a796dff07673324da5`。模型从固定 revision 的 Qwen3-0.6B 获取，适配器由本项目生成。项目源码采用 MIT，上游依赖与模型沿用各自的许可证。 [MIT](../LICENSE) · [上游元数据](../env/upstream-source.json) · [模型版本](../env/model.json)

公开仓库提供源码、图表和聚合结论，发布页提供脱敏离线证据包及 SHA-256 校验文件。 [GitHub Release](https://github.com/kuleeyoung/vllm-multi-lora-admission/releases/tag/v0.1.0)
