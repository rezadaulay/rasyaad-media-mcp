# Safe Media Copy SOP

Use this procedure when copying a video into the library watched by the Rasyaad Media MCP worker. The scanner ignores any file or directory whose name contains `.partial` (case-insensitive). Keep that marker in the temporary name until the copy has finished and been checked. This is an operator instruction; it does not change the scanner configuration.

## Recommended procedure

1. Choose a unique final filename with a supported video extension, such as `weekly-study-2026-11-11.mp4`. Do not overwrite a video already in the library.
2. Copy the source into the library using a temporary filename that contains `.partial`, for example `weekly-study-2026-11-11.mp4.partial`. Keep it in the same library directory and volume as the final file so the final rename is local and atomic.
3. Wait for the copy operation to finish. Do not trigger a scan while the file is being copied.
4. Compare the source and copied file sizes. For higher assurance, compare SHA-256 hashes as shown below. If the sizes or hashes differ, copy again and keep the temporary filename marked `.partial`.
5. Rename the completed temporary file to the final video filename, removing `.partial`. Do not alter the file contents after this point.
6. Allow the worker to discover it. The worker requires two matching file observations at least 60 seconds apart; it scans every 300 seconds by default. Check status or logs to confirm ingestion has completed before using transcript and search tools.

## PowerShell example

Set `$source` to the completed source file and `$library` to the host path configured by `LIBRARY_HOST_PATH` in `.env`:

```powershell
$source = 'D:\Incoming\weekly-study-2026-11-11.mp4'
$library = 'D:\Rasyaad\library'
$finalName = 'weekly-study-2026-11-11.mp4'
$partial = Join-Path $library ($finalName + '.partial')
$final = Join-Path $library $finalName

Copy-Item -LiteralPath $source -Destination $partial

$sourceInfo = Get-Item -LiteralPath $source
$copyInfo = Get-Item -LiteralPath $partial
if ($sourceInfo.Length -ne $copyInfo.Length) {
    throw 'Copied file size differs from the source. Keep the .partial file and copy again.'
}

$sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash
$copyHash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
if ($sourceHash -ne $copyHash) {
    throw 'Copied file hash differs from the source. Keep the .partial file and copy again.'
}

if (Test-Path -LiteralPath $final) {
    throw 'Final filename already exists. Choose a unique name; do not overwrite indexed media.'
}
Move-Item -LiteralPath $partial -Destination $final
```

The rename should be within the same directory and filesystem. If the source is already inside the watched library, use `Move-Item` to give it a `.partial` name before copying or moving its contents into place; do not use this sequence to overwrite a registered file.

## After the rename

- The worker scans automatically. To request an immediate scan, run `docker compose exec worker python -m app scan` after the rename.
- Check the worker with `docker compose logs --tail 100 worker` or inspect jobs with `docker compose exec worker python -m app status`.
- A file may take time to process after discovery. Wait for its job to reach `completed` before querying its transcript or searching it.
- If ingestion fails, inspect the reported error and resolve the cause before retrying. Do not delete application databases or volumes as a routine recovery step.

## If a file was copied under its final name

If a copy was accidentally started without `.partial`, let it finish before requesting a scan. Compare its size and, when possible, SHA-256 hash with the source. If it was already discovered, do not edit or replace it in place: stop and resolve the existing job and registered source before retrying with a new unique filename. This avoids an indexed record pointing at changing file contents.
