# Register the TDM Updater as a Windows scheduled task running weekly.
#
# Usage:
#   .\Register-WeeklyTask.ps1                  # default Sunday 02:00 local
#   .\Register-WeeklyTask.ps1 -DayOfWeek Saturday -At "23:30"
#   .\Register-WeeklyTask.ps1 -Unregister      # remove the task
#
# Notes:
#  - The task MUST run with user interactive logon. TDM is a WPF GUI and we
#    drive it via UI Automation, so the user session has to be unlocked (or
#    `at-logon` runs while session is interactive).
#  - We do NOT set RunLevel=Highest — TDM does not need admin and elevation
#    breaks UI Automation against non-elevated TDM.
#  - The task uses the currently-logged-on user account.

param(
    [string]$DayOfWeek = "Sunday",
    [string]$At = "02:00",
    [switch]$Unregister
)

$TaskName = "TDM Updater (weekly tick CSV refresh)"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Wrapper = Join-Path $Here "run_weekly.ps1"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Unregistered: $TaskName"
    } else {
        Write-Host "Not registered: $TaskName"
    }
    exit 0
}

if (-not (Test-Path $Wrapper)) {
    Write-Error "Wrapper script not found: $Wrapper"; exit 1
}

$action = New-ScheduledTaskAction `
    -Execute "PowerShell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Wrapper`"" `
    -WorkingDirectory $Here

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $At

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 18) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 15)

# Use current interactive user so the desktop session is available for UI automation.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Task already exists; updating..."
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal | Out-Null
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal `
        -Description "Drives Tick Data Manager via UI automation to refresh all <SYMBOL>_GMT+2_US-DST.csv files in D:\TickData. See TDM Updater\README.md." | Out-Null
    Write-Host "Registered: $TaskName"
}

# Show the resulting task
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, Description, State
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime, NextRunTime, LastTaskResult

Write-Host ""
Write-Host "Run on demand:  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "View status:    Get-ScheduledTaskInfo -TaskName `"$TaskName`""
Write-Host "Remove:         .\Register-WeeklyTask.ps1 -Unregister"
