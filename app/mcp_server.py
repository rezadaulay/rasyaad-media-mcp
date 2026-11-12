"""MCP adapter delegates all operations to the shared FastAPI service."""
import json
import hashlib
import hmac
import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from mcp.server.mcpserver import MCPServer

server=MCPServer("AI Dakwah Content Engine")
API=os.getenv("API_BASE_URL","http://api:8000").rstrip("/")
TOKEN=os.getenv("MCP_API_TOKEN","")
API_TIMEOUT_SECONDS=float(os.getenv("MCP_API_TIMEOUT_SECONDS","180"))
PUBLIC_BASE_URL=os.getenv("MCP_PUBLIC_BASE_URL","").rstrip("/")
log=logging.getLogger("dakwah.mcp")

def call(path: str, params: dict | None = None, method: str = "GET", body: dict | None = None):
    query={k:v for k,v in (params or {}).items() if v is not None and v != ""}
    url=API+path+("?"+urlencode(query) if query else "")
    headers={"Accept":"application/json"}
    data=None
    if body is not None:
        headers["Content-Type"]="application/json"
        data=json.dumps(body,ensure_ascii=False).encode("utf-8")
    if TOKEN: headers["X-Ingestion-Token"]=TOKEN
    request=Request(url,data=data,headers=headers,method=method)
    started=time.perf_counter()
    try:
        with urlopen(request,timeout=API_TIMEOUT_SECONDS) as response:
            result=json.loads(response.read().decode("utf-8"))
            if path == "/search":
                log.info("API search completed status=%d elapsed_seconds=%.2f", response.status, time.perf_counter()-started)
            return result
    except HTTPError as exc:
        if path == "/search":
            log.warning("API search returned status=%d elapsed_seconds=%.2f", exc.code, time.perf_counter()-started)
        return {"error":f"API returned {exc.code}","detail":exc.read().decode("utf-8","replace")[:1000]}
    except (URLError,TimeoutError) as exc:
        if path == "/search":
            log.warning("API search unavailable elapsed_seconds=%.2f error=%s", time.perf_counter()-started, str(exc)[:500])
        return {"error":"API unavailable","detail":str(exc)[:500]}

@server.tool()
def list_videos(status: str = "", limit: int = 50, offset: int = 0) -> dict:
    """List discovered videos and ingestion status with pagination."""
    return call("/videos",{"status":status or None,"limit":limit,"offset":offset})

@server.tool()
def get_video_metadata(video_id: str) -> dict:
    """Get metadata and latest job state for a discovered video id."""
    return call(f"/videos/{video_id}")

@server.tool()
def get_transcript(video_id: str, start_time: float = -1, end_time: float = -1, limit: int = 500, offset: int = 0) -> dict:
    """Get transcript segments, optionally bounded by source-video seconds."""
    params={"limit":limit,"offset":offset}
    if start_time >= 0: params["start_time"]=start_time
    if end_time >= 0: params["end_time"]=end_time
    return call(f"/videos/{video_id}/transcript",params)

@server.tool()
def search_sermons(query: str, limit: int = 10, video_id: str = "", language: str = "") -> dict:
    """Search sermon chunks by meaning and keywords. Similarity is not a truth probability."""
    params={"query":query,"limit":limit}
    if video_id: params["video_id"]=video_id
    if language: params["language"]=language
    return call("/search",params)

@server.tool()
def get_segment_context(chunk_id: str, before_chunks: int = 1, after_chunks: int = 1,
                        before_seconds: float = -1, after_seconds: float = -1) -> dict:
    """Read neighboring semantic chunks or a time window around one chunk."""
    params={"before_chunks":before_chunks,"after_chunks":after_chunks}
    if before_seconds >= 0: params["before_seconds"]=before_seconds
    if after_seconds >= 0: params["after_seconds"]=after_seconds
    return call(f"/chunks/{chunk_id}/context",params)

@server.tool()
def get_ingestion_status() -> dict:
    """Get current ingestion jobs, stages, errors, and recent operational events."""
    return call("/ingestion/status")


@server.tool()
def request_clip_render(proposal_id: str) -> dict:
    """Render a new MP4 from a human-approved proposal and return its job id."""
    return call("/clip-jobs", {"proposal_id": proposal_id}, method="POST")


@server.tool()
def request_vertical_clip_render(proposal_id: str) -> dict:
    """Render an approved proposal as a centered 9:16 social video at 1080x1920."""
    return call("/clip-jobs", {"proposal_id": proposal_id, "render_preset": "vertical_9_16"}, method="POST")


@server.tool()
def get_clip_job(job_id: str) -> dict:
    """Get render progress, errors, and the completed export path for a clip job."""
    result=call(f"/clip-jobs/{quote(job_id, safe='')}")
    if result.get("status") == "completed" and result.get("output_path") and PUBLIC_BASE_URL and TOKEN:
        expires=int(time.time())+900
        message=f"clip-job:{job_id}:{expires}".encode("utf-8")
        signature=hmac.new(TOKEN.encode("utf-8"),message,hashlib.sha256).hexdigest()
        query=urlencode({"expires":expires,"signature":signature})
        # Tailscale Serve strips the matched /clip-download/ prefix before proxying.
        result["download_url"]=f"{PUBLIC_BASE_URL}/clip-download/job/{quote(job_id,safe='')}?{query}"
        if result.get("subtitle_path"):
            result["subtitle_url"]=(
                f"{PUBLIC_BASE_URL}/clip-download/job/{quote(job_id,safe='')}/subtitle?{query}"
            )
        if result.get("subtitle_ar_path"):
            result["subtitle_ar_url"]=(
                f"{PUBLIC_BASE_URL}/clip-download/job/{quote(job_id,safe='')}/subtitle/ar?{query}"
            )
        result["download_url_expires_at"]=expires
    return result

@server.tool()
def save_content_proposal(proposal: dict) -> dict:
    """Validate source traceability and persist a proposed content candidate."""
    return call("/content-proposals",method="POST",body=proposal)

@server.tool()
def list_content_proposals(status: str = "", video_id: str = "", limit: int = 50, offset: int = 0) -> dict:
    """List persisted proposals with pagination and optional status/video filters."""
    return call("/content-proposals",{"status":status or None,"video_id":video_id or None,"limit":limit,"offset":offset})

@server.tool()
def get_content_proposal(proposal_id: str) -> dict:
    """Retrieve a persisted proposal by its identifier."""
    return call("/content-proposals/"+quote(proposal_id,safe=""))

@server.tool()
def update_proposal_review(proposal_id: str, decision: str, notes: str = "") -> dict:
    """Record an editor decision: approved, rejected, or needs_revision."""
    return call("/content-proposals/"+quote(proposal_id,safe="")+"/review",method="POST",body={"decision":decision,"notes":notes or None})

@server.tool()
def trigger_library_scan() -> dict:
    """Start a safe scan of the configured allowlisted read-only library."""
    return call("/library/scan",method="POST")

if __name__=="__main__":
    server.run(transport=os.getenv("MCP_TRANSPORT","streamable-http"),host="0.0.0.0",port=8001,json_response=True,stateless_http=True)
