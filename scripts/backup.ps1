$ErrorActionPreference = 'Stop'

$repo = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repo '.env'
if (-not (Test-Path -LiteralPath $envFile)) {
    throw 'File .env tidak ditemukan. Salin .env.example dan isi konfigurasi lokal terlebih dahulu.'
}

$settings = @{}
foreach ($line in Get-Content -LiteralPath $envFile) {
    if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$') {
        $settings[$Matches[1]] = $Matches[2].Trim('"').Trim("'")
    }
}

$appData = $settings['APP_DATA_DIR']
if ([string]::IsNullOrWhiteSpace($appData)) { throw 'APP_DATA_DIR belum ditetapkan di .env.' }
$snapshotSource = Join-Path $appData 'qdrant-snapshots'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$backupRoot = Join-Path 'F:\DakwahBackup' $timestamp
$snapshotTarget = Join-Path $backupRoot 'qdrant-snapshots'
New-Item -ItemType Directory -Path $snapshotTarget -Force | Out-Null

Push-Location $repo
$workerStopped = $false
try {
    docker compose stop worker | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Worker could not be paused for a consistent backup.' }
    $workerStopped = $true
    $output = docker compose exec -T api python -m app.backup
    if ($LASTEXITCODE -ne 0) { throw 'Pembuatan snapshot Qdrant gagal.' }
    $backupResult = $output | Select-Object -Last 1 | ConvertFrom-Json

    foreach ($snapshot in $backupResult.qdrant_snapshots) {
        $source = Join-Path (Join-Path $snapshotSource $snapshot.collection) $snapshot.name
        if (-not (Test-Path -LiteralPath $source)) { throw "Snapshot tidak ditemukan: $source" }
        $collectionTarget = Join-Path $snapshotTarget $snapshot.collection
        New-Item -ItemType Directory -Path $collectionTarget -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $collectionTarget
    }

    $staging = Join-Path $appData 'backup-staging'
    if (Test-Path -LiteralPath (Join-Path $staging 'metadata.sqlite3')) {
        Copy-Item -LiteralPath (Join-Path $staging 'metadata.sqlite3') -Destination $backupRoot
    }
    if (Test-Path -LiteralPath (Join-Path $staging 'transcripts')) {
        Copy-Item -LiteralPath (Join-Path $staging 'transcripts') -Destination $backupRoot -Recurse
    }

    $configTarget = Join-Path $backupRoot 'project-config'
    New-Item -ItemType Directory -Path $configTarget -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repo 'compose.yaml') -Destination $configTarget
    Copy-Item -LiteralPath (Join-Path $repo '.env.example') -Destination $configTarget
    Copy-Item -LiteralPath (Join-Path $repo 'README.md') -Destination $configTarget
    Copy-Item -LiteralPath (Join-Path $repo 'docs') -Destination $configTarget -Recurse

    $manifest = [ordered]@{
        created_at = (Get-Date).ToString('o')
        qdrant_snapshots = @($backupResult.qdrant_snapshots)
        metadata_included = (Test-Path -LiteralPath (Join-Path $backupRoot 'metadata.sqlite3'))
        transcript_files_included = (Get-ChildItem -LiteralPath (Join-Path $backupRoot 'transcripts') -File -ErrorAction SilentlyContinue | Measure-Object).Count
        secrets_included = $false
        source_videos_included = $false
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $backupRoot 'manifest.json') -Encoding utf8
    Get-ChildItem -LiteralPath $backupRoot -Recurse -File |
        Where-Object { $_.Name -ne 'sha256.csv' } |
        Get-FileHash -Algorithm SHA256 |
        Select-Object Path, Hash | Export-Csv -LiteralPath (Join-Path $backupRoot 'sha256.csv') -NoTypeInformation
    Write-Output "Backup dibuat: $backupRoot"
}
finally {
    if ($workerStopped) {
        docker compose start worker | Out-Null
    }
    Pop-Location
}
