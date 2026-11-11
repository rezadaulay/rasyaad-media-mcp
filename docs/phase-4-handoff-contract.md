# Phase 4 Handoff Contract

The discovery skill hands off one human-approved proposal at a time. The persisted proposal JSON is the contract, with these fields required by the editor:

- `proposal_id`, `video_id`, and `source_video` identify the source.
- `transcript_version`, `source_chunk_ids`, `evidence_references`, and `transcript_excerpt` preserve traceability.
- `start_time`, `end_time`, and `duration` are source-video seconds derived from transcript segment timestamps. These are not frame-accurate edit points.
- `status` must be `approved`; `review_decision` must also be `approved` before production.
- `editing_brief`, `subtitle_emphasis`, `visual_suggestions`, `suggested_format`, and warnings guide editing without authorizing changes to message or adding religious claims.
- `context_risk` and transcript/ASR warnings must remain visible to the editor.

Phase 4 should inspect the source at both boundaries, adjust cut points only while preserving the entire thought, and record actual rendered boundaries separately. It must not assume audio/video quality was evaluated by Phase 3. No rendering, reframing, subtitle generation, or publishing is part of this contract's Phase 3 implementation.
