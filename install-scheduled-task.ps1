<#
    TeleAgent OpenAI-Compatible Proxy - Windows 持久化安装脚本
    ==============================================================
    对应 macOS 的 launchd plist：用「任务计划程序」实现开机自启 + 失败自动重启。

    用法:
        powershell -ExecutionPolicy Bypass -File install-scheduled-task.ps1
        powershell -ExecutionPolicy Bypass -File install-scheduled-task.ps1 -Uninstall

    说明:
        - 触发器: 用户登录时启动（与 TeleAgent 桌面应用的启动时机一致）
        - 失败重启: 每隔 1 分钟重试，最多 3 次
        - 默认只监听 127.0.0.1，不对局域网暴露
#>

param(
    [string]$TaskName = "TeleAgent OpenAI Proxy",
    [string]$Host_Address = "127.0.0.1",
    [int]$Port = 8088,
    [string]$LogDir = "$env:LOCALAPPDATA\TeleAgentOpenAIProxy",
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] 已删除计划任务: $TaskName" -ForegroundColor Green
    exit 0
}

# ---- 定位代理脚本 ----
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$proxyScript = Join-Path $scriptDir "openai_proxy.py"
if (-not (Test-Path $proxyScript)) {
    Write-Host "[ERROR] 找不到 openai_proxy.py: $proxyScript" -ForegroundColor Red
    exit 1
}

# ---- 定位 Python 解释器 ----
$python = $null
$teleAgentPython = "$env:USERPROFILE\.local\share\TeleAgent\runtimes\python\python.exe"
if (Test-Path $teleAgentPython) {
    $python = $teleAgentPython
} else {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source }
}
if (-not $python) {
    Write-Host "[ERROR] 找不到 Python 解释器（请安装 Python 3.8+ 或安装 TeleAgent 运行时）" -ForegroundColor Red
    exit 1
}

# ---- 准备日志目录 ----
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$stdout = Join-Path $LogDir "proxy.out.log"
$stderr = Join-Path $LogDir "proxy.err.log"

Write-Host "[INFO] Python    : $python"
Write-Host "[INFO] 代理脚本  : $proxyScript"
Write-Host "[INFO] 监听地址  : ${Host_Address}:$Port"
Write-Host "[INFO] 日志      : $LogDir"
Write-Host ""

# ---- 包装成 .cmd，让计划任务直接调用 ----
$runner = Join-Path $LogDir "run-proxy.cmd"
$runnerContent = @"
@echo off
"$python" "$proxyScript" --host $Host_Address --port $Port
"@
[System.IO.File]::WriteAllText($runner, $runnerContent, (New-Object System.Text.UTF8Encoding($false)))

# ---- 注册计划任务 ----
$action = New-ScheduledTaskAction -Execute $runner
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "TeleAgent OpenAI-Compatible Proxy (127.0.0.1:$Port)" `
    -Force | Out-Null

Write-Host "[OK] 计划任务已注册: $TaskName" -ForegroundColor Green
Write-Host ""
Write-Host "常用命令:" -ForegroundColor Cyan
Write-Host "  立即启动 : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  停止     : Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "  查看状态 : Get-ScheduledTask  -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  卸载     : powershell -ExecutionPolicy Bypass -File install-scheduled-task.ps1 -Uninstall"
Write-Host ""
Write-Host "注意: 任务在用户登录时启动，且需要 TeleAgent 桌面应用已经在运行（super-agent 监听 4397）。" -ForegroundColor Yellow
