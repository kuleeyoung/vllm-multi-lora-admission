# WSL 启动故障与恢复

2026-11-17 实测：发行版 `Ubuntu-24.04-NestQuant` 已注册为 WSL2，启动失败，错误码 `Wsl/Service/CreateInstance/CreateVm/HCS/HCS_E_SERVICE_NOT_AVAILABLE`。Windows GPU 查询成功，驱动 610.88，RTX 5070，12227 MiB。

只读检查显示：

- `VirtualMachinePlatform`：Disabled。
- `Microsoft-Windows-Subsystem-Linux`：Disabled。
- `WSLService`：Running；`vmcompute` 服务和 `C:/Windows/System32/vmcompute.exe` 不存在。
- `HypervisorPresent`：True。

启用以下两项系统功能是下一步修复，需要管理员 PowerShell。先保存正在编辑的工作；以下命令不自动重启，执行完成后安排一次 Windows 重启。

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All -NoRestart
```

重启后，在项目目录运行：

```powershell
wsl -d Ubuntu-24.04-NestQuant -- nvidia-smi
python scripts/probe_env.py --output env/host-probe-after-reboot.json
```

验收：WSL 命令退出码为 0，WSL 内显示 RTX 5070。若仍失败，保留新探测结果，继续检查功能是否启用、重启是否完成以及 vmcompute 服务状态。不要注销发行版；现有发行版可能含其他项目数据。

通过后在 WSL 的 Linux 文件系统建立 `~/work/vllm-lora-admission` 和独立虚拟环境。先核对所选 vLLM 版本的 Python、PyTorch、CUDA wheel 要求，避免复用 NestQuant 环境。完成 GPU 小算子和原版 BF16 请求，再锁定安装依赖与正式启动脚本。
