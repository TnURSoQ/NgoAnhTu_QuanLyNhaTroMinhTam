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
$logFile = Join-Path $logDirectory 'monthly-billing.log'
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Tao hoa don nhap" | Out-File -FilePath $logFile -Append -Encoding utf8
& $PythonExecutable -X utf8 (Join-Path $projectDirectory 'manage.py') generate_monthly_invoice_drafts 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
exit $LASTEXITCODE
