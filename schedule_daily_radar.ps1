# Run this once in PowerShell as Administrator to schedule the B2B Atlanta radar daily at 8am
$taskName = "B2B Atlanta Daily Radar"
$scriptPath = "C:\Users\Ryan.Casale\OneDrive - IQPC WBR\Field service East\fse_sdr_agent\Run B2B Atlanta Radar.bat"

$action = New-ScheduledTaskAction -Execute $scriptPath
$trigger = New-ScheduledTaskTrigger -Daily -At "8:00AM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force

Write-Host ""
Write-Host "Done! '$taskName' will run every morning at 8am."
Write-Host "New companies will appear in your pipeline tab automatically."
Write-Host ""
Write-Host "To run it manually right now:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
