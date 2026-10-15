[CmdletBinding()]
param(
    [switch]$Unregister
)

# 注册/注销知识渠道「每日飞书收录」计划任务（Windows 任务计划程序）
# 默认：每天 20:00 执行飞书抓取和增量收录。
# 归档、夸克转存、新分享和 Excel 回写是独立流程，不由本任务触发。
# 这是 Codex 定时任务不可用时的本机备用方案；请不要与 Codex 的同一时刻任务同时启用。
# 用法（管理员 PowerShell）：
#   .\Register-KnowledgeTasks.ps1            # 注册
#   .\Register-KnowledgeTasks.ps1 -Unregister # 注销

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskName = "XKnowledge-Ingest"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scriptPath = Join-Path $projectRoot "scripts\windows\Run-FeishuIntakeDaily.ps1"

if ($Unregister) {
    schtasks /Delete /TN $taskName /F 2>$null | Out-Null
    Write-Host "已注销计划任务: $taskName"
    return
}

if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "Ingest script not found: $scriptPath"
}

schtasks /Create `
    /TN $taskName `
    /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`"" `
    /SC DAILY `
    /ST "20:00" `
    /F | Out-Null
Write-Host "已注册计划任务: $taskName @ 20:00 (每天，仅飞书收录)"

Write-Host ""
Write-Host "注意：任务在「当前登录用户」下运行；如机器锁屏/睡眠时未执行，"
Write-Host "可在任务计划程序中把任务设置为『不管用户是否登录都要运行』或调整唤醒策略。"
Write-Host "手动运行：.\Run-FeishuIntakeDaily.ps1"
