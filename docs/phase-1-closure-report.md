# Phase 1 Closure Report: Setup and Preparation

**Project:** Rasyaad Media MCP  
**Date:** November 11, 2026  
**Status:** **Closed — local foundation ready for further development**

## Summary

Phase 1 established a working Docker foundation with persistent storage, an internal network, API, Qdrant, Redis, an idle worker, local MCP, backup and recovery procedures, and Linux migration guidance. A CPU benchmark also showed that the tested Whisper configuration can process a 20-minute sermon locally.

This phase covered setup and preparation only. At closure, the system had not scanned a library, consumed worker jobs, created embeddings, or generated Reels candidates.

## Verified environment and status

- Windows host with a 6-core / 12-thread AMD CPU, 16 GB RAM, and a 4 GB AMD GPU.
- Docker Desktop runs through WSL2. Docker's virtual disk is stored on a separate data drive.
- `docker compose config --quiet` passed.
- Compose services ran; API, Qdrant, and Redis health checks passed. API liveness returned `alive`, and readiness returned `ready`.
- API and local MCP were bound to loopback. Redis and Qdrant remained on the internal Compose network.
- The source library was mounted read-only. Worker concurrency was one. FFmpeg and FFprobe were available in the worker image.
- Resource limits and Linux migration guidance were documented.

## Backup, recovery, and security

- A weekly local backup task was registered and its execution succeeded.
- Backups include a manifest and checksums. A Qdrant snapshot restore drill into a test collection passed; the synthetic collection was later removed.
- `.env` contains local secrets and is excluded from Git. Redis and Qdrant are not exposed to the host/LAN; local MCP is loopback-bound and initially offered read-only status tools.

## ASR benchmark

A sample sermon video was 14 minutes 46.9 seconds long. In an earlier benchmark, faster-whisper `small`, CPU INT8, four threads processed the full audio in 207.95 seconds (RTF 0.234), with 1.21 GB peak RSS. Linear extrapolation for a 20-minute video is about 4 minutes 41 seconds.

For the first three minutes, all models received the same mono 16 kHz excerpt:

| Model | Transcription time | RTF | Peak RAM | Sample notes |
|---|---:|---:|---:|---|
| faster-whisper `small` INT8 | 67 seconds | 0.37 | 1.25 GB | Fast, but Arabic term transliteration had more errors. |
| faster-whisper `large-v3` INT8 | 174 seconds | 0.96 | 3.42 GB | Best on the checked hadith quotation; it recognized the quoted Arabic phrases more accurately. |
| Qwen3-ASR-1.7B BF16 CPU | 630 seconds | 3.50 | 5.67 GB | More errors in the Arabic excerpt; first-time setup needed another 420 seconds to download weights. |

This is a qualitative assessment of a small sample, not WER/CER; a complete human-verified reference transcript was unavailable. Nemotron 3.5 was not tested because the host had no NVIDIA GPU and the Docker/WSL memory available was about 7.7 GiB, below its target deployment configuration. No video was sent to an external service.

**Model direction:** use faster-whisper `large-v3` for local ASR and a paid agent such as Claude for MCP-connected analysis. This is a direction based on the initial sample, not a completed integration. Nemotron can be reconsidered if a suitable NVIDIA GPU environment becomes available.

## Phase 1 Definition of Done

| Criterion | Result |
|---|---|
| Host, WSL2, virtualization, and disk audit | Passed; hypervisor/WSL2 were active and Docker data was moved to a separate drive. BIOS firmware flags were not read directly. |
| Compose configuration and base services | Passed; latest status was verified. |
| Network, persistence, resource limits, and portable paths | Passed; documented in `docs/architecture.md`, `docs/phase-1-plan.md`, and `compose.yaml`. |
| API, Qdrant, Redis, worker, MCP, health/readiness | Passed; API readiness was healthy. Worker remained idle as scoped. |
| Secret handling, loopback binding, read-only library mount | Passed based on configuration and verification. |
| Scheduled backup and snapshot restore drill | Passed; task was active and restore drill succeeded. |
| CPU ASR benchmark on a sermon sample | Passed as throughput and initial comparison; corpus-wide accuracy was not assessed. |
| No library indexing or Reels candidate generation | Met; these activities were outside Phase 1 scope. |

**Decision:** Phase 1 setup criteria were met. Phase 1 is closed.

## Remaining operational risks

- Timestamped backups have no automatic retention. Review disk use regularly. Source video is not backed up by the application.
- A backup on one local disk does not protect against failure of that disk; create a separate or offsite copy before storing production data.
- ASR accuracy across the full library and retrieval quality have not been evaluated. Arabic and religious terminology require human references and review.
- Migration to a Linux server has not been tested because a target server was unavailable; migration steps are documented.

## Related documents

- Plan and acceptance criteria: `docs/phase-1-plan.md`
- Sanitized host audit: `docs/host-audit.md`
- Service and backup verification: `docs/verification.md`
- Three-minute ASR comparison: `docs/asr-comparison-first-180s.md`
- Operations guide: `docs/operations.md`
