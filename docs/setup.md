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
   docker compose --profile mcp up -d --build
   ```

5. Check `http://127.0.0.1:8000/health/ready` and inspect worker logs with `docker compose logs -f worker`.

ASR and embedding models are downloaded to `/data/models` when first needed. Reserve several gigabytes of free space on the data drive. These are local open-weight model downloads, not cloud inference. Avoid running multiple ingestion jobs at once.

## Automatic startup on Windows

Docker Desktop must start before its containers can start. In Docker Desktop, enable **Settings → General → Start Docker Desktop when you sign in to your computer**. On this PC, Docker Desktop is registered in the current Windows user's Startup registry entry and its `AutoStart` preference is enabled. This starts Docker Desktop after that user signs in; it does not start Docker services before Windows sign-in.

Every Compose service uses `restart: unless-stopped`, including the API, worker, MCP server, Qdrant, Redis, and Tailscale. Once a profile has been brought up successfully, Docker restarts its containers when the engine starts. Use the same profile when initially creating the stack:

```powershell
# Local MCP endpoint only
docker compose --profile mcp up -d --build

# Public remote MCP endpoint through Tailscale Funnel
docker compose --profile remote up -d --build
```

The `remote` profile includes the MCP service and Tailscale Funnel. Configure `TS_AUTHKEY` and persistent `APP_DATA_DIR` before starting it. Funnel is publicly accessible and persists through `tailscale/serve.json`. To intentionally keep the stack stopped, run `docker compose --profile remote stop` (or use the profile you started); a manual stop is respected by `unless-stopped` until a later explicit `up`.

After signing in or rebooting, check `docker compose ps` and the endpoint at `http://127.0.0.1:8000/health/ready`. Public MCP availability also depends on Tailscale reconnecting to the tailnet and Funnel being allowed by tailnet policy. Windows sleep, network availability, and the host remaining powered on determine whether remote access is reachable. The public endpoint has no per-client authentication; anyone who knows its URL can invoke MCP tools.

## Scanning and job status

The worker scans every 300 seconds and requires two stable observations at least 60 seconds apart. Files still being copied are deferred. To scan manually:

```powershell
$token = (Get-Content .env | Where-Object { $_ -match '^INGESTION_API_TOKEN=' }) -replace '^INGESTION_API_TOKEN=', ''
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/library/scan -Headers @{ 'X-Ingestion-Token' = $token }
docker compose exec worker python -m app status
```

Local operators can also run `docker compose exec worker python -m app scan`. Jobs finish with `completed`; videos without audio and duplicates are marked `skipped`; terminal failures are marked `failed`. Automatic retries use bounded backoff.

## API and MCP

FastAPI documentation is available at `http://127.0.0.1:8000/docs`. The local MCP Streamable HTTP endpoint is `http://127.0.0.1:8001/mcp`. For public remote access, configure `TS_AUTHKEY` in `.env`, then run `docker compose --profile remote up -d --build`. This profile starts MCP and Tailscale Funnel; MCP is forwarded over HTTPS publicly without opening a router port. See the [MCP guide](mcp.md) for URLs, state migration, and access limits.

## Cleanup and retention

Temporary WAV files are removed after each job. Model caches are retained to avoid repeated downloads. Transcripts and metadata are stored in `/data`; original videos remain in the library. Back up `/data/metadata.sqlite3`, `/data/transcripts`, and Qdrant snapshots using the coordinated procedure in `operations.md`.
