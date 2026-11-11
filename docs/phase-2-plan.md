# Phase 2 Backlog and Technical Plan

| ID | Task | Dependencies | Module | Acceptance | Status after local implementation |
|---|---|---|---|---|---|
| F2-00 | Phase 1 and host audit | — | docs/host-audit.md, Compose/runtime | Container, mount, disk, Qdrant, and ASR baseline recorded | Complete |
| F2-01 | DB schema, event, job lifecycle/recovery | — | app/database.py | SQLite WAL, atomic claim, retries, FK/indexes | Implemented; all unit tests passed; retry recovered during real ingest |
| F2-02 | Library scanning, FFprobe, stability, duplicate check | F2-01 | app/discovery.py | Rescan idempotent; changed file invalidates descendants | Real file discovered and queued; unchanged rescan; identical-file dedup unit test passed |
| F2-03 | Audio extraction, ASR, output/checkpoint | F2-01/02 | worker/pipeline.py | Timestamp JSON, cleanup, no-audio/error states | Real 886.93 s video transcribed: 284 segments, 16:05 ASR; audio temp removed |
| F2-04 | Timestamp/sentence chunks, neighbors | F2-03 | app/segmentation.py | ordered boundaries and source refs | 8 chunks persisted; API returned 3 neighboring chunks; deterministic unit tests passed |
| F2-05 | Batch embedding and Qdrant versioning | F2-04 | app/embedding.py, pipeline | deterministic upsert and exact dimension | Qwen loaded, 1024 dimensions, 8 vectors; separate snapshot restored and count verified |
| F2-06 | Search, transcript/context/status APIs | F2-01/05 | app/service.py, api/main.py | source/timestamps, pagination, score explanation | Final-image semantic + FTS search returned 3 timestamped results in 43.7 s cold; transcript/context API verified |
| F2-07 | MCP service adapter | F2-06 | app/mcp_server.py, Compose | seven tools call same API; scan token protected | MCP listed 7 tools and executed status/search; unauthenticated scan returned 403 |
| F2-08 | Operational docs, backup/restore, QA | F2-01..07 | docs, scripts | documented evidence and limitations | 21-file backup, 0 checksum mismatches; restored DB/Qdrant passed; audio QA limitations remain |

## Status definitions

Implementation and a one-video end-to-end run are verified. Phase 2 remains incomplete until three audio conditions are evaluated against human references, restart/retry edge cases and repeated-copy dedup are tested, and retrieval relevance is judged with a labeled set. Do not proceed to Phase 3.

## Key decisions

1. Keep the Phase 1 Compose and data mount conventions.
2. Use SQLite for durable queue/status; keep Redis internal for future use without introducing a second queue state source.
3. Use local faster-whisper `large-v3` based on the project's comparison sample, while leaving model parameters configurable.
4. Use Qwen3 Embedding 0.6B, Apache-2.0, 1024 dimensions as the initial candidate. It loaded on CPU; the worker reached about 4.0 GiB RSS under its 5 GiB limit. First API query took about 28 seconds; the API process retained about 2.2 GiB after query.
5. Keep topic labels and summaries out of the source transcript. No LLM inference is required in ingestion.
6. No Phase 3 clip selection, editing, publication, or scoring is included.
