param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExecutable
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$projectDirectory = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$logDirectory = Join-Path $projectDirectory '.backups'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logFile = Join-Path $logDirectory 'appointment-emails.log'
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Gui email lich hen dang cho" | Out-File -FilePath $logFile -Append -Encoding utf8
$ErrorActionPreference = 'Continue'
& $PythonExecutable -X utf8 (Join-Path $projectDirectory 'manage.py') send_appointment_emails --limit 20 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
$emailExitCode = $LASTEXITCODE
exit $emailExitCode
