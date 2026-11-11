# Phase 3 Dependency & Readiness Assessment

Audit date: 2026-11-11. Source review covered the repository documentation, API, shared service, MCP adapter, SQLite schema, worker architecture, and existing QA report. Initial short health probes timed out, but the running stack was subsequently checked after recovery: API health returned ready, SQLite schema v2 and the proposal table were present, the library returned two completed videos, and MCP registered all 11 tools.

## Available capabilities

| Need | Existing implementation | Readiness |
|---|---|---|
| Video inventory and pagination | MCP `list_videos`; API `/videos` | Available, status filter supported |
| Video metadata and ingestion state | MCP `get_video_metadata`; API `/videos/{id}` | Available |
| Timestamped transcript | MCP `get_transcript`; API pagination (`limit`, `offset`, time filters) | Available; agent must page and verify full coverage |
| Semantic plus keyword discovery | MCP `search_sermons`; API hybrid retrieval | Available; completed sources only; ranking scores are not truth confidence |
| Neighboring context | MCP `get_segment_context`; API neighboring chunks/time windows | Available |
| Ingestion status | MCP `get_ingestion_status` | Available |
| Transcript/chunk source provenance | SQLite transcript segments and semantic chunks carry times, IDs, transcript references | Available; transcript version is ASR model metadata rather than a dedicated immutable version ID |
| Proposal/review persistence | Added SQLite v2 table, API endpoints, and MCP tools in this phase | Runtime migration v2, authorized save, list, MCP retrieval, and rejected invalid-token write verified |

The existing MCP code exposes seven Phase 2 tools: six read tools and `trigger_library_scan`. It delegates to the shared FastAPI service. Read tools are enough to retrieve a transcript comprehensively in pages; no new Phase 2 endpoint is necessary for transcript pagination.

## Missing dependencies and limitations

- No `list_used_segments` capability exists. Proposal history can be checked, but actual rendered/published use is not tracked, so “unused content” cannot be guaranteed.
- No visual/audio inspection tool is exposed by MCP. Technical quality must remain `not_evaluated`; timestamp boundaries are ASR segment-level and must be checked in Phase 4 rendering.
- Live retrieval found two completed videos. Full transcript coverage and one real transcript-derived proposal were checked for `a sample video`; the proposal was schema-validated and persisted. This is not the required three-video human editorial evaluation. Existing Phase 2 documentation still leaves transcript accuracy and retrieval relevance QA open.
- No user identity or per-user authorization exists on the MCP transport. New write operations inherit the existing shared ingestion-token trust boundary. Restrict remote access to trusted tailnet operators.
- Transcript metadata has ASR model and creation metadata but no immutable transcript revision ID. Proposals retain a caller-provided `transcript_version`; production orchestration should standardize it from transcript metadata.

## MCP compatibility and security

Skill discovery is compatible with Claude Code's `.claude/skills/<name>/SKILL.md` convention. Existing source tools provide IDs, timestamps, excerpt text, and context. Added MCP write tools delegate to the same API and do not accept arbitrary filesystem paths or shell commands. Proposal persistence validates schema, completed source video, exact registered filename, chunk ownership, transcript excerpt, time overlap, and source duration. Writes require `X-Ingestion-Token`; MCP currently forwards the shared internal token. Proposal responses are limited to 256 KB; pages are capped at 200 rows. Review notes are capped at 4,000 characters.

## Proposed changes and decisions

1. Add the standalone agent skill, progressive references, proposal JSON Schema, deterministic validator, simulated evaluation fixture, and human QA checklist.
2. Reuse the existing list/transcript/search/context tools; no duplicate search service or inference pipeline.
3. Add a minimal SQLite schema v2 proposal table plus four API/MCP operations: save, list, get, and record review.
4. Keep proposal status separate from rendering/publication. There is deliberately no claim of production or “used” state.
5. Do not close Phase 2 or claim Phase 3 Definition of Done until multi-video/topic/library behavior evaluation and human editorial QA are performed.
