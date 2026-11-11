# Testing and QA Results

## Phase 1 evidence

- Compose services, health/readiness checks, read-only library mount, Qdrant snapshot restore drill, and baseline backup are recorded in `phase-1-closure-report.md` and `verification.md`.
- faster-whisper `small` processed the full 14:46.9 sample in 207.95 seconds (RTF 0.234; peak RSS 1.21 GB).
- Qualitative comparison of a 180-second excerpt: `large-v3` INT8 performed best on the checked Arabic quotation (174 seconds, 3.42 GB peak RSS); `small` took 67 seconds / 1.25 GB; Qwen ASR 1.7B on CPU took 630 seconds / 5.67 GB. WER/CER is unavailable because a complete human reference transcript does not exist.

## Phase 2 results (November 11, 2026)

| Area | Result | Evidence / limitation |
|---|---|---|
| Database, discovery, and segmentation unit tests | 8 tests | Passed 8/8 in the final image in 7.86 seconds. |
| Discovery, stability, and deduplication | A video was registered after the stability interval and queued; repeated scan was unchanged; identical-copy test verified one pending job. | Passed; changed-content detection was not exercised with a real modified video. |
| Timestamped transcript | One 886.93-second video; 284 segments; ASR took 965 seconds (RTF 1.09). | Pipeline completed; human transcript review is pending. |
| Chunk and context | Eight chunks; timestamp range covered; context endpoint returned target and neighbors. | Smoke check passed. |
| Embedding and Qdrant | Qwen3-Embedding-0.6B, dimension 1024, eight points in a versioned collection. | Dimension and count check passed. |
| API retrieval | Final-image query returned three results with source, chunk ID, timestamp, and cosine score in 43.7 seconds cold. | Smoke check passed; no relevance labels, so accuracy is unmeasured. |
| MCP | Client saw seven tools, called status and semantic search; final search returned two timestamped results. | Status and search passed after final restart. |
| Scan access control | Scan without a token was rejected with 403. | Passed. |
| Persistent restart | API/worker/MCP restarted; job remained completed, eight Qdrant points remained, and worker heartbeat recovered. | Passed for idle/completed state; hard interruption during live ASR remains untested. |
| Resource and temporary files | ASR peak about 3.47 GiB; embedding worker peak about 4.0 GiB / 5 GiB; temporary audio count was zero. | Within worker limit in this run. |
| Backup and restore | 21 checksums, no mismatches; SQLite integrity `ok` with one video, 284 segments, eight chunks; Qdrant restore copy returned eight points / 1024 dimensions. | Populated restore drill passed. |
| Three audio conditions and retrieval judgments | Only one source video was available. | Not met; blocks Phase 2 closure. |

ASR and semantic retrieval smoke checks are not a religious-content accuracy certificate. For acceptance, review clean, noisy, and Indonesian-Arabic samples against human references and record omissions, incorrect terms, and timestamp drift. Label a small retrieval set before reporting precision@k.
