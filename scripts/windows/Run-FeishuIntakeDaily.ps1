[CmdletBinding()]
param(
    [switch]$DryRun
)

# 每日飞书收录：飞书抓取 → 按收录.md顶部日期增量同步到收录.md。
# 归档、夸克转存、新分享和 Excel 回写属于独立流程，不在此脚本内执行。
# 用法：
#   .\Run-FeishuIntakeDaily.ps1         # 真实执行飞书抓取与收录
#   .\Run-FeishuIntakeDaily.ps1 -DryRun # 抓取并预览，不写收录.md

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ingestScript = Join-Path $projectRoot "scripts\windows\Ingest-Knowledge.ps1"
$logDirectory = Join-Path $projectRoot "output\logs"
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDirectory "feishu-intake-$runStamp.log"

if (-not (Test-Path -LiteralPath $ingestScript -PathType Leaf)) {
    throw "Knowledge intake script not found: $ingestScript"
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-RunLine {
    param([Parameter(Mandatory)][string]$Message)
    "[{0}] {1}" -f (Get-Date -Format "s"), $Message |
        Tee-Object -FilePath $logFile -Append
}

function Invoke-IntakeStage {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$ScriptPath,
        [hashtable]$StageParameters = @{}
    )

    Write-RunLine "stage_start=$Name"
    & $ScriptPath @StageParameters 2>&1 | Tee-Object -FilePath $logFile -Append
    $stageExitCode = $LASTEXITCODE
    if ($stageExitCode -ne 0) {
        throw "stage_failed=$Name exit_code=$stageExitCode"
    }
    Write-RunLine "stage_done=$Name"
}

try {
    $mode = if ($DryRun) { "DRY_RUN" } else { "LIVE" }
    Write-RunLine "feishu_intake_start mode=$mode log=$logFile"

    $ingestParameters = @{ Scrape = $true }
    if ($DryRun) { $ingestParameters.DryRun = $true }
    Invoke-IntakeStage -Name "ingest" -ScriptPath $ingestScript -StageParameters $ingestParameters

    Write-RunLine "feishu_intake_done mode=$mode"
} catch {
    Write-RunLine "feishu_intake_failed message=$($_.Exception.Message)"
    throw
}
