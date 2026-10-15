[CmdletBinding()]
param(
    [switch]$QuarkRun,
    [switch]$Execute,
    [switch]$RunAll,
    [switch]$DryRun,
    [switch]$RetryFailed,
    [int]$Limit = 1
)

# 知识渠道「归档处理」：读取 knowledge/资料渠道一归档.md 的新增条目
#   → 自动预分类 → 追加写入 output/quark_links.typefully.xlsx 的“处理结果”工作表
#   -QuarkRun -Execute 时：自动执行夸克转存 + 新分享 + 匿名验证，新链接回写 Excel
# 用法：
#   .\Archive-Knowledge.ps1 -DryRun                     # 预览候选与预分类
#   .\Archive-Knowledge.ps1                              # 只登记 Excel（不碰夸克）
#   .\Archive-Knowledge.ps1 -QuarkRun -Execute -Limit 1  # 先单条验证完整链路
#   .\Archive-Knowledge.ps1 -QuarkRun -Execute -RunAll   # 全量处理归档条目

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if ($env:OS -ne "Windows_NT") { $python = Join-Path $projectRoot ".venv/bin/python" }

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found: $python"
}

Push-Location $projectRoot
try {
    $arguments = @("-m", "xpan_auto.knowledge_flow", "archive", "--limit", $Limit)
    if ($QuarkRun)  { $arguments += "--quark-run" }
    if ($Execute)   { $arguments += "--execute" }
    if ($RunAll)    { $arguments += "--run-all" }
    if ($DryRun)    { $arguments += "--dry-run" }
    if ($RetryFailed) { $arguments += "--retry-failed" }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge archive failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
