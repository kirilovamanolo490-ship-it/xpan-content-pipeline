[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Execute,
    [switch]$RetryFailed
)

# 独立归档流程：读取资料渠道一归档.md → 夸克转存 → 新分享 → 总大小/保存路径/状态追加到发布主表。
# 用法：
#   .\Run-KnowledgeArchive.ps1 -DryRun # 只预览归档候选，不操作夸克或 Excel
#   .\Run-KnowledgeArchive.ps1 -Execute # 按归档游标真实执行范围内未处理条目

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$archiveScript = Join-Path $projectRoot "scripts\windows\Archive-Knowledge.ps1"
$logDirectory = Join-Path $projectRoot "output\logs"
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDirectory "knowledge-archive-$runStamp.log"

if (-not (Test-Path -LiteralPath $archiveScript -PathType Leaf)) {
    throw "Knowledge archive script not found: $archiveScript"
}

if (-not $DryRun -and -not $Execute) {
    throw "真实归档会转存并新建分享链接；请先用 -DryRun 预览，确认后传入 -Execute。"
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-RunLine {
    param([Parameter(Mandatory)][string]$Message)
    "[{0}] {1}" -f (Get-Date -Format "s"), $Message |
        Tee-Object -FilePath $logFile -Append
}

try {
    $mode = if ($DryRun) { "DRY_RUN" } else { "LIVE" }
    Write-RunLine "knowledge_archive_start mode=$mode log=$logFile"

    $archiveParameters = @{ RunAll = $true }
    if ($DryRun) {
        $archiveParameters.DryRun = $true
    } else {
        $archiveParameters.QuarkRun = $true
        $archiveParameters.Execute = $true
    }
    if ($RetryFailed) { $archiveParameters.RetryFailed = $true }

    & $archiveScript @archiveParameters 2>&1 | Tee-Object -FilePath $logFile -Append
    $stageExitCode = $LASTEXITCODE
    if ($stageExitCode -ne 0) {
        throw "archive_stage_failed exit_code=$stageExitCode"
    }

    Write-RunLine "knowledge_archive_done mode=$mode"
} catch {
    Write-RunLine "knowledge_archive_failed message=$($_.Exception.Message)"
    throw
}
