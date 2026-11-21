$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$runnerPath = Join-Path $PSScriptRoot 'run-monthly-billing.ps1'
$pythonExecutable = (Get-Command python -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -PythonExecutable "{1}"' -f $runnerPath, $pythonExecutable) -WorkingDirectory $projectDirectory
$trigger = New-ScheduledTaskTrigger -Daily -At '00:10'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'MinhTam-MonthlyInvoiceDrafts' -Description 'Tao hoa don nhap hang thang cho nha tro Minh Tam; khong tu chot hoa don.' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Select-Object TaskName, State
