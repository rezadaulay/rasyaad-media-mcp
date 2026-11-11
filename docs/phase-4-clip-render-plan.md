# Phase 4 clip rendering plan

## Objective

Let an operator render a copy of a human-approved sermon proposal through MCP, while preserving the original video and keeping long FFmpeg work out of the request thread.

## Scope and flow

1. Reuse approved, source-validated content proposals as the clip specification. MCP accepts only `proposal_id`, never a filesystem path or caller-supplied timestamps. `request_clip_render` preserves source dimensions; `request_vertical_clip_render` makes a centered vertical crop for social media.
2. The API validates that the proposal is approved, its source video is still completed and inside the configured library, its time range is valid, and the requested duration is no longer than 10 minutes.
3. Persist a separate SQLite clip job and return its `job_id`. A duplicate active render for the same proposal and render preset returns the existing job.
4. The single worker renders the clip with FFmpeg to a temporary file under `/data/clips`, validates the output, and atomically publishes `<job_id>.mp4`. It rechecks the source fingerprint before and after rendering and never writes to the library.
5. Vertical output is center-cropped to 9:16 and encoded as 1080×1920 H.264/AAC MP4. This static crop does not track a speaker who moves away from center.
6. MCP exposes request and status tools. The status includes the render preset, export path, dimensions, duration, clear errors, and a short-lived HTTPS download URL for completed clips.

## Acceptance criteria

- Only an approved proposal for a completed video can be rendered.
- Unknown proposals, unapproved proposals, missing or out-of-library sources, invalid ranges, and durations over 600 seconds are rejected with clear errors.
- Repeated requests while a render is pending or processing return the same job and do not duplicate work.
- Original and vertical renders of the same proposal use separate jobs; duplicate requests for either preset reuse that preset's active job.
- A render is durably queued, survives worker restart, and reaches completed or failed status with a useful error.
- Successful output is a decodable MP4 with the requested duration within codec tolerance, and exists only in the export directory.
- Vertical render output is exactly 1080×1920, centered, and 9:16; original render output behavior remains unchanged.
- Source file bytes and metadata remain unchanged.
- MCP request and job-status tools work through the shared API. API, MCP, and worker docs describe the flow and limits.
- The completed job URL serves only that MP4 over HTTPS, requires a time-limited HMAC signature, and rejects expired or altered links.
- Focused tests and the full existing suite pass.

## Verification

Use generated media and a temporary library/data directory. Exercise authorization, proposal validation, duplicate requests, restart/retry persistence, FFmpeg output probing, and source hash equality. Then run the complete test suite and validate Compose configuration.
