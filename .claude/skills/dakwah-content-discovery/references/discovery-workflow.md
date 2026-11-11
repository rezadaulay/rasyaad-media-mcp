# Discovery Workflow

## Mode A: one video

Fetch metadata and require `completed`. Page the entire transcript. Default page size 500, honoring the MCP tool's actual cap. Continue offsets until the returned segment count reaches `total`; verify stable total, ordered sequence numbers, monotonic timestamps, and end coverage. Use multiple passes: (1) map topic/argument across the transcript, (2) generate candidate spans, (3) expand context and validate, (4) score and deduplicate. If coverage is incomplete, say so and label the run partial.

## Mode B: topic

Run semantic search for the user's phrase and useful paraphrases/synonyms; compare exact-term search results when lexical search is available. Search results generate leads, not final evidence. Retrieve neighboring chunks and transcript segments around each result, verify source metadata, and keep multiple candidates only when their message and time span are distinct.

## Mode C: library

Paginate completed videos. Record total and inspected count; don't imply full-library coverage after sampling. Search across eligible videos, then expand and validate top leads. Check prior proposal/use records if available. If absent, disclose reuse status is unknown. Seek variety by video and theme, subject to relevance and quality.

## Boundary and deduplication

Use source segment boundaries as evidence; select whole sentence/thought boundaries. Preferred duration is 30–60s; acceptable 20–90s unless user configures it. Reject negative or out-of-duration timestamps. Mark boundary precision as segment-level when word alignment is unavailable. For a batch, merge candidates from the same video when their intervals substantially overlap and they express the same idea; also remove semantic duplicates across videos when the point is materially the same. Preserve a distinct candidate if the editorial message is genuinely different.

## Run record

Report mode, requested scope, videos seen/checked, transcript pages and segment ranges checked, gaps/errors, candidate pool size, rejected count and primary reasons, valid count, and reuse-history availability.
