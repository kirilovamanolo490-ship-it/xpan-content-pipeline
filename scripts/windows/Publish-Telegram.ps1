[CmdletBinding()]
param(
    [int]$Limit = 1
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if ($env:OS -ne "Windows_NT") { $python = Join-Path $projectRoot ".venv/bin/python" }
$workbookPath = Join-Path $projectRoot "output\quark_links.typefully.xlsx"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found: $python"
}
if (-not (Test-Path -LiteralPath $workbookPath -PathType Leaf)) {
    throw "Excel workbook was not found: $workbookPath"
}

Push-Location $projectRoot
try {
    & $python -m xpan_auto.publish_pipeline `
        --limit $Limit `
        --telegram-send
    if ($LASTEXITCODE -ne 0) {
        throw "Telegram publish failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
