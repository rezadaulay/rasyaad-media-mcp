# MCP Integration

The MCP server uses Streamable HTTP at `http://127.0.0.1:8001/mcp`. The `mcp` profile exposes local access only. The `remote` profile adds a Tailscale container that shares the MCP network namespace and exposes HTTPS publicly through Tailscale Funnel to `127.0.0.1:8001`. Funnel configuration is persisted in `tailscale/serve.json`.

Read tools include `list_videos`, `get_video_metadata`, `get_transcript`, `search_sermons`, `get_segment_context`, and `get_ingestion_status`. `trigger_library_scan` starts a scan; MCP uses an internal token from `.env` to call the API. Phase 3 adds `save_content_proposal`, `list_content_proposals`, `get_content_proposal`, and `update_proposal_review`. Save and review use the same internal token. MCP does not provide per-user reviewer identity or OAuth. With public Funnel enabled, anyone who knows the URL can invoke available tools. An approved proposal is still only a proposal; it does not prove that a video was rendered or published.

The Claude Code skill is in `.claude/skills/dakwah-content-discovery/`. See the [Phase 3 usage guide](phase-3-usage.md). For single-video analysis, the agent must retrieve the full transcript with pagination and check total coverage; semantic search is not a substitute. Proposal history is available, but there is no record of which segments were actually used or published.

See the [MCP tools reference](mcp-tools.md) for every available tool, its inputs, and workflow constraints. For instructions on copying media into the watched library without indexing an incomplete copy, follow the [safe media copy SOP](media-ingestion-sop.md).

## Remote Tailscale setup

1. Create a one-off, non-ephemeral Tailscale auth key for this container. If device approval is enabled for the tailnet, mark the key pre-approved. Set `TS_AUTHKEY` in the local `.env`. Never commit or share this key.
2. Set `APP_DATA_DIR` to persistent storage. Tailscale node identity is stored in `${APP_DATA_DIR}/tailscale-state` so a restart does not register a new node.
3. Start the remote profile:

   ```powershell
   docker compose --profile remote up -d --build
   ```

4. After Tailscale connects and Funnel is allowed by tailnet policy, use the URL shown by `tailscale funnel status` with the `/mcp` suffix, for example `https://rasyaad-mcp.<tailnet-name>.ts.net/mcp`. Public clients do not need to join the tailnet.

The MCP adapter currently uses a shared ingestion token for its calls to the API; it does not authenticate inbound MCP clients individually. Anyone who knows the public Funnel URL can invoke the exposed MCP tools. For migration, preserve Tailscale state securely or register a new node, then verify Funnel status and MCP access.
