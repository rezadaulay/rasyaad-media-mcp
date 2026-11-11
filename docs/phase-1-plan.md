# Phase 1: Setup and Preparation

## Scope

Build a local platform that can be run, inspected, backed up, and migrated to Linux. Phase 1 does not scan the library, transcribe videos, create embeddings or indexes, or discover Reels candidates.

## Host assumptions at audit time

- Windows 11 Pro, 6-core / 12-thread Ryzen CPU, 16 GB RAM, and 4 GB Radeon GPU.
- Docker Desktop, Docker Engine, Compose, and a WSL2 Linux engine.
- Docker data is stored on a separate data drive. Exact host paths are configured locally and are intentionally not recorded in this public repository.

## Stages, dependencies, and deliverables

| Stage | Dependency | Implementation / deliverable |
|---|---|---|
| 1. Audit | Docker Desktop installed | `docs/host-audit.md`; review daemon, WSL, virtualization, drives, and Docker data location. |
| 2. Storage | Disk audit | Prepare library, data, snapshot, and backup directories; mount source media read-only. |
| 3. Architecture | Storage | `docs/architecture.md`; internal Compose bridge, loopback API, named database volumes, optional MCP profile. |
| 4. Repository and configuration | Architecture | `compose.yaml`, Dockerfile, requirements, `.env.example`, `.dockerignore`, README. Keep local secrets in ignored `.env`. |
| 5. Base services | Repository | FastAPI, idle worker, Qdrant, Redis, FFmpeg/FFprobe, health checks, named volumes, initial resource limits. |
| 6. MCP | API running | Optional local Streamable HTTP MCP, loopback only, read-only status tool; no shell, media, or indexing tools. |
| 7. Models and queue | Base services | Record CPU-first strategy and concurrency one; queue consumption and indexing are not enabled yet. |
| 8. Operations | Healthy services | Stdout logging, Qdrant snapshots, backup plan, health checks, and inspection procedures. |
| 9. Migration | Portable configuration | Host paths controlled by `.env`; containers use only `/library` and `/data`; document Linux migration. |

## Initial AI strategy

- **ASR:** A one-video benchmark used faster-whisper 1.2.1, `small`, CPU INT8, four threads, beam size 5, and Indonesian language. A 14:46.9 video took 207.95 seconds (RTF 0.234), produced 248 segments, and peaked at 1.21 GB RSS. Linear estimate for a 20-minute video is about 4:41. This measured throughput, not accuracy against a human reference; an opening greeting was duplicated and subtitles require human review. Benchmark requirements pin PyAV `<19` because faster-whisper 1.2.1 is incompatible with PyAV 19.
- **Embeddings:** Initial candidate was `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, a multilingual baseline that includes Indonesian. Record model revision, dimensions, and preprocessing; evaluate retrieval before production use.
- **Future ASR target:** NVIDIA Nemotron 3.5 Transcribe was selected for later evaluation because it supports Indonesian, Arabic, and code-switching. It was not installed or run because the host did not meet its official deployment requirements. See `docs/asr-model-decision.md`.
- **LLM:** Optional, CPU-first, and small/quantized. Do not run alongside heavy ASR on a 16 GB machine. The AMD GPU is not used in the baseline.
- **Queue:** Redis was prepared as a broker, but the worker did not yet consume jobs. The later pipeline should use idempotent jobs, bounded retries, failure records, and a relational database for durable status.
- **Vector store:** Qdrant stores embeddings and search payloads. Do not store full videos or long transcripts as payloads.

## Initial resource budget

| Service | Maximum RAM | Maximum CPU |
|---|---:|---:|
| API | 1 GB | 1 core |
| Qdrant | 1.5 GB | 1.5 cores |
| Redis | 512 MB | 0.5 core |
| Worker | 4 GB | 4 cores |
| Optional MCP | 512 MB | 0.5 core |

The combined maximum is about 7.5 GB with all services active, close to the measured 7.7 GB WSL/Docker VM limit. Avoid running an LLM with ASR and monitor host conditions. If workload approaches the limit, stop MCP when unused or reduce the worker limit. Do not change `.wslconfig` automatically without checking other Windows workloads.

## Security and operations

- Secrets in `.env` are excluded from Git; `.env.example` contains placeholders only.
- The API and MCP bind to `127.0.0.1`; Redis and Qdrant are not published to the host/LAN.
- The host library is mounted read-only; outputs and snapshots use separate mounts.
- Logs go to stdout/stderr; never log secrets or full transcript contents.
- Backup scripts copy Qdrant snapshots and metadata to a separately configured destination with a manifest and checksums. Verify a restore drill before relying on a backup.
- Docker data is on a separate drive. Exact paths and free-space measurements remain local configuration.

## Verification and Definition of Done

```powershell
docker info
wsl --status
wsl --list --verbose
docker compose config --quiet
docker compose ps
docker compose logs --tail 100 qdrant redis api worker
Invoke-RestMethod http://localhost:8000/health/live
docker compose exec worker ffmpeg -version
docker compose exec worker ffprobe -version
docker stats --no-stream
```

Phase 1 is ready when the host and storage layout are documented; Compose validates; Qdrant, Redis, API, and worker are healthy; optional MCP is loopback-only; named volumes are active; the library mount is read-only; FFmpeg/FFprobe are available; resource limits are recorded; `.env` is ignored; and backup and snapshot recovery have been demonstrated. The final preparation step evaluates a CPU-first model on a representative sermon sample; library indexing remains a later phase.

## Open risks

1. The combined Compose resource ceiling is close to the measured WSL/Docker memory limit.
2. Backup and snapshot recovery do not include source videos; create a separate source-media backup plan.
3. ASR accuracy against verified transcripts and retrieval quality on a representative corpus remain unmeasured. Throughput benchmarks do not establish accuracy.
4. Durable catalog metadata, job status, and automatic indexing require later phases.

## Linux migration

1. Install Docker Engine and the Compose plugin on the Linux server.
2. Copy the repository without `.env`, then create a new `.env` with Linux volume paths.
3. Transfer the library, snapshots, and metadata using a manifest and checksums.
4. Run `docker compose config --quiet`, pull or build pinned images, then start Qdrant and Redis.
5. Restore Qdrant snapshots and validate health and queries; start API, worker, and MCP as needed.
6. Cut over only after verifying source files and restored results. Application code should not contain host-specific drive paths.
