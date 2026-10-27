# Make the TechTrend scheduled task start at boot without anyone logged on.
#
# The task used LogonType Interactive with an at-logon trigger, so after the
# 2026-10-27 05:00 reboot it stayed down until someone logged in (08:24).
# This switches it to S4U (no stored password) and adds an AtStartup trigger.
# Run from an elevated PowerShell: powershell -ExecutionPolicy Bypass -File fix-boot-task.ps1

$ErrorActionPreference = 'Stop'
$bak = Join-Path $PSScriptRoot 'TechTrend-task.backup-2026-10-27.xml'
if (-not (Test-Path $bak)) { Export-ScheduledTask TechTrend | Out-File $bak -Encoding utf8 }
"backup: $bak"

$t = Get-ScheduledTask TechTrend
$trig = @($t.Triggers)
if (-not ($trig | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })) {
    $trig += New-ScheduledTaskTrigger -AtStartup
}
$p = New-ScheduledTaskPrincipal -UserId Administrator -LogonType S4U -RunLevel Highest
Set-ScheduledTask TechTrend -Trigger $trig -Principal $p | Out-Null

# Test: the start script is idempotent, so a run now should just log "already up".
$before = (Get-Date)
Start-ScheduledTask TechTrend
Start-Sleep 30
$info = Get-ScheduledTaskInfo TechTrend
"last run: $($info.LastRunTime)  result: 0x{0:X}" -f $info.LastTaskResult
wsl -d Ubuntu-24.04 -u root -e tail -n 7 /var/log/techtrend-start.log
"If the log above has new lines from $($before.ToString('HH:mm')) on, S4U works."
"If not, roll back:  Register-ScheduledTask TechTrend -Xml (Get-Content '$bak' -Raw) -Force"
"  then use a stored password instead:  Set-ScheduledTask TechTrend -User Administrator -Password '<pw>'"
