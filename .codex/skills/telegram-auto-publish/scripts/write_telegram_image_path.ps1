param(
    [Parameter(Mandatory = $true)][int]$RowIndex,
    [Parameter(Mandatory = $true)][string]$ImagePath,
    [string]$WorkbookPath = '',
    [string]$WorksheetName = '处理结果',
    [int]$ImageColumn = 13
)
# Legacy entry point; workbook access is now cross-platform Python, never COM.
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if ($env:OS -ne 'Windows_NT') { $python = Join-Path $projectRoot '.venv/bin/python' }
if (-not (Test-Path -LiteralPath $python)) { throw "Native Python environment missing: $python" }
if ($WorksheetName -ne '处理结果') { throw 'Only the fixed 处理结果 worksheet is supported' }
$arguments = @((Join-Path $PSScriptRoot 'write_telegram_image_path.py'), '--row-index', $RowIndex, '--image-path', $ImagePath)
if ($WorkbookPath) { $arguments += @('--workbook-path', $WorkbookPath) }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw "Image path write failed: $LASTEXITCODE" }
