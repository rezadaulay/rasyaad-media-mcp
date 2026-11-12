from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import redis
from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

from app.config import settings
from app.database import connect, initialize
from app.discovery import scan_library
from app import service

app = FastAPI(title="AI Dakwah Content Engine", version="0.2.0", description="Local sermon ingestion and timestamped semantic search API")


class ProposalReview(BaseModel):
    decision: str
    notes: str | None = Field(default=None,max_length=4000)


@app.on_event("startup")
def startup() -> None:
    initialize()


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status":"alive"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, Any]:
    try:
        QdrantClient(url=settings.qdrant_url,api_key=settings.qdrant_api_key or None,timeout=3).get_collections()
        if os.getenv("REDIS_URL"):
            redis.Redis.from_url(os.environ["REDIS_URL"],socket_timeout=3).ping()
        with connect() as db: db.execute("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503,detail="A required service is unavailable") from exc
    return {"status":"ready","phase":"2","worker":"single-job SQLite queue"}


@app.get("/health/status", tags=["health"])
def health_status() -> dict[str, Any]:
    usage=shutil.disk_usage(settings.data_dir)
    try:
        memory_current=int(open('/sys/fs/cgroup/memory.current',encoding='utf-8').read().strip())
        raw_max=open('/sys/fs/cgroup/memory.max',encoding='utf-8').read().strip()
        memory_max=int(raw_max) if raw_max != 'max' else None
    except (OSError,ValueError):
        memory_current=memory_max=None
    with connect() as db:
        videos=db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        pending=db.execute("SELECT COUNT(*) FROM ingestion_jobs WHERE status IN ('pending','retry_pending')").fetchone()[0]
        failed=db.execute("SELECT COUNT(*) FROM ingestion_jobs WHERE status='failed'").fetchone()[0]
    return {"status":"ready","video_count":videos,"pending_jobs":pending,"failed_jobs":failed,
            "disk_free_bytes":usage.free,"disk_total_bytes":usage.total,
            "container_memory_current_bytes":memory_current,"container_memory_limit_bytes":memory_max,
            "worker_status":service.ingestion_status()["workers"]}


@app.get("/videos")
def videos(status: str | None = None, limit: int = Query(50,ge=1,le=200),offset: int = Query(0,ge=0)):
    return service.list_videos(status,limit,offset)


@app.get("/videos/{video_id}")
def video_metadata(video_id: str):
    result=service.get_video_metadata(video_id)
    if not result: raise HTTPException(404,"Video not found")
    return result


@app.get("/videos/{video_id}/transcript")
def transcript(video_id: str,start_time: float | None = None,end_time: float | None = None,
                limit: int = Query(500,ge=1,le=2000),offset: int = Query(0,ge=0)):
    if start_time is not None and end_time is not None and start_time > end_time:
        raise HTTPException(422,"start_time must be less than or equal to end_time")
    return service.get_transcript(video_id,start_time,end_time,limit,offset)


@app.get("/search")
def search(query: str = Query(...,min_length=2,max_length=2000),limit: int = Query(10,ge=1,le=50),
           video_id: str | None = None,language: str | None = None):
    try:
        return service.search_sermons(query,limit,video_id,language)
    except RuntimeError as exc:
        raise HTTPException(503,str(exc)) from exc


@app.get("/chunks/{chunk_id}/context")
def context(chunk_id: str,before_chunks: int = Query(1,ge=0,le=50),after_chunks: int = Query(1,ge=0,le=50),
            before_seconds: float | None = Query(None,ge=0,le=3600),after_seconds: float | None = Query(None,ge=0,le=3600)):
    result=service.get_segment_context(chunk_id,before_chunks,after_chunks,before_seconds,after_seconds)
    if not result: raise HTTPException(404,"Chunk not found")
    return result


@app.get("/ingestion/status")
def status(): return service.ingestion_status()


@app.post("/clip-jobs", status_code=202)
def request_clip(proposal_id: str = Query(..., min_length=1), render_preset: str = Query("original"),
                 x_ingestion_token: str | None = Header(None)):
    require_ingestion_token(x_ingestion_token)
    try:
        return service.request_clip_render(proposal_id, render_preset)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.ClipRequestError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/clip-jobs/{job_id}")
def clip_job(job_id: str):
    result = service.get_clip_job(job_id)
    if not result:
        raise HTTPException(404, "Clip job not found")
    return result


def _get_download_checkpoint(job_id: str, expires: int, signature: str) -> dict[str, Any]:
    if not settings.api_token or expires < int(time.time()) or expires > int(time.time()) + 3600:
        raise HTTPException(403, "Download link expired or invalid")
    message = f"clip-job:{job_id}:{expires}".encode("utf-8")
    expected = hmac.new(settings.api_token.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(403, "Download link expired or invalid")
    with connect() as db:
        row = db.execute("SELECT status,checkpoint FROM clip_jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Clip job not found")
    if row["status"] != "completed":
        raise HTTPException(409, "Clip render is not complete")
    return json.loads(row["checkpoint"])


@app.get("/clip-download/{job_id}")
@app.get("/job/{job_id}")
def download_clip(job_id: str, expires: int, signature: str):
    checkpoint = _get_download_checkpoint(job_id, expires, signature)
    expected_path = (settings.data_dir / "clips" / f"{job_id}.mp4").resolve()
    try:
        output_path = Path(checkpoint["output_path"]).resolve()
        output_path.relative_to((settings.data_dir / "clips").resolve())
    except (KeyError, ValueError, OSError) as exc:
        raise HTTPException(404, "Clip output is unavailable") from exc
    if output_path != expected_path or not output_path.is_file():
        raise HTTPException(404, "Clip output is unavailable")
    return FileResponse(output_path, media_type="video/mp4", filename=f"{job_id}.mp4")


@app.get("/clip-download/{job_id}/subtitle")
@app.get("/job/{job_id}/subtitle")
def download_clip_subtitle(job_id: str, expires: int, signature: str):
    checkpoint = _get_download_checkpoint(job_id, expires, signature)
    expected_path = (settings.data_dir / "clips" / f"{job_id}.srt").resolve()
    try:
        subtitle_path = Path(checkpoint["subtitle_path"]).resolve()
        subtitle_path.relative_to((settings.data_dir / "clips").resolve())
    except (KeyError, ValueError, OSError) as exc:
        raise HTTPException(404, "Clip subtitles are unavailable") from exc
    if subtitle_path != expected_path or not subtitle_path.is_file():
        raise HTTPException(404, "Clip subtitles are unavailable")
    return FileResponse(subtitle_path, media_type="application/x-subrip", filename=f"{job_id}.srt")


@app.get("/clip-download/{job_id}/subtitle/ar")
@app.get("/job/{job_id}/subtitle/ar")
def download_clip_arabic_subtitle(job_id: str, expires: int, signature: str):
    checkpoint = _get_download_checkpoint(job_id, expires, signature)
    clips_dir = (settings.data_dir / "clips").resolve()
    expected_paths = {
        clips_dir / f"{job_id}.ar.srt",  # Keep previously rendered jobs downloadable.
        clips_dir / f"{job_id}.arabic.srt",
    }
    try:
        subtitle_path = Path(checkpoint["subtitle_ar_path"]).resolve()
        subtitle_path.relative_to((settings.data_dir / "clips").resolve())
    except (KeyError, ValueError, OSError) as exc:
        raise HTTPException(404, "Arabic clip subtitles are unavailable") from exc
    if subtitle_path not in expected_paths or not subtitle_path.is_file():
        raise HTTPException(404, "Arabic clip subtitles are unavailable")
    return FileResponse(subtitle_path, media_type="application/x-subrip", filename=subtitle_path.name)


@app.post("/library/scan")
def trigger_scan(x_ingestion_token: str | None = Header(None)):
    require_ingestion_token(x_ingestion_token)
    return scan_library()


def require_ingestion_token(x_ingestion_token: str | None) -> None:
    if not settings.api_token or x_ingestion_token != settings.api_token:
        raise HTTPException(403,"Invalid or missing ingestion token")


@app.post("/videos/{video_id}/reprocess", status_code=202)
def reprocess_video(video_id: str, x_ingestion_token: str | None = Header(None)):
    require_ingestion_token(x_ingestion_token)
    try:
        return service.request_reprocess(video_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except service.ReprocessConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/content-proposals")
def save_proposal(proposal: dict[str, Any] = Body(...), x_ingestion_token: str | None = Header(None)):
    require_ingestion_token(x_ingestion_token)
    import json
    if len(json.dumps(proposal,ensure_ascii=False).encode("utf-8")) > 256_000:
        raise HTTPException(413,"Proposal exceeds the 256 KB limit")
    try:
        return service.save_content_proposal(proposal)
    except service.ProposalValidationError as exc:
        raise HTTPException(422,str(exc)) from exc


@app.get("/content-proposals")
def list_proposals(status: str | None = None, video_id: str | None = None,
                   limit: int = Query(50,ge=1,le=200),offset: int = Query(0,ge=0)):
    if status and status not in {"draft","proposed","approved","rejected","needs_revision"}:
        raise HTTPException(422,"Invalid proposal status")
    return service.list_content_proposals(status,video_id,limit,offset)


@app.get("/content-proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    result=service.get_content_proposal(proposal_id)
    if result is None: raise HTTPException(404,"Proposal not found")
    return result


@app.post("/content-proposals/{proposal_id}/review")
def review_proposal(proposal_id: str, review: ProposalReview,
                    x_ingestion_token: str | None = Header(None)):
    require_ingestion_token(x_ingestion_token)
    try:
        result=service.update_proposal_review(proposal_id,review.decision,review.notes)
    except service.ProposalValidationError as exc:
        raise HTTPException(409,str(exc)) from exc
    if result is None: raise HTTPException(404,"Proposal not found")
    return result
