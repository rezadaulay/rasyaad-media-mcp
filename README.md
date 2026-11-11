# Rasyaad Media MCP

**A local-first media library and Model Context Protocol (MCP) server for Islamic content teams.**

Rasyaad Media MCP helps dakwah teams turn recorded talks and study sessions into a searchable, reusable source library. Local services handle repeatable processing such as media inspection, audio extraction, transcription, segmentation, indexing, and retrieval. Paid AI models can then focus on work that benefits from language and editorial reasoning, such as finding themes, drafting clip proposals, and planning social content.

The project is intended to support workflows for short-form video and carousel content while keeping source references attached to the material. Human editorial and religious-source review remains part of the publishing workflow.

## Project status

This repository contains a working Docker-based pipeline focused on sermon video ingestion, transcript search, MCP access, editorial proposals, and approved-proposal clip rendering. The wider goal includes reusable libraries for video, audio, text, documents, and books. Audio-only, general document, and book ingestion are future capabilities; they are not implemented by the current pipeline.

The indexed corpus and quality checks are still limited. One available video has been processed end to end. Audio-condition QA, human transcript and timestamp review, and broader retrieval evaluation remain open; see the phase reports in [`docs/`](docs/).

## What is implemented

- Read-only scanning of an allowlisted media library, with video metadata and ingestion status.
- Local audio extraction and timestamped Indonesian speech transcription using faster-whisper.
- Transcript segmentation, SQLite full-text search, local embeddings, and Qdrant vector search.
- Hybrid lexical and semantic retrieval with source-relative paths, transcript excerpts, and timestamps.
- FastAPI endpoints and MCP Streamable HTTP tools for searching and accessing the library.
- Structured content proposals with source-reference validation and human review decisions.
- MP4 clip rendering for approved proposals, including a centered 1080 × 1920 vertical preset.
- A Claude Code skill for source-grounded clip discovery and editorial review.
- Optional public remote access through Tailscale Funnel.

## Design principles

1. **Keep routine processing local.** The application uses local CPU inference for transcription and embeddings, plus local media and database services.
2. **Use paid AI where it adds value.** Connect an MCP-compatible AI client for tasks such as synthesis, editorial decisions, and content drafting.
3. **Keep the source traceable.** Search results and proposals retain transcript, video, and timestamp references.
4. **Keep source media unchanged.** The media library is mounted read-only; derived data and rendered clips are stored separately.
5. **Keep people in the review loop.** Search rankings and automated transcripts do not establish factual or religious correctness.

## Architecture

```text
Read-only video library
        │
        ▼
Scanner and SQLite job queue
        │
        ├── FFprobe metadata
        ├── FFmpeg temporary audio extraction
        ├── faster-whisper timestamped transcript
        ├── transcript chunks and SQLite FTS5 index
        └── local embeddings and Qdrant vector index
                         │
                         ▼
          FastAPI service and MCP server
                         │
                         ▼
       Claude, ChatGPT, or another MCP client
```

SQLite stores application metadata, job state, transcripts, and proposals. Qdrant stores vector embeddings and retrieval payloads. Docker Compose runs the API, worker, Qdrant, Redis, and optional MCP and Tailscale services. See the [architecture guide](docs/architecture.md) for data flow, resource limits, storage, and access boundaries.

## Requirements

- Docker Desktop with Linux containers on Windows, or Docker Engine and the Docker Compose plugin on Linux.
- A media directory and a separate persistent data directory with enough space for transcripts, indexes, model downloads, and rendered clips.
- Several gigabytes of free disk space for the local ASR and embedding model caches.
- A CPU that can run local transcription and embeddings. Inference speed depends on model, language, CPU, and media length.

GPU acceleration is not required by the current Docker image; it installs CPU-only PyTorch.

## Quick start

### 1. Configure environment

Copy the sample configuration and edit `.env`:

```powershell
Copy-Item .env.example .env
```

Set `APP_DATA_DIR` to a persistent writable directory and `LIBRARY_HOST_PATH` to the directory containing source videos. Replace the placeholder `QDRANT_API_KEY` and `INGESTION_API_TOKEN` with long random secrets. Keep `.env` private and do not commit it.

The sample uses Windows drive paths. On Linux, replace them with absolute Linux paths, for example `/srv/rasyaad/data` and `/srv/media/dakwah`. Store the `.env` file securely on the target PC or server; it is not part of this repository.

### 2. Validate and start local services

```powershell
docker compose config --quiet
docker compose --profile mcp up -d --build
```

Check readiness at <http://127.0.0.1:8000/health/ready>. The local MCP endpoint is <http://127.0.0.1:8001/mcp>. API documentation is available at <http://127.0.0.1:8000/docs>.

The worker checks for new media every five minutes. To request a scan manually:

```powershell
docker compose exec worker python -m app scan
```

Follow processing logs with:

```powershell
docker compose logs -f worker
```

For MCP client setup, remote access, backup, restore, and migration instructions, read the [MCP integration guide](docs/mcp.md) and [setup and operations guide](docs/setup.md).

## Repository layout

```text
app/                 FastAPI API, MCP server, ingestion, indexing, and rendering
.claude/             Claude Code skill, references, schema, and validation helper
docs/                Setup, API, architecture, operations, QA, and phase reports
scripts/             Local maintenance and helper scripts
tailscale/            Private Serve configuration for the remote Compose profile
tests/               Automated and phase-specific test cases
compose.yaml         Local and optional remote service definitions
Dockerfile           Container image definition
.env.example         Safe environment-variable template
```

## Documentation

- [Setup and operations](docs/setup.md)
- [API reference](docs/api.md)
- [MCP integration](docs/mcp.md)
- [MCP tools reference](docs/mcp-tools.md)
- [Safe media copy SOP](docs/media-ingestion-sop.md)
- [Architecture](docs/architecture.md)
- [Testing and verification](docs/testing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Backup and operations](docs/operations.md)
- [Phase 1 plan and closure report](docs/phase-1-plan.md) · [closure report](docs/phase-1-closure-report.md)
- [Phase 2 plan and report](docs/phase-2-plan.md) · [priority work plan](docs/phase-2-priority-workplan-01-04.md) · [report](docs/phase-2-report.md)
- [Phase 3 usage, readiness, and report](docs/phase-3-usage.md) · [readiness assessment](docs/phase-3-readiness-assessment.md) · [report](docs/phase-3-report.md)
- [Phase 4 clip rendering plan](docs/phase-4-clip-render-plan.md)

## Security and content review

- Do not commit `.env`, authentication keys, API tokens, Tailscale state, source media, local databases, model caches, or generated exports.
- Source media is mounted read-only. Keep the API, Qdrant, and Redis endpoints on trusted networks; only MCP is exposed publicly through the explicitly configured Funnel.
- The optional Tailscale Funnel setup provides public HTTPS access. MCP does not authenticate inbound callers individually; anyone who knows the URL can invoke available tools. Enable this access only when public access is intended.
- Automated transcripts may contain recognition errors and are not verified religious quotations. Retrieval scores rank results; they are not confidence or truth scores. Review the original source, wording, timestamps, and religious context before publication.

## License

This project is licensed under the [MIT License](LICENSE).
