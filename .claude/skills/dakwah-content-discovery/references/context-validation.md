# Context Validation Checklist

For each candidate, inspect source material before and after the proposed span. Expand by neighboring chunks or 15–30 seconds when available; expand further if a pronoun, question, example, quotation, or conclusion depends on earlier material.

1. Identify the source video, transcript version, segment/chunk IDs, and exact time span.
2. Read the preceding thought and subsequent thought, including any question being answered.
3. Confirm the proposed excerpt is an exact contiguous transcript quote, with ASR uncertainty noted rather than silently edited.
4. Check negation, conditions, contrast, attribution, quotation boundaries, and whether a claim is later qualified or rebutted.
5. Ask whether a viewer can understand who/what the speaker refers to and why the conclusion follows.
6. Ensure no required proof, exception, or caution is clipped from the point.
7. Flag likely ASR errors whose correction could change meaning.
8. Mark Qur'anic, hadith, fiqh, or other religious references as `needs_human_verification` unless an authoritative check is actually documented.
9. Assign context risk and cite evidence references that explain the assessment.

Reject when the cut changes the speaker's meaning, reverses a negation, strips a material qualification, or cannot be validated against the source. Use `high` risk for unresolved attribution, materially uncertain ASR, contested references, missing context, or a claim whose surrounding passage may change its meaning. Do not present a high-risk candidate as ready for editing.
