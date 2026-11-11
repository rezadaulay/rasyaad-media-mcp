# Editorial Scoring Rubric (v1.0)

This is an editorial assessment, not a prediction of views or virality. Score evaluated dimensions from 0–100. Store each dimension's base weight, status, and score. Normalize the weighted average across evaluated dimensions only; show evaluated-weight coverage as the sum of evaluated base weights divided by 100.

| Dimension | Weight | Guidance |
|---|---:|---|
| Message benefit | 25 | Meaningful, beneficial, accurate point grounded in the source |
| Context independence | 25 | Understandable without hidden question, prior claim, or omitted qualification |
| Opening hook | 20 | Clear and engaging opening that remains faithful |
| Clarity | 15 | Coherent spoken thought and transcript intelligibility |
| Audience relevance | 10 | Fit for the requested audience/topic |
| Verified technical quality | 5 | Audio/video quality only when actually inspected |

If media was not inspected, set technical status to `not_evaluated` and score to `null`. Recompute `overall_score` over evaluated dimensions only; never award a guessed technical score. `evaluation_coverage` contains evaluated weight (0–1), evaluated dimension names, and a note about the limits. If no scored dimensions, no overall score can be produced.

## Gates before score

Reject candidates with unverifiable source, invalid time range, meaning distortion, misleading cuts, missing essential context, or duplicate content. A high numeric score does not override rejection. Context risk is `low`, `medium`, or `high`; high-risk candidates should normally be rejected or explicitly held for special review.

## Recommendation bands

- 85–100: strong candidate, subject to editorial approval.
- 70–84: viable with noted weakness or boundary review.
- 50–69: weak; normally exclude from a short ranked batch.
- Below 50: reject.

Explain scores with evidence. Keep `strengths` and `weaknesses` concrete. State the recommendation, not just a number.
