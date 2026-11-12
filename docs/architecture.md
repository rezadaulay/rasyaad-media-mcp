# Architecture

## Runtime and data flow

```text
Windows library (read-only bind) -> scanner -> SQLite jobs -> one worker
                                                   |-> FFprobe metadata
                                                   |-> FFmpeg temporary WAV
                                                   |-> faster-whisper timestamp transcript
                                                   |-> sentence/time chunks -> SQLite + FTS5
                                                   `-> Qwen3 embeddings -> versioned Qdrant collection

AI client -> MCP tools -> FastAPI service -> SQLite / Qdrant / local embedding model
```

SQLite is the source of truth for status and metadata. Redis remains available from Phase 1, but Phase 2 uses SQLite tables for persistent jobs and transactional claims without a second broker. Worker concurrency is one. SQLite uses WAL and constraints. Qdrant stores vectors and retrieval payloads only.

The SQLite schema version is recorded through `PRAGMA user_version`. Version 1 is the baseline; version 2 adds Phase 3 proposal and review storage without deleting existing rows. The application exits with a clear message if the database version is newer than the application supports.

## Models and resources

- Default ASR is `large-v3`, CPU INT8, four threads, Indonesian language, with VAD enabled. This uses Phase 1 local benchmark results; the setting remains configurable.
- Default embedding model is `Qwen/Qwen3-Embedding-0.6B`, CPU, dimension 1024, batch size 2. The model is stored in `/data/models` (host D:). Collections are separated by model version hash and dimension.
- The API loads the embedding model on the first semantic search and keeps it while searches are active. It unloads the model after 10 idle minutes (`EMBEDDING_MODEL_IDLE_SECONDS`). The worker still unloads the model after each indexing batch. Search returns 503 while the worker runs a heavy CPU stage.
- The worker is limited to 5 GiB RAM / 4 CPUs; the API to 3 GiB / 1 CPU. Docker Desktop was measured at about 7.7 GiB for the Linux VM; monitor actual use as ingestion grows.

## Identity, deduplication, and file safety

`video_id` is deterministic from the library-relative path. Source files are read-only. Two matching fingerprint observations, separated by `STABLE_FILE_SECONDS`, are required before processing; the fast fingerprint uses metadata and sampled bytes. Duplicate candidates with matching size and sample fingerprints are verified using streaming SHA-256 before being marked `skipped`. A content change at the same path clears local derived results and is processed as a new job.

Temporary audio, SQLite, transcripts, model cache, and rendered clip exports are stored in `/data`; temporary WAV is deleted in a `finally` block. Final transcripts are written atomically, and partial transcripts are recorded every 100 segments. Clip jobs save an MP4 under `/data/clips`, derive an Indonesian SRT from the stored timestamp transcript, and run a second Arabic-detection/transcription pass with the same local Whisper model to produce an Arabic-script SRT. Subtitle timestamps are relative to clip time zero. The worker removes completed or failed clip artifacts after `CLIP_RETENTION_HOURS` (48 hours by default), checking hourly; job history stays in SQLite and reports when outputs have expired. Active and retryable jobs are excluded. Jobs recover safely after restart, but partial Whisper output is not resumed from a timestamp; the full ASR job restarts to avoid stitching text with incorrect context.

## Retrieval and integrity

Deterministic chunking groups timestamped segments at sentence boundaries and target lengths. Each chunk stores order, time, neighbors, segmentation version, and transcript segment references. No video clip files are created by indexing. Retrieval combines semantic top-k and FTS5 with reciprocal rank fusion; cosine similarity is not a probability of correctness. Source results expose only library-relative names and paths.

## Remote access and migration

The library is read-only and allowlisted through a single `/library` mount; the API does not accept arbitrary paths. Qdrant and Redis are available only on the Compose network. The API and local MCP are bound to host loopback. The Compose `remote` profile adds a Tailscale container sharing the MCP network namespace. Tailscale Funnel forwards public HTTPS to `127.0.0.1:8001`; configuration persists in `tailscale/serve.json`, and node identity persists under `${APP_DATA_DIR}/tailscale-state`, separately from the image. The public MCP endpoint does not authenticate individual callers, so anyone who knows the URL can invoke available MCP tools. Do not configure router port forwarding.

`POST /library/scan` requires `INGESTION_API_TOKEN`; the MCP adapter uses the same token to call the API. MCP does not verify an individual caller identity, and the explicitly configured public Funnel allows anyone who knows its URL to invoke MCP tools. For a Linux server, securely transfer Compose files, `.env`, and Tailscale state, or register a new tailnet node. Do not run two nodes using the same state. Perform an application backup/restore drill before cutover.

## Phase 3 proposal flow

The Claude Code skill reasons over the existing MCP list, search, transcript, and context tools. Proposal writes use the same MCP/API path and persist in SQLite `content_proposals`; source media stays read-only. API validation checks JSON Schema and source chunk, video, time, and quote references. Review is an explicit human decision. The system does not track rendered media or published-use status. See the [Phase 3 assessment](phase-3-readiness-assessment.md).
