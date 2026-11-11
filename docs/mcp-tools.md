# MCP Tools Reference

Rasyaad Media MCP exposes tools over Streamable HTTP at `/mcp`. Connect an MCP-compatible client to the local endpoint or the private Tailscale URL described in [MCP integration](mcp.md). The server delegates operations to the configured API and uses a shared ingestion token; remote clients do not have individual identities or reviewer accounts.

## Available tools

### Library and transcript tools

| Tool | Purpose | Inputs |
| --- | --- | --- |
| `list_videos` | List discovered videos and their latest ingestion state. | `status` (optional), `limit` (default 50), `offset` (default 0). |
| `get_video_metadata` | Read metadata and latest job state for a video. | `video_id`. |
| `get_transcript` | Read timestamped transcript segments, optionally within source-video seconds. | `video_id`, `start_time` and `end_time` (optional, seconds), `limit` (default 500), `offset` (default 0). Paginate to cover the full transcript. |
| `get_ingestion_status` | Read current ingestion jobs, stages, errors, and recent operational events. | None. |
| `trigger_library_scan` | Ask the worker to scan the configured allowlisted library. | None. Use after a completed copy or when checking for newly added media. |

### Search and context tools

| Tool | Purpose | Inputs |
| --- | --- | --- |
| `search_sermons` | Search indexed transcript chunks by keywords and meaning. | `query` (2–2000 characters), `limit` (default 10; maximum 50), optional `video_id`, optional `language`. |
| `get_segment_context` | Retrieve neighboring chunks or a time window around a transcript chunk. | `chunk_id`; `before_chunks` and `after_chunks` (default 1; maximum 50 each); optional `before_seconds` and `after_seconds` (maximum 3600). |

Search is a retrieval aid: similarity scores rank candidate passages and are not confidence, truth, or religious-authority scores. Verify wording, timestamps, and context against the source and transcript. `get_transcript`, `search_sermons`, and `get_segment_context` require a source that has completed ingestion.

### Editorial proposal tools

| Tool | Purpose | Inputs |
| --- | --- | --- |
| `save_content_proposal` | Validate and save a source-grounded content proposal. | `proposal` object, following `.claude/skills/dakwah-content-discovery/schemas/content-proposal.schema.json`. |
| `list_content_proposals` | List proposals with optional filters. | Optional `status`, `video_id`, `limit` (default 50), and `offset` (default 0). |
| `get_content_proposal` | Read a proposal by identifier. | `proposal_id`. |
| `update_proposal_review` | Record an editorial decision. | `proposal_id`, `decision` (`approved`, `rejected`, or `needs_revision`), optional `notes` (up to 4000 characters). |

Proposals must refer to a completed, registered source and retain verifiable chunk IDs, excerpts, and time bounds. The API validates proposal structure and source traceability. An approval is an editorial decision recorded in the library; it does not mean the clip was rendered or published. The shared MCP token does not identify which person made a review decision.

### Clip rendering tools

| Tool | Purpose | Inputs |
| --- | --- | --- |
| `request_clip_render` | Queue an MP4 render from an approved proposal. | `proposal_id`. |
| `request_vertical_clip_render` | Queue a centered 9:16, 1080 × 1920 MP4 render from an approved proposal. | `proposal_id`. |
| `get_clip_job` | Read render progress, errors, and export information. | `job_id`. |

Rendering requires a human-approved proposal and an unchanged, completed source. Rendered outputs are derived files; the source library remains read-only. When configured, a completed job can return a signed download URL that expires after 15 minutes.

## Suggested workflow

1. Call `list_videos` or `get_ingestion_status` to confirm the source is registered and completed.
2. Use `search_sermons` to locate candidate passages. For a single-video review, use paginated `get_transcript` calls to check full coverage; search results alone can omit relevant context.
3. Call `get_segment_context` and inspect source timestamps before drafting.
4. Save a traceable draft with `save_content_proposal`, then have a human editor verify the transcript, original recording, and religious context.
5. Record the review using `update_proposal_review`. Request a render only after approval, then poll `get_clip_job`.

## Current scope

The implemented ingestion pipeline focuses on video sources and their transcripts. Audio-only, general document, and book ingestion are planned capabilities, not currently available tools. See [project status](../README.md#project-status) for scope and known evaluation limits.
