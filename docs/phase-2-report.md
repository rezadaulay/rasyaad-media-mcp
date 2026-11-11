# Phase 2 Implementation Report

**Status:** Core implementation and a one-video end-to-end run are working. **Phase 2 is not complete**; QA across three audio conditions, a human reference transcript, and relevance evaluation remain blockers.

## Changes made

- SQLite metadata and job store with WAL, foreign keys, FTS5, atomic job claims, stage/progress tracking, retry/backoff, restart recovery, and transcript/chunk/event tables.
- Periodic and manual scanner: FFprobe metadata, read-only source, two stable observations, metadata and byte-sample fingerprints, and full SHA-256 checks for duplicate candidates.
- Single-concurrency worker: FFmpeg mono 16 kHz temporary audio, CPU faster-whisper, timestamp JSON and partial checkpoints, audio cleanup, deterministic timestamp/sentence chunks, and neighbor references.
- CPU Qwen3-Embedding-0.6B, batch encoding, Qdrant dimension 1024, collection version hash, deterministic point IDs, SQLite FTS5, and reciprocal rank fusion.
- FastAPI list/metadata/transcript/search/context/status/health/scan; scan requires token. MCP delegates to API and exposes 7 tools.
- Compose runtime pins CPU-only PyTorch, mounts the library read-only, stores model cache and temporary work on a data volume, and keeps Qdrant/Redis on the internal network.
- Backups include Qdrant snapshots, SQLite metadata, transcript JSON, non-secret configuration, and checksums; the worker pauses during snapshot creation.

## One-video run evidence

A sample source video remained read-only (1,124,860,600 bytes; FFprobe duration 886.927708 s). Its discovery job entered pending after the stability interval, completed successfully, and did not create a clip file.

- ASR: faster-whisper `large-v3`, CPU INT8, VAD enabled, 4 threads; 284 segments, 965 seconds of transcription (RTF 1.09). Partial checkpoints were saved every 100 segments.
- Initial embedding/indexing took about 148 seconds from model loading logs to ingestion completion (including initial Qwen model load/cache). Total ingestion from a clean retry to completion took about 23:56, including model download; audio extraction was not measured separately.
- Resources: ASR peak was about 3.47 GiB RAM; embedding worker was about 4.0 GiB under the 5 GiB limit. The Qwen model was in the local model cache. Final API cold search took 43.7 seconds and the API process retained about 2.33 GiB after loading the query model. The Docker VM exposed about 7.72 GiB; monitor load as additional services are added.
- Segmentation/index: eight chunks and eight points; a versioned Qdrant collection at dimension 1024. Temporary WAV was removed.
- The final-image search API returned three results for a query about advice and guarding speech, with relative source, timestamp, text, and score; the final MCP call returned two timestamped results from the same API. Human relevance review is pending.
- The context API returned the target chunk and its neighbors; a timestamp transcript window returned 44 segments from 523–619 seconds.
- The MCP client saw seven tools and called status/search; a scan without a token was rejected with 403. After restarting the final image, MCP still showed the job as completed and the worker alive.
- The backup contained 21 files with no checksum mismatches. A restored SQLite copy passed `integrity_check` with one video, 284 segments, and eight chunks. Restoring the Qdrant snapshot into a temporary collection returned eight points at dimension 1024; the test collection was removed.

## Issues and recovery

The first model download used HF Xet and failed to write to a Windows bind mount. Setting `HF_HUB_DISABLE_XET=1` allowed the cache download to complete; two retries were recorded before ingestion succeeded. The source file was unchanged.

The initial image collected zero tests because the test folder had not been copied into the image. The Dockerfile was updated. The final build ran eight unit tests, all passing in 7.86 seconds; coverage includes schema/FTS, atomic claim/retry, deterministic segmentation, file identifiers/fingerprints, and duplicate copies.

## Closure blockers

1. Three videos/excerpts covering different audio conditions (clean, noisy, and Arabic terms) and human reference transcripts are unavailable. Transcripts, especially Arabic, Quranic, and hadith text, require manual review before being considered faithful.
2. No relevance judgments exist for search queries; do not report precision@k or retrieval accuracy claims.
3. Duplicate-copy has unit coverage; duplicate, changed-content, and file-moved branches have not been tested with multiple real files.
4. Restart was observed during a retry-pending job and through backup pause/start; a hard kill during ASR and a Qdrant/worker restart with an active job remain untested.
5. Backup restore was tested on a database copy and temporary collection, not as full-machine disaster recovery or Linux migration.
6. The Windows build requires lifecycle review; no forced upgrade was performed.

**Decision:** continue only with Phase 2 QA. Do not start Phase 3 until audio and retrieval blockers are addressed.
