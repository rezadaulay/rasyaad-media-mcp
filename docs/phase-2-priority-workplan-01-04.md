# Phase 2 Priority Work Plan

## Search filtering and explicit video reprocessing

### Objective

Complete two technical priorities before Phase 2 closure: ensure keyword search returns only active, completed sources, and give an operator a safe, explicit way to request reprocessing for one video.

### Scope

This plan covers priorities 1 and 4 from the audit. Deferred audio/transcript/relevance QA and other work such as multi-folder support, schema migrations, and model reindexing are outside this subtask.

### Implementation sequence

1. **Define correct search behavior.** Add a `completed` source-status condition to FTS/keyword queries. Preserve semantic result filtering, video/language/time filters, reciprocal rank fusion, and the current response shape.
2. **Add search regression tests.** A match from a `completed` video may appear. Matches from `pending`, `processing`, `retry_pending`, `failed`, `skipped`, or missing sources must not appear. Check hybrid results when lexical matches are filtered out.
3. **Design safe reprocessing.** Add an operator action through the API using the existing ingestion token. Accept only `video_id`; verify the source remains under the allowlisted library. Reject unknown IDs, missing sources, and duplicates while a job is pending or processing.
4. **Persist reprocessing intent.** Create a durable job that records a fresh-transcription requirement. After restart or retry, the worker must honor the flag instead of reusing old transcript JSON as a new result.
5. **Keep data consistent during processing.** While a video is pending or being reprocessed, do not serve its old index as current data. Show clear status and failure reasons. Never alter or delete the source video.
6. **Complete tests and operator docs.** Add relevant service/API/worker tests. Update API and MCP documentation if the interface changes. Run focused and existing tests, then report actual outcomes and changed files.

### Acceptance criteria

| Priority | Evidence required |
|---|---|
| Keyword search returns only completed sources | A matching chunk from a completed source can appear; results from other states or unavailable videos do not appear; filters and hybrid ranking still work. |
| Reprocessing requires an explicit request | An authorized operator can request by `video_id`; the system validates video and source, avoids duplicate active jobs, persists the request, performs fresh transcription/indexing, reports status/errors, and leaves source bytes unchanged. |

### Verification boundaries

This subtask implements only these two priorities. Technical tests cover search behavior and reprocessing. They do not replace human QA for transcript accuracy or search relevance. Record tests actually run, results, documentation changes, and evidence that the source video did not change. Do not mark all of Phase 2 complete based on this subtask alone.

## Implementation prompt

Work in the existing project. Implement only these agreed Phase 2 priorities:

1. Prevent keyword search from returning chunks whose source video is not in `completed` status.
2. Add a safe, explicit operator-triggered way to reprocess one video by `video_id`.

Before changing code, inspect `app/service.py`, `app/api/main.py`, `app/database.py`, `app/worker/pipeline.py`, `app/worker/__main__.py`, `app/mcp_server.py`, and relevant docs/tests. Preserve the SQLite job queue, shared service layer, single-worker model, read-only library mount, and token-protected mutation pattern.

Do not add multi-folder support, schema migrations, chunk-limit changes, model reindexing, audio QA, or Phase 3 work. Do not alter or delete source videos.

For keyword search, require the associated video to have `status='completed'`. Keep semantic-search behavior, filters, ranking, and response fields. Add regression tests for completed, pending, processing, retry-pending, failed, skipped, missing/inactive sources, and hybrid fusion after lexical filtering.

For reprocessing, add an operator-triggered API action such as `POST /videos/{video_id}/reprocess`, protected by `X-Ingestion-Token`. A CLI path may be added if consistent with existing conventions, but do not accept arbitrary filesystem paths. Keep queue/state changes in the service/database layer and keep the API thin. Update API/MCP documentation when the interface changes. Validate the video ID and confirm its source remains under the configured allowlisted library root. Return clear authorization, not-found, and conflict errors. Do not create a duplicate active job; return the existing job or a clear conflict. Persist the explicit reprocessing intent so worker restarts and retries perform a fresh transcription/indexing pass. Do not serve old results as current while reprocessing. Ensure status and errors are visible and source bytes remain unchanged.

Add focused unit/API tests for completed-only lexical filtering, authorization, unknown IDs, missing sources, duplicate active requests, queue creation, and worker handling of the fresh-transcription flag. Run focused and existing tests when the environment permits. Report exact commands and outcomes; never claim unrun tests passed. Review the diff for changes outside these two priorities.

At completion, summarize changed files, behavior, tests and results, and any limitation that blocks acceptance. Do not declare Phase 2 fully closed; deferred QA and audit items are outside this subtask.
