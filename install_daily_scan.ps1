# ============================================================================
# Install the Oweru daily scan as a Windows Scheduled Task.
# Run once from an elevated PowerShell:
#     powershell -ExecutionPolicy Bypass -File install_daily_scan.ps1
#
# The task runs run_daily_scan.bat every day at 06:00 and writes results
# to daily_scan.log in the project folder.
# ============================================================================

$ErrorActionPreference = 'Continue'

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatPath = Join-Path $ProjectDir 'run_daily_scan.bat'
$TaskName = 'Oweru Daily Site Scan'

if (-not (Test-Path -LiteralPath $BatPath)) {
    Write-Error "run_daily_scan.bat not found at $BatPath"
    exit 1
}

Write-Host "Registering scheduled task '$TaskName' ..." -ForegroundColor Cyan

# Remove existing task if present (ignore the "not found" error on first run)
schtasks /Delete /TN $TaskName /F 2>$null | Out-Null

schtasks /Create /TN $TaskName /TR $BatPath /SC DAILY /ST 06:00 /F
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to create the scheduled task. Run this script as Administrator."
    exit 1
}

Write-Host "Task created: runs daily at 06:00." -ForegroundColor Green
Write-Host "Test it now with:" -ForegroundColor Cyan
Write-Host "  schtasks /Run /TN \"$TaskName\"" -ForegroundColor Yellow
Write-Host "Logs: $ProjectDir\daily_scan.log" -ForegroundColor Yellow

# Verify the task was registered
schtasks /Query /TN $TaskName