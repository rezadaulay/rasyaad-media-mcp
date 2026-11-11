# Using the Dakwah Content Discovery Skill

Claude Code discovers the skill at `.claude/skills/dakwah-content-discovery/SKILL.md` when invoked by name or when the task clearly matches sermon clip discovery.

Example prompts:

- "Analyze video ID `<video_id>` and suggest up to five Reels candidates. Review the full transcript, flag context risks, and save qualifying proposals for review."
- "Find up to five candidates about raising children in the library. Prefer 30–60 seconds, varied sources, and self-contained context. Report coverage and any parts you could not inspect."
- "Explore the library for useful messages that are not already represented in previous proposals. If published-use history is unavailable, state that you could not confirm whether a clip has been used before."

Expected MCP flow: use `list_videos` and `get_video_metadata` to establish source eligibility; page through `get_transcript` for full-video analysis; use `search_sermons` to find topic or library leads; validate boundaries with `get_segment_context` and transcript time windows; then call `save_content_proposal` for each schema-valid candidate. Present the returned ID and `proposed` status. An editor's explicit decision can be recorded with `update_proposal_review`. Never mark a candidate approved without that review result.

To validate an exported proposal file locally, run:

```powershell
python .claude/skills/dakwah-content-discovery/scripts/validate-proposal.py path\to\proposals.json
```

The validator dependency is listed separately in `requirements-phase3.txt`; install it with `pip install -r requirements-phase3.txt` when validating outside Docker.

The validator accepts one JSON object or an array. It checks JSON Schema, timestamp/duration consistency, weighted score and evaluation coverage, technical score status, duplicate IDs, and strong same-video overlap. Backend persistence independently checks source ownership and verbatim excerpts. The validator alone cannot establish that a quotation is faithful to the speaker's intent.
