$ErrorActionPreference = 'Stop'

$dataRoot = 'D:\DakwahData'
$logDir = Join-Path $dataRoot 'logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir 'scheduled-backup.log'

Start-Transcript -Path $logFile -Append | Out-Null
try {
    & (Join-Path $PSScriptRoot 'backup.ps1')
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
        throw "Backup command exited with code $LASTEXITCODE."
    }
}
catch {
    Write-Error $_
    throw
}
finally {
    Stop-Transcript | Out-Null
}
