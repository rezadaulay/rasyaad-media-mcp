# API Reference

Local base URL: `http://127.0.0.1:8000`. Swagger UI: `/docs`.

| Method | Path | Description |
|---|---|---|
| GET | `/health/live`, `/health/ready`, `/health/status` | Liveness, dependencies, resource and job counts |
| GET | `/videos?status=&limit=&offset=` | List videos with pagination |
| GET | `/videos/{video_id}` | Safe metadata and latest job |
| GET | `/videos/{video_id}/transcript?start_time=&end_time=&limit=&offset=` | Timestamped transcript |
| GET | `/search?query=&limit=&video_id=&language=` | Hybrid semantic and lexical search |
| GET | `/chunks/{chunk_id}/context?...` | Neighboring chunks or time range |
| GET | `/ingestion/status` | Current stage, errors, and latest event |
| POST | `/library/scan` | Scan the allowlisted library; requires `X-Ingestion-Token` |
| POST | `/videos/{video_id}/reprocess` | Queue transcript and index regeneration; requires `X-Ingestion-Token` |
| POST | `/clip-jobs?proposal_id=` | Queue rendering for an approved proposal; requires `X-Ingestion-Token` |
| POST | `/clip-jobs?proposal_id=&render_preset=vertical_9_16` | Queue a centered 1080×1920 9:16 social clip; requires `X-Ingestion-Token` |
| GET | `/clip-jobs/{job_id}` | Render status, error, and output location |
| GET | `/clip-download/{job_id}?expires=&signature=` | Download an MP4 using a signed, expiring link |
| POST | `/content-proposals` | Validate and save a draft proposal; requires `X-Ingestion-Token` |
| GET | `/content-proposals?status=&video_id=&limit=&offset=` | List and filter proposals with pagination |
| GET | `/content-proposals/{proposal_id}` | Retrieve a structured proposal |
| POST | `/content-proposals/{proposal_id}/review` | Record an editor decision; requires `X-Ingestion-Token` |

Search responses include a relative source path, timestamp, matched text, score, and `score_explanation`. A cosine score is a ranking signal, not a measure of factual confidence.

Semantic and keyword search return only videos with `completed` status. Transcript and chunk context are available after a video has finished processing.

Submit a reprocess request without a body using an ID from `GET /videos`. The `202` response includes `video_id`, `job_id`, and the initial `pending` status. Poll `GET /videos/{video_id}` for status, stage, and error details. The worker creates a new transcript and index, including on retry. The source video remains unchanged.

- `403`: token is empty or incorrect.
- `404`: ID is not registered or the source file is missing.
- `409`: a job is active (`pending`, `processing`, or `retry_pending`), the source path is invalid, or scan metadata does not indicate an audio stream.

Proposals use `.claude/skills/dakwah-content-discovery/schemas/content-proposal.schema.json`. Saving accepts `draft` or `proposed`, requires a `completed` video, a filename matching registered metadata, source chunks belonging to that video, a verbatim excerpt found in those chunks, and a time range overlapping the source and ending within the video duration. The maximum proposal body is 256 KB. Validation failures return `422`; conflicting final review decisions return `409`. Review body: `{"decision":"approved|rejected|needs_revision","notes":"..."}`; notes are limited to 4,000 characters. Write operations use the shared ingestion token and do not identify reviewers individually. The proposal list is not a record of published content.

Rendering accepts only an `approved` proposal with a completed source video still inside the library, and a duration of at most 600 seconds. The `202` response contains a `job_id`; duplicate active jobs return the existing job. A new MP4 is written to `/data/clips/<job_id>.mp4`; the source video is unchanged. The status endpoint returns the failure type and message when a job fails.
