$ErrorActionPreference = 'Stop'
$projectDirectory = Split-Path -Parent $PSScriptRoot
$runnerPath = Join-Path $PSScriptRoot 'run-appointment-emails.ps1'
$pythonExecutable = (Get-Command python -ErrorAction Stop).Source
& $pythonExecutable -X utf8 (Join-Path $projectDirectory 'manage.py') send_appointment_emails --check-config
if ($LASTEXITCODE -ne 0) {
    throw 'Can hoan tat cau hinh gui email trong .env truoc khi dang ky lich.'
}
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -PythonExecutable "{1}"' -f $runnerPath, $pythonExecutable) -WorkingDirectory $projectDirectory
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'MinhTam-AppointmentEmails' -Description 'Gui lai email lich hen dang cho/loi; khong gui lai thu da gui hoac thong tin cu.' -Action $action -Trigger $trigger -Settings $taskSettings -Principal $principal -Force | Select-Object TaskName, State
