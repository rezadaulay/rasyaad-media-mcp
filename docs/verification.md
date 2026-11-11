# Phase 1 Verification Results (November 10, 2026)

See the [Phase 1 closure report](phase-1-closure-report.md).

## Verified

- Docker Desktop and the `desktop-linux` engine were running under WSL2.
- `docker compose config --quiet` passed after Compose adjustments.
- Qdrant, Redis, API, and worker containers were running; health checks for Qdrant, Redis, and API were healthy.
- API `GET /health/ready` returned `ready`; the check queried Qdrant with an API key and pinged Redis.
- MCP Streamable HTTP was available on `127.0.0.1:8001`. An MCP client discovered `get_engine_status` and received `api_alive: true`, `phase: setup`, `indexing_enabled: false`.
- Worker was idle and logs indicated indexing was disabled.
- `ffmpeg` and `ffprobe` were available in the worker image.
- Worker `/library` mount was verified as read-only; `/data` was writable.
- Qdrant and Redis used named Docker volumes; their ports were not published to the host.
- `scripts/backup.ps1` created a backup with manifest, checksums, and a test collection snapshot.
- Qdrant restore drill succeeded: the test snapshot was recovered into a test collection and the point count returned to one. See [Qdrant snapshot documentation](https://qdrant.tech/documentation/operations/snapshots/).
- After verification, the synthetic collection and its local snapshots were removed through the Qdrant API.
- The weekly backup task was registered and a Task Scheduler run succeeded.
- A local `.env` was created with random API keys and is listed in `.gitignore`; never include it in a backup or public repository.

## Phase 1 limits

- Timestamped backups have no automatic retention.
- The source media library was an empty prepared directory at the time of the original setup verification. No video was scanned or processed in that phase.
- The Docker virtual disk was moved to a separate data drive. Exact host paths and free-space values are intentionally omitted from this public record.
- faster-whisper `small` was downloaded and tested on one sample video only. CPU INT8, four threads: 886.93 seconds of audio completed in 207.95 seconds (RTF 0.234), 248 segments, Indonesian detected, 1.21 GB peak RSS. This verifies throughput, not accuracy against a reference transcript; the initial output duplicated an opening greeting. Embeddings had not yet been downloaded or tested.
- MCP had no authentication at this stage; it was bound to loopback and did not need to run when unused.

## ASR benchmark notes (November 10, 2026)

- Benchmark ran in a temporary container with four CPU and 5 GB RAM limits; the video mount was read-only and only one sample was read.
- Initial installation failed because faster-whisper 1.2.1 passed a `metadata_errors` parameter removed in PyAV 19. The benchmark passed after pinning `av<19` (PyAV 18.1.0). See the upstream [faster-whisper issue](https://github.com/SYSTRAN/faster-whisper/issues/1589).
- Result: 14:46.9 of audio, 3:27.9 processing time, RTF 0.234; linear estimate for a 20-minute video is 4:41. Estimates depend on content and host load.
- Phase 1 conclusion: Docker/Compose, storage, backup/recovery, base services, and CPU ASR throughput were verified. Phase 1 closed as setup. ASR accuracy and embedding/retrieval evaluation remained future work. No library indexing or Reels candidate generation ran.

## Current usage boundary

The service foundation works, but setup alone is not an indexing engine. Do not expect the worker to process videos or create Reels candidates until the later pipeline phases are configured. To stop the MCP profile, run `docker compose --profile mcp down`; this does not delete volumes.
