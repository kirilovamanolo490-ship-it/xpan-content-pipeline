[CmdletBinding()]
param(
    [switch]$Scrape,
    [switch]$DryRun
)

# 知识渠道「自动收录」：抓取飞书页面 → 增量追加到 knowledge/资料渠道一收录.md
# 用法：
#   .\Ingest-Knowledge.ps1 -Scrape            # 重新抓取飞书并增量收录
# 默认推荐 python scripts/run_workflow.py ingest，自动抓取并清理临时文件。
# 不带 -Scrape 的此兼容脚本仅适用于已人工准备 work/feishu-source.json 的情况。
#   .\Ingest-Knowledge.ps1 -DryRun             # 只预览新增条目，不写文件

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
    $arguments = @("-m", "xpan_auto.knowledge_flow", "ingest")
    if ($Scrape) { $arguments += "--scrape" }
    if ($DryRun) { $arguments += "--dry-run" }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge ingest failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
