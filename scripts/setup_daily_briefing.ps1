$action = New-ScheduledTaskAction -Execute 'python' -Argument '-m jaybrain.daily_briefing' -WorkingDirectory 'C:\Users\Joshua\jaybrain'
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName 'JayBrain Daily Briefing' -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Scheduled task 'JayBrain Daily Briefing' created for 7:00 AM daily."
