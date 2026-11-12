"""Application service layer shared by HTTP and MCP adapters."""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.database import connect
from app.discovery import resolve_library_source
from app.embedding import collection_name, embed_query, ensure_collection, get_qdrant

log = logging.getLogger("dakwah.search")
PROPOSAL_SCHEMA = Path(__file__).resolve().parent.parent / ".claude/skills/dakwah-content-discovery/schemas/content-proposal.schema.json"


def list_videos(status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(limit, 200)); offset = max(0, offset)
    with connect() as db:
        where, args = ("WHERE status=?", [status]) if status else ("", [])
        total = db.execute(f"SELECT COUNT(*) FROM videos {where}", args).fetchone()[0]
        rows = db.execute(f"SELECT video_id,file_name,size_bytes,duration,width,height,video_codec,has_audio,status,updated_at FROM videos {where} ORDER BY file_name LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    return {"items":[dict(r) for r in rows],"total":total,"limit":limit,"offset":offset}


def get_video_metadata(video_id: str) -> dict[str, Any] | None:
    with connect() as db:
        db.execute("BEGIN")
        row = db.execute("SELECT video_id,file_name,size_bytes,duration,width,height,video_codec,audio_codec,has_audio,container,status,created_at,updated_at FROM videos WHERE video_id=?", (video_id,)).fetchone()
        if not row: return None
        result = dict(row)
        job = db.execute("SELECT job_id,status,stage,retry_count,progress,error_type,error_message,updated_at FROM ingestion_jobs WHERE video_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (video_id,)).fetchone()
        result["job"] = dict(job) if job else None
        return result


class ReprocessConflict(ValueError):
    pass


class ClipRequestError(ValueError):
    pass


def request_clip_render(proposal_id: str, render_preset: str = "original") -> dict[str, Any]:
    if render_preset not in {"original", "vertical_9_16"}:
        raise ClipRequestError("Unsupported clip render preset")
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        proposal_row = db.execute(
            "SELECT p.proposal_json,p.status,p.video_id,v.path,v.status AS video_status,v.duration,v.fingerprint,v.content_fingerprint "
            "FROM content_proposals p JOIN videos v ON v.video_id=p.video_id WHERE p.proposal_id=?",
            (proposal_id,),
        ).fetchone()
        if proposal_row is None:
            raise FileNotFoundError("Proposal not found")
        if proposal_row["status"] != "approved":
            raise ClipRequestError("Only an approved proposal can be rendered")
        if proposal_row["video_status"] != "completed":
            raise ClipRequestError("Source video is not completed")
        try:
            source = resolve_library_source(proposal_row["path"])
        except (ValueError, FileNotFoundError) as exc:
            raise ClipRequestError(str(exc)) from exc
        from app.discovery import content_fingerprint, fingerprint
        if (fingerprint(source) != proposal_row["fingerprint"] or
                content_fingerprint(source) != proposal_row["content_fingerprint"]):
            raise ClipRequestError("Source video changed since indexing; rescan and create a new proposal")

        proposal = json.loads(proposal_row["proposal_json"])
        start_time = float(proposal["start_time"])
        end_time = float(proposal["end_time"])
        duration = end_time - start_time
        if start_time < 0 or duration <= 0 or duration > 600:
            raise ClipRequestError("Proposal time range is invalid or exceeds the 600-second render limit")
        if proposal_row["duration"] is not None and end_time > float(proposal_row["duration"]) + 1:
            raise ClipRequestError("Proposal end time exceeds the source video duration")
        active = db.execute(
            "SELECT job_id,status FROM clip_jobs WHERE proposal_id=? "
            "AND COALESCE(json_extract(checkpoint,'$.render_preset'),'original')=? "
            "AND status IN ('pending','processing','retry_pending') ORDER BY created_at DESC LIMIT 1",
            (proposal_id, render_preset),
        ).fetchone()
        if active:
            return {"job_id": active["job_id"], "proposal_id": proposal_id,
                    "render_preset": render_preset, "status": active["status"]}

        job_id = str(uuid.uuid4())
        output_path = settings.data_dir / "clips" / f"{job_id}.mp4"
        checkpoint = {
            "source_path": str(source),
            "source_fingerprint": _source_fingerprint(proposal_row["path"]),
            "source_content_fingerprint": proposal_row["content_fingerprint"],
            "start_time": start_time,
            "end_time": end_time,
            "render_preset": render_preset,
            "output_path": str(output_path),
        }
        db.execute(
            "INSERT INTO clip_jobs(job_id,proposal_id,video_id,status,checkpoint) VALUES(?,?,?,'pending',?)",
            (job_id, proposal_id, proposal_row["video_id"], json.dumps(checkpoint)),
        )
    return {"job_id": job_id, "proposal_id": proposal_id,
            "render_preset": render_preset, "status": "pending"}


def _source_fingerprint(path: str) -> str:
    from app.discovery import fingerprint, resolve_library_source
    return fingerprint(resolve_library_source(path))


def get_clip_job(job_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM clip_jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    checkpoint = json.loads(result.pop("checkpoint"))
    result["render_preset"] = checkpoint.get("render_preset", "original")
    result["outputs_expired"] = bool(checkpoint.get("outputs_expired", False))
    if checkpoint.get("arabic_detection"):
        result["arabic_detection"] = checkpoint["arabic_detection"]
    result["output_path"] = checkpoint.get("output_path") if row["status"] == "completed" else None
    if row["status"] == "completed":
        result["output_width"] = checkpoint.get("output_width")
        result["output_height"] = checkpoint.get("output_height")
        if checkpoint.get("subtitle_path"):
            result["subtitle_path"] = checkpoint["subtitle_path"]
            result["subtitle_cue_count"] = int(checkpoint.get("subtitle_cue_count", 0))
        if checkpoint.get("subtitle_ar_path"):
            result["subtitle_ar_path"] = checkpoint["subtitle_ar_path"]
            result["subtitle_ar_cue_count"] = int(checkpoint.get("subtitle_ar_cue_count", 0))
            result["arabic_corrections"] = checkpoint.get("arabic_corrections", [])
    return result


def request_reprocess(video_id: str) -> dict[str, str]:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        video = db.execute("SELECT path, has_audio FROM videos WHERE video_id=?", (video_id,)).fetchone()
        if video is None:
            raise FileNotFoundError("Video not found")
        try:
            resolve_library_source(video["path"])
        except ValueError as exc:
            raise ReprocessConflict(str(exc)) from exc

        active = db.execute(
            "SELECT job_id, status FROM ingestion_jobs WHERE video_id=? "
            "AND status IN ('pending','processing','retry_pending') LIMIT 1", (video_id,)
        ).fetchone()
        if active:
            raise ReprocessConflict(f"Video already has active job {active['job_id']} ({active['status']})")
        if not video["has_audio"]:
            raise ReprocessConflict("Video needs scanned metadata with an audio stream")

        job_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO ingestion_jobs(job_id,video_id,status,checkpoint) VALUES(?,?,'pending',?)",
            (job_id, video_id, json.dumps({"reprocess": True})),
        )
        db.execute("UPDATE videos SET status='pending',updated_at=CURRENT_TIMESTAMP WHERE video_id=?", (video_id,))
    return {"video_id": video_id, "job_id": job_id, "status": "pending"}


def get_transcript(video_id: str, start_time: float | None = None, end_time: float | None = None,
                   limit: int = 500, offset: int = 0) -> dict[str, Any]:
    limit=max(1,min(limit,2000)); offset=max(0,offset)
    clauses=["video_id=?"]; args: list[Any]=[video_id]
    if start_time is not None: clauses.append("end_time>=?"); args.append(start_time)
    if end_time is not None: clauses.append("start_time<=?"); args.append(end_time)
    where=" AND ".join(clauses)
    with connect() as db:
        db.execute("BEGIN")
        if not db.execute("SELECT 1 FROM videos WHERE video_id=? AND status='completed'", (video_id,)).fetchone():
            return {"video_id":video_id,"transcript":None,"segments":[],"total":0,"limit":limit,"offset":offset}
        meta=db.execute("SELECT language,asr_model,segment_count,duration FROM transcripts WHERE video_id=?",(video_id,)).fetchone()
        rows=db.execute(f"SELECT sequence_number,start_time,end_time,text,confidence FROM transcript_segments WHERE {where} ORDER BY sequence_number LIMIT ? OFFSET ?",[*args,limit,offset]).fetchall()
        total=db.execute(f"SELECT COUNT(*) FROM transcript_segments WHERE {where}",args).fetchone()[0]
    return {"video_id":video_id,"transcript":dict(meta) if meta else None,"segments":[dict(r) for r in rows],"total":total,"limit":limit,"offset":offset}


def search_sermons(query: str, limit: int = 10, video_id: str | None = None, language: str | None = None,
                   filters: dict[str, Any] | None = None) -> dict[str, Any]:
    started=time.perf_counter()
    limit=max(1,min(limit,50)); filters=filters or {}
    with connect() as db:
        indexed=db.execute("SELECT 1 FROM embedding_indexes WHERE status='ready' LIMIT 1").fetchone()
    if not indexed:
        return {"query":query,"items":[],"score_explanation":"Cosine similarity scores are not probabilities of correctness.","index_status":"empty"}
    with connect() as db:
        busy=db.execute("SELECT stage FROM ingestion_jobs WHERE status='processing' AND stage IN ('audio_extraction','transcription','embedding') LIMIT 1").fetchone()
    if busy:
        raise RuntimeError("CPU model is busy with ingestion; retry the search when the active stage completes")
    client=get_qdrant(); collection=collection_name(); ensure_collection(client,collection)
    embedding_started=time.perf_counter()
    vector=embed_query(query)
    embedding_seconds=time.perf_counter()-embedding_started
    must=[]
    from qdrant_client.models import Filter, FieldCondition, MatchValue, Range
    for key,val in (("video_id",video_id),("language",language)):
        if val: must.append(FieldCondition(key=key,match=MatchValue(value=val)))
    if filters.get("start_time_gte") is not None: must.append(FieldCondition(key="end_time",range=Range(gte=float(filters["start_time_gte"]))))
    if filters.get("end_time_lte") is not None: must.append(FieldCondition(key="start_time",range=Range(lte=float(filters["end_time_lte"]))))
    qfilter=Filter(must=must) if must else None
    vector_started=time.perf_counter()
    response=client.query_points(collection_name=collection,query=vector,query_filter=qfilter,limit=limit*2,with_payload=True)
    vector_seconds=time.perf_counter()-vector_started
    semantic=[]
    for rank,point in enumerate(response.points,1):
        p=point.payload or {}
        semantic.append({"video_id":p.get("video_id"),"chunk_id":p.get("chunk_id"),"text":p.get("text"),"start_time":p.get("start_time"),"end_time":p.get("end_time"),"language":p.get("language"),"source_reference":p.get("source_reference"),"score":float(point.score),"score_type":"cosine_similarity"})
    # A source that changed or disappeared during reprocessing must not surface stale
    # vectors even if Qdrant cleanup is waiting on a retry.
    semantic_ids={item["video_id"] for item in semantic if item["video_id"]}
    with connect() as db:
        active_ids={r[0] for r in db.execute("SELECT video_id FROM videos WHERE status='completed' AND video_id IN (%s)" % ",".join("?" for _ in semantic_ids),tuple(semantic_ids)).fetchall()} if semantic_ids else set()
    semantic=[item for item in semantic if item["video_id"] in active_ids]
    lexical=[]
    try:
        with connect() as db:
            fts_query=' OR '.join('"'+token.replace('"','')+'"' for token in query.split() if token)
            if fts_query:
                sql="SELECT c.chunk_id,c.video_id,c.text,c.start_time,c.end_time,c.language,v.file_name FROM chunks_fts f JOIN semantic_chunks c ON c.chunk_id=f.chunk_id JOIN videos v ON v.video_id=c.video_id WHERE chunks_fts MATCH ? AND v.status='completed'"
                args=[fts_query]
                if video_id: sql+=" AND c.video_id=?"; args.append(video_id)
                if language: sql+=" AND c.language=?"; args.append(language)
                if filters.get("start_time_gte") is not None: sql+=" AND c.end_time>=?"; args.append(float(filters["start_time_gte"]))
                if filters.get("end_time_lte") is not None: sql+=" AND c.start_time<=?"; args.append(float(filters["end_time_lte"]))
                lexical=[dict(r) for r in db.execute(sql+" ORDER BY rank LIMIT ?",[*args,limit*2]).fetchall()]
    except Exception:
        lexical=[]
    # Reciprocal rank fusion prevents dissimilar cosine/FTS scales from being mixed naively.
    merged={}
    for rank,item in enumerate(semantic,1):
        key=item["chunk_id"]; merged[key]=dict(item); merged[key]["rrf"]=1/(60+rank)
    for rank,item in enumerate(lexical,1):
        key=item["chunk_id"]
        if key not in merged:
            merged[key]={"video_id":item["video_id"],"chunk_id":key,"text":item["text"],"start_time":item["start_time"],"end_time":item["end_time"],"language":item["language"],"source_reference":item["file_name"],"score":None,"score_type":"keyword_only","rrf":0}
        merged[key]["rrf"]+=1/(60+rank)
        merged[key]["matched_by"]="hybrid"
    items=sorted(merged.values(),key=lambda x:x["rrf"],reverse=True)[:limit]
    for item in items: item.pop("rrf",None)
    log.info("Search completed embedding_seconds=%.2f vector_seconds=%.2f total_seconds=%.2f results=%d",
             embedding_seconds, vector_seconds, time.perf_counter()-started, len(items))
    return {"query":query,"items":items,"score_explanation":"Cosine similarity is a ranking signal, not a probability of correctness. Keyword and semantic ranks are fused when keyword matches exist.","index_status":"ready"}


def get_segment_context(chunk_id: str, before_chunks: int = 1, after_chunks: int = 1,
                        before_seconds: float | None = None, after_seconds: float | None = None) -> dict[str, Any] | None:
    with connect() as db:
        db.execute("BEGIN")
        target=db.execute("SELECT c.* FROM semantic_chunks c JOIN videos v ON v.video_id=c.video_id WHERE c.chunk_id=? AND v.status='completed'",(chunk_id,)).fetchone()
        if not target:return None
        if before_seconds is not None or after_seconds is not None:
            start=float(target["start_time"])-(before_seconds or 0); end=float(target["end_time"])+(after_seconds or 0)
            rows=db.execute("SELECT chunk_id,video_id,sequence_number,start_time,end_time,text,language FROM semantic_chunks WHERE video_id=? AND end_time>=? AND start_time<=? ORDER BY sequence_number",(target["video_id"],start,end)).fetchall()
        else:
            lo=max(0,int(target["sequence_number"])-max(0,min(before_chunks,50)))
            hi=int(target["sequence_number"])+max(0,min(after_chunks,50))
            rows=db.execute("SELECT chunk_id,video_id,sequence_number,start_time,end_time,text,language FROM semantic_chunks WHERE video_id=? AND sequence_number BETWEEN ? AND ? ORDER BY sequence_number",(target["video_id"],lo,hi)).fetchall()
    return {"target_chunk_id":chunk_id,"video_id":target["video_id"],"chunks":[dict(r) for r in rows]}


def ingestion_status() -> dict[str, Any]:
    with connect() as db:
        counts={r["status"]:r["count"] for r in db.execute("SELECT status,COUNT(*) AS count FROM ingestion_jobs GROUP BY status")}
        active=db.execute("SELECT j.job_id,j.video_id,v.file_name,j.status,j.stage,j.progress,j.retry_count,j.error_type,j.error_message FROM ingestion_jobs j JOIN videos v ON v.video_id=j.video_id WHERE j.status='processing' ORDER BY j.started_at DESC LIMIT 1").fetchone()
        recent=db.execute("SELECT event_id,video_id,job_id,stage,level,message,created_at FROM processing_events ORDER BY event_id DESC LIMIT 20").fetchall()
        workers=db.execute("SELECT worker_id,process_id,started_at,heartbeat_at,stage FROM worker_status ORDER BY heartbeat_at DESC").fetchall()
    import time
    worker_list=[]
    for row in workers:
        worker=dict(row); worker["alive"]=worker["stage"] != "stopped" and time.time()-worker["heartbeat_at"] < 30
        worker_list.append(worker)
    return {"jobs_by_status":counts,"active_job":dict(active) if active else None,"workers":worker_list,"recent_events":[dict(r) for r in recent]}


class ProposalValidationError(ValueError):
    pass


def save_content_proposal(proposal: dict[str, Any]) -> dict[str, Any]:
    """Validate source traceability, then durably store an unreviewed proposal."""
    try:
        import jsonschema
        schema=json.loads(PROPOSAL_SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker()).validate(proposal)
    except ImportError as exc:
        raise RuntimeError("JSON Schema validation dependency is unavailable") from exc
    except Exception as exc:
        if type(exc).__module__.startswith("jsonschema"):
            raise ProposalValidationError(f"Proposal does not match the content proposal schema: {exc.message}") from exc
        raise

    video_id=proposal["video_id"]
    if proposal["status"] not in {"draft","proposed"}:
        raise ProposalValidationError("New proposals must be submitted as draft or proposed; editor decisions use the review action")
    chunk_ids=proposal["source_chunk_ids"]
    with connect() as db:
        video=db.execute("SELECT file_name,duration,status FROM videos WHERE video_id=?",(video_id,)).fetchone()
        if video is None or video["status"] != "completed":
            raise ProposalValidationError("Source video does not exist or is not completed")
        if proposal["source_video"] != video["file_name"]:
            raise ProposalValidationError("source_video does not match the registered video metadata")
        marks=",".join("?" for _ in chunk_ids)
        chunks=db.execute(f"SELECT chunk_id,text,start_time,end_time FROM semantic_chunks WHERE video_id=? AND chunk_id IN ({marks}) ORDER BY sequence_number",[video_id,*chunk_ids]).fetchall()
        if {c["chunk_id"] for c in chunks} != set(chunk_ids):
            raise ProposalValidationError("One or more source_chunk_ids do not belong to this video")
        if not any(proposal["start_time"] <= c["end_time"] and proposal["end_time"] >= c["start_time"] for c in chunks):
            raise ProposalValidationError("Proposal time span does not overlap its source chunks")
        source_text=" ".join(c["text"] for c in chunks)
        if proposal["transcript_excerpt"] not in source_text:
            raise ProposalValidationError("transcript_excerpt is not present verbatim in the referenced source chunks")
        if video["duration"] is not None and proposal["end_time"] > video["duration"] + 1:
            raise ProposalValidationError("Proposal end_time exceeds the source video duration")
        existing=db.execute("SELECT status FROM content_proposals WHERE proposal_id=?",(proposal["proposal_id"],)).fetchone()
        if existing:
            raise ProposalValidationError("proposal_id already exists; use a new ID for a revision so prior review feedback is preserved")
        clean=dict(proposal)
        clean["status"]="proposed"
        db.execute("""INSERT INTO content_proposals(proposal_id,video_id,status,proposal_json,created_at,updated_at)
            VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)""",
            (clean["proposal_id"],video_id,clean["status"],json.dumps(clean,ensure_ascii=False),clean["created_at"]))
    return {"proposal_id":clean["proposal_id"],"video_id":video_id,"status":clean["status"]}


def list_content_proposals(status: str | None = None, video_id: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit=max(1,min(limit,200)); offset=max(0,offset)
    clauses=[]; args=[]
    if status: clauses.append("status=?"); args.append(status)
    if video_id: clauses.append("video_id=?"); args.append(video_id)
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    with connect() as db:
        total=db.execute("SELECT COUNT(*) FROM content_proposals"+where,args).fetchone()[0]
        rows=db.execute("SELECT proposal_id,video_id,status,created_at,updated_at,reviewed_at,review_decision,review_notes FROM content_proposals"+where+" ORDER BY created_at DESC LIMIT ? OFFSET ?",[*args,limit,offset]).fetchall()
    return {"items":[dict(r) for r in rows],"total":total,"limit":limit,"offset":offset}


def get_content_proposal(proposal_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row=db.execute("SELECT proposal_json FROM content_proposals WHERE proposal_id=?",(proposal_id,)).fetchone()
    return json.loads(row["proposal_json"]) if row else None


def update_proposal_review(proposal_id: str, decision: str, notes: str | None = None) -> dict[str, Any] | None:
    if decision not in {"approved","rejected","needs_revision"}:
        raise ProposalValidationError("Decision must be approved, rejected, or needs_revision")
    reviewed_at=datetime.now(timezone.utc).isoformat()
    with connect() as db:
        row=db.execute("SELECT proposal_json,status FROM content_proposals WHERE proposal_id=?",(proposal_id,)).fetchone()
        if not row: return None
        proposal=json.loads(row["proposal_json"])
        if row["status"] in {"approved","rejected"}:
            raise ProposalValidationError("Proposal already has a final review decision")
        proposal["status"]=decision
        proposal["reviewed_at"]=reviewed_at
        proposal["review_notes"]=notes
        proposal["review_decision"]=decision
        db.execute("UPDATE content_proposals SET status=?,proposal_json=?,reviewed_at=?,review_decision=?,review_notes=?,updated_at=CURRENT_TIMESTAMP WHERE proposal_id=?",
                   (decision,json.dumps(proposal,ensure_ascii=False),reviewed_at,decision,notes,proposal_id))
    return proposal
