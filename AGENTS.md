# Agent Guidelines

## Project Purpose and Scope

Rasyaad Media MCP is a local-first library for processing and searching Islamic media through the Model Context Protocol (MCP). The current implementation focuses on sermon videos, transcripts, retrieval, editorial proposals, and clip rendering. Audio-only, general document, and book ingestion are planned capabilities; do not describe them as implemented.

## Architecture

- `app/worker/` scans the configured media library and runs ingestion jobs.
- `app/service.py` contains shared media and retrieval services.
- `app/api/` exposes the FastAPI HTTP API.
- `app/mcp_server.py` exposes MCP tools over Streamable HTTP.
- SQLite stores application metadata, jobs, transcripts, and content proposals. Qdrant stores vector data. Redis is present in Compose; check current code before assuming it is part of a processing path.
- `compose.yaml` defines the local services and optional private Tailscale profile. `Dockerfile` builds the CPU-oriented application image.

Read `docs/architecture.md`, `docs/mcp.md`, and the relevant API or operations guide before changing service boundaries or data flow.

## Data and Security Boundaries

- Treat the source media library as read-only. Keep derived data, model caches, databases, and rendered clips in the configured application data directory.
- Never add `.env`, credentials, SSH keys, Tailscale state, source media, private library samples, local databases, model caches, or generated exports to version control.
- Preserve path allowlisting and token checks. Do not introduce arbitrary host-path access or expose internal services publicly. The MCP Funnel exception is explicitly authorized and documented below.
- Public MCP access through Tailscale Funnel is enabled by explicit operator request and persisted in `tailscale/serve.json`. Preserve this setting unless the operator explicitly asks to change it. Do not enable router port forwarding. The public MCP endpoint does not authenticate inbound callers individually; anyone who knows the URL can invoke available MCP tools.
- Avoid destructive data or volume cleanup unless the task explicitly requires it and the affected data is identified.

## Content Integrity

- Automated transcripts can contain recognition errors. Retrieval scores are ranking signals, not measures of truth or religious authority.
- Preserve source video, transcript, and timestamp references in proposals and search results.
- Keep editorial and religious-source review as a human decision before publication. Do not imply that an approved proposal means a clip was published.

## Development Conventions

- Target Python 3.12 and keep dependencies explicit in the requirements files.
- Preserve CPU-only PyTorch installation in the Docker image unless GPU support is deliberately designed and documented.
- Validate external input at API, MCP, and file-processing boundaries. Preserve database migrations, job recovery behavior, and existing API contracts unless the task calls for a change.
- Use English for repository-facing names and text, including the repository name and description, documentation filenames and contents, branch names, and commit messages. Prefer lowercase kebab-case for new branch names and concise English commit subjects.
- Update the relevant guides when changing API routes, MCP tools, environment variables, Compose services, storage, security boundaries, or operational procedures.
- Prefer focused changes that follow existing module and test organization. Do not add generated artifacts or private machine-specific paths.

## Useful Commands

Validate Compose configuration:

```powershell
docker compose config --quiet
```

Start the local MCP profile:

```powershell
docker compose --profile mcp up -d --build
```

Inspect readiness and worker activity:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready
docker compose logs -f worker
```

Request a scan from the worker container:

```powershell
docker compose exec worker python -m app scan
```

Run the Python test suite when validation is requested:

```powershell
pytest -q
```
