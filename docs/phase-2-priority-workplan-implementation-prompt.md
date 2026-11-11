# Subtask Prompt: Implement Phase 2 Priorities 1 and 4

Work in the existing project at `C:\Users\ROG\Documents\ChatGPT\Rasyaad MCP`. Implement only these two agreed Phase 2 priorities:

1. Prevent keyword search from returning chunks whose source video is not in `completed` status.
2. Add a safe, explicit operator-triggered way to reprocess one video by `video_id`.

## Before changing code

- Inspect `app/service.py`, `app/api/main.py`, `app/database.py`, `app/worker/pipeline.py`, `app/worker/__main__.py`, `app/mcp_server.py`, and the relevant docs/tests.
- Preserve the existing SQLite job queue, shared service layer, single-worker model, read-only library mount, and token-protected mutation pattern.
- Do not add multi-folder support, schema migrations, chunk-limit changes, model reindexing, audio QA, or Phase 3 work in this task.
- Do not alter or delete source videos.

## Work A: Filter keyword search by active source status

- Update the FTS/keyword query so it can return chunks only when the associated video has `status='completed'`.
- Keep the existing semantic-search status behavior and all query filters, ranking, and response fields intact.
- Add regression coverage showing a matching chunk from a completed video can appear, while matches from pending, processing, retry-pending, failed, skipped, or missing/inactive sources cannot appear.
- Confirm hybrid fusion still behaves correctly when lexical matches are filtered out.

## Work B: Add explicit reprocessing by video ID

- Add an operator-triggered API action such as `POST /videos/{video_id}/reprocess`, protected by the existing `X-Ingestion-Token` check. A CLI path may also be added if it fits the existing conventions, but do not accept arbitrary filesystem paths.
- Put queue/state changes in the service/database layer; keep the API thin. Update API documentation and MCP documentation if the exposed interface changes.
- Validate that the video ID exists and its source still exists under the configured allowlisted library root. Return clear not-found/conflict/authorization errors.
- If a job for that video is already pending or processing, do not create a duplicate job; return the existing job or a clear conflict.
- For a new explicit request, create a durable job and make the worker perform a fresh transcription/indexing pass rather than silently reusing an old completed transcript JSON. Track the explicit reprocess intent in durable job data (for example, the existing checkpoint field) so worker restarts and retries preserve the intent.
- Ensure old results are not served as current while the video is pending/reprocessing, and ensure success/failure is reflected in video and job status with an understandable error. Keep video source bytes unchanged.

## Verification

- Add focused unit/API tests for completed-only lexical filtering, authorization, unknown IDs, missing source, duplicate active requests, queue creation, and worker honoring the fresh-transcription flag.
- Run the focused tests and the existing test suite if the environment permits. Report exact commands and outcomes; do not claim unrun tests passed.
- Review the diff for accidental changes outside the two priorities.

## Acceptance criteria

1. Keyword search returns matching chunks only from completed videos; inactive or missing sources never leak into results, and hybrid ranking remains intact.
2. An authorized operator can request reprocessing by video ID; the request is durable, safe, and does not duplicate an active job; the worker performs a fresh pass; status and errors are visible; source video files remain unchanged.

At completion, summarize changed files, behavior, tests and results, and any limitation that blocks either acceptance criterion. Do not declare Phase 2 fully closed; the other deferred QA and audit items are outside this subtask.