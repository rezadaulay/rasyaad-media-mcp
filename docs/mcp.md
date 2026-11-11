# MCP Integration

The MCP server uses Streamable HTTP at `http://127.0.0.1:8001/mcp`. The `mcp` profile exposes local access only. The `remote` profile adds a Tailscale container that shares the MCP network namespace; Tailscale Serve forwards HTTPS to `127.0.0.1:8001`. Review `tailscale/serve.json` and tailnet ACLs to confirm the intended access scope.

Read tools include `list_videos`, `get_video_metadata`, `get_transcript`, `search_sermons`, `get_segment_context`, and `get_ingestion_status`. `trigger_library_scan` starts a scan; MCP uses an internal token from `.env` to call the API. Phase 3 adds `save_content_proposal`, `list_content_proposals`, `get_content_proposal`, and `update_proposal_review`. Save and review use the same internal token. Authorized remote MCP users share that trust boundary. MCP does not provide per-user reviewer identity or OAuth. Restrict tailnet ACLs to trusted operators. An approved proposal is still only a proposal; it does not prove that a video was rendered or published.

The Claude Code skill is in `.claude/skills/dakwah-content-discovery/`. See the [Phase 3 usage guide](phase-3-usage.md). For single-video analysis, the agent must retrieve the full transcript with pagination and check total coverage; semantic search is not a substitute. Proposal history is available, but there is no record of which segments were actually used or published.

## Private Tailscale setup

1. Create a one-off, non-ephemeral Tailscale auth key for this container. If device approval is enabled for the tailnet, mark the key pre-approved. Set `TS_AUTHKEY` in the local `.env`. Never commit or share this key.
2. Set `APP_DATA_DIR` to persistent storage. Tailscale node identity is stored in `${APP_DATA_DIR}/tailscale-state` so a restart does not register a new node.
3. Start the remote profile:

   ```powershell
   docker compose --profile remote up -d --build
   ```

4. After Tailscale connects and HTTPS is enabled for the tailnet, use the URL shown by Tailscale with the `/mcp` suffix, for example `https://rasyaad-mcp.<tailnet-name>.ts.net/mcp`. Client devices must join the tailnet and be allowed by its ACL.

The MCP adapter currently uses a shared ingestion token; it does not authenticate each client separately. Do not expose this service publicly or enable Tailscale Funnel. For migration, preserve Tailscale state securely or register a new node, then verify ACLs and MCP access.
