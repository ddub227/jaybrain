# Schedule the JayBrain Daily Briefing as a Windows Scheduled Task.
# Run this script once (elevated if possible) to create the task.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_briefing.ps1

$ErrorActionPreference = "Stop"

$TaskName = "JayBrain Daily Briefing"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $ProjectRoot) { $ProjectRoot = "C:\Users\Joshua\jaybrain" }

# Find Python executable
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $PythonPath) {
    $PythonPath = (Get-Command python3 -ErrorAction SilentlyContinue).Source
}
if (-not $PythonPath) {
    Write-Error "Python not found in PATH. Please install Python 3.11+ or add it to PATH."
    exit 1
}

Write-Host "Using Python: $PythonPath"
Write-Host "Project root: $ProjectRoot"

# Build the action
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "-m jaybrain.daily_briefing" `
    -WorkingDirectory $ProjectRoot

# Daily at 7:00 AM
$Trigger = New-ScheduledTaskTrigger -Daily -At "07:00AM"

# Settings: allow running on battery, don't stop if going to battery,
# wake to run, retry on failure
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# Remove existing task if it exists
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Register the task (runs as current user)
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Sends a daily email briefing with tasks, job pipeline, networking items, and study stats from JayBrain." `
    -RunLevel Highest

Write-Host ""
Write-Host "Scheduled task '$TaskName' created successfully!" -ForegroundColor Green
Write-Host "  Schedule: Daily at 7:00 AM"
Write-Host "  Python:   $PythonPath"
Write-Host "  Command:  python -m jaybrain.daily_briefing"
Write-Host ""
Write-Host "To test it now:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To remove it:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
