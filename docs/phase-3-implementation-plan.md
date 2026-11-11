# Phase 3 Implementation Backlog

| ID | Work | Dependencies | Acceptance criteria | Status |
|---|---|---|---|---|
| F3-01 | Audit Phase 2 and MCP | Existing repository | Capabilities, gaps, and trust boundary recorded | Done by code/docs and live API/MCP checks |
| F3-02 | Agent skill and editorial references | F3-01 | Claude Code skill supports three discovery modes and progressive disclosure | Implemented |
| F3-03 | Proposal contract and validator | F3-02 | Strict JSON Schema; timestamp, duration, score, coverage, and duplicate validation | Implemented; included in passing 25-test full suite |
| F3-04 | Durable proposal/review storage | Existing SQLite/API/MCP | Schema migration; source-validated save, paginated list/get, human review action | Migration and save/list/get verified live; human review decision not exercised on the real proposal |
| F3-05 | Discovery behavior evaluation | MCP and real indexed sources | Single video, topic, library coverage; context/negation/quote behavior checked | Blocked on live MCP and real transcript access |
| F3-06 | Human editorial QA | At least three real videos or agreed sample | Reviewer records context, boundaries, relevance, titles, and risks | Pending; no real transcript sample was available |
| F3-07 | Phase 4 handoff | F3-03 and approved proposals | Versioned handoff fields and approval gate documented | Contract documented; production consumer not available |

## Architecture

```text
Claude Code agent + dakwah-content-discovery skill
   |-- read MCP -> existing MCP adapter -> FastAPI -> SQLite / Qdrant
   |                    list, metadata, transcript pages, search, context, status
   `-- write MCP -> proposal API -> SQLite v2
                        schema + source reference validation; human review state
```

The agent performs editorial reasoning. No local LLM or video inference pipeline is introduced. SQLite remains the metadata source of truth; Qdrant remains retrieval infrastructure. The video library stays read-only. Proposal records reference existing `video_id` and chunk IDs and store the validated structured proposal. Phase 4 consumes only human-approved proposals.

## Implementation status and remaining acceptance work

The repo contains the skill, contract, validator, proposal persistence endpoints/tools, tests, simulated fixture, and operational documentation. API/MCP access, additive migration, one real-source proposal, and the full automated suite were verified. Topic-based and autonomous library behavior were not evaluated end to end by an agent; three-sermon human review is still required before claiming the Phase 3 Definition of Done.
