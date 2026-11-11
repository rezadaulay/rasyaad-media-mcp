# Setup and Operations

## Prerequisites

1. Use Docker Desktop with Linux containers. Confirm `docker compose ps` reports healthy dependencies after startup.
2. Configure a local `.env`: set `APP_DATA_DIR` to a data drive, `LIBRARY_HOST_PATH` to the media library, and provide Qdrant credentials and the ingestion token. Do not commit `.env`.
3. Place media to process in the library directory. The `/library` container mount is read-only.
   Follow the [safe media copy SOP](media-ingestion-sop.md) to stage large files with a `.partial` name until the copy is complete.
4. Validate and start the services:

   ```powershell
   docker compose config --quiet
   docker compose build
   docker compose up -d --build
   ```

5. Check `http://127.0.0.1:8000/health/ready` and inspect worker logs with `docker compose logs -f worker`.

ASR and embedding models are downloaded to `/data/models` when first needed. Reserve several gigabytes of free space on the data drive. These are local open-weight model downloads, not cloud inference. Avoid running multiple ingestion jobs at once.

## Scanning and job status

The worker scans every 300 seconds and requires two stable observations at least 60 seconds apart. Files still being copied are deferred. To scan manually:

```powershell
$token = (Get-Content .env | Where-Object { $_ -match '^INGESTION_API_TOKEN=' }) -replace '^INGESTION_API_TOKEN=', ''
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/library/scan -Headers @{ 'X-Ingestion-Token' = $token }
docker compose exec worker python -m app status
```

Local operators can also run `docker compose exec worker python -m app scan`. Jobs finish with `completed`; videos without audio and duplicates are marked `skipped`; terminal failures are marked `failed`. Automatic retries use bounded backoff.

## API and MCP

FastAPI documentation is available at `http://127.0.0.1:8000/docs`. The local MCP Streamable HTTP endpoint is `http://127.0.0.1:8001/mcp`. For private remote access, configure `TS_AUTHKEY` in `.env`, then run `docker compose --profile remote up -d --build`. This profile starts MCP and Tailscale Serve; MCP is forwarded over HTTPS within the tailnet without opening a router port. Client devices must join the tailnet and be permitted by its ACL. See the [MCP guide](mcp.md) for URLs, state migration, and access limits.

## Cleanup and retention

Temporary WAV files are removed after each job. Model caches are retained to avoid repeated downloads. Transcripts and metadata are stored in `/data`; original videos remain in the library. Back up `/data/metadata.sqlite3`, `/data/transcripts`, and Qdrant snapshots using the coordinated procedure in `operations.md`.
