"""Single-job-at-a-time local ingestion pipeline."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from app.config import settings
from app.database import connect, event, finish_clip_job, finish_job, set_stage
from app.discovery import fingerprint, content_fingerprint, resolve_library_source
from app.segmentation import SEGMENTATION_VERSION, make_chunks

log = logging.getLogger("dakwah.pipeline")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def render_clip_job(job) -> None:
    """Render an approved proposal to a new MP4 without modifying its source."""
    import subprocess

    output_dir = settings.data_dir / "clips"
    temp_path = None
    try:
        checkpoint = json.loads(job["checkpoint"])
        source = resolve_library_source(checkpoint["source_path"])
        output_dir.mkdir(parents=True, exist_ok=True)
        start_time = float(checkpoint["start_time"])
        duration = float(checkpoint["end_time"]) - start_time
        render_preset = checkpoint.get("render_preset", "original")
        if render_preset not in {"original", "vertical_9_16"}:
            raise RuntimeError("Stored clip render preset is invalid")
        if start_time < 0 or duration <= 0 or duration > 600:
            raise RuntimeError("Stored proposal time range is invalid")
    except Exception as exc:
        log.exception("Clip job data is invalid job_id=%s", job["job_id"])
        finish_clip_job(job["job_id"], "failed", exc)
        return
    output_path = output_dir / f"{job['job_id']}.mp4"
    temp_path = output_dir / f"{job['job_id']}.rendering.mp4"
    try:
        if (fingerprint(source) != checkpoint["source_fingerprint"] or
                content_fingerprint(source) != checkpoint["source_content_fingerprint"]):
            raise RuntimeError("Source video changed after the render request")
        set_stage(job["job_id"], "rendering", 0.05)
        render_args = []
        if render_preset == "vertical_9_16":
            render_args = [
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920",
            ]
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
            "-ss", f"{start_time:.3f}", "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "0:a?", *render_args,
            "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(temp_path),
        ], check=True, timeout=max(300, int(duration * 10)))
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
            "-of", "json", str(temp_path),
        ], check=True, capture_output=True, text=True, timeout=30)
        media = json.loads(probe.stdout)
        video_stream = next((stream for stream in media.get("streams", []) if stream.get("codec_type") == "video"), None)
        if video_stream is None:
            raise RuntimeError("FFmpeg output does not contain a video stream")
        output_width = int(video_stream.get("width") or 0)
        output_height = int(video_stream.get("height") or 0)
        if render_preset == "vertical_9_16" and (output_width, output_height) != (1080, 1920):
            raise RuntimeError("Vertical clip output must be exactly 1080x1920")
        rendered_duration = float(media.get("format", {}).get("duration") or 0)
        if rendered_duration <= 0 or abs(rendered_duration - duration) > 1.0:
            raise RuntimeError("Rendered clip duration does not match the approved time range")
        if (fingerprint(source) != checkpoint["source_fingerprint"] or
                content_fingerprint(source) != checkpoint["source_content_fingerprint"]):
            raise RuntimeError("Source video changed during rendering")
        os.replace(temp_path, output_path)
        set_stage(job["job_id"], "completed", 1, {
            "output_path": str(output_path), "duration": rendered_duration,
            "output_width": output_width, "output_height": output_height,
        })
        finish_clip_job(job["job_id"], "completed")
        event("Approved clip rendered", video_id=job["video_id"], job_id=job["job_id"], stage="completed",
              details={"proposal_id": job["proposal_id"], "duration": rendered_duration,
                       "render_preset": render_preset, "width": output_width, "height": output_height})
    except Exception as exc:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        log.exception("Clip render failed job_id=%s", job["job_id"])
        finish_clip_job(job["job_id"], "failed", exc)
        event("Clip render failed", video_id=job["video_id"], job_id=job["job_id"], stage="failed",
              level="ERROR", details={"type": type(exc).__name__, "message": str(exc)[:1000]})


def transcribe(job, video) -> dict:
    from faster_whisper import WhisperModel

    source = resolve_library_source(video["path"])
    if fingerprint(source) != video["fingerprint"] or content_fingerprint(source) != video["content_fingerprint"]:
        raise RuntimeError("Source file changed after discovery; rescan required")
    temp_dir = settings.data_dir / "temporary"
    temp_dir.mkdir(parents=True, exist_ok=True)
    audio_path = temp_dir / f"{video['video_id']}.wav"
    set_stage(job["job_id"], "audio_extraction", 0.02)
    import subprocess
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)], check=True, timeout=max(3600, int((video["duration"] or 0) * 3)))
    try:
        set_stage(job["job_id"], "transcription", 0.05)
        model = WhisperModel(settings.asr_model, device="cpu", compute_type=settings.asr_compute_type,
                             cpu_threads=settings.asr_threads, num_workers=1,
                             download_root=str(settings.model_cache_dir))
        iterator, info = model.transcribe(str(audio_path), language=settings.asr_language or None,
                                          beam_size=5, vad_filter=True, word_timestamps=False,
                                          condition_on_previous_text=True)
        segments = []
        transcript_path = settings.data_dir / "transcripts" / f"{video['video_id']}.json"
        for i, item in enumerate(iterator):
            segments.append({"sequence_number": i, "start": float(item.start), "end": float(item.end),
                             "text": item.text.strip(), "confidence": None})
            if (i + 1) % 100 == 0:
                atomic_json(transcript_path.with_suffix(".partial.json"), {
                    "video_id": video["video_id"], "language": info.language, "asr_model": settings.asr_model,
                    "asr_config": {"device":"cpu","compute_type":settings.asr_compute_type,"beam_size":5,"vad_filter":True,"word_timestamps":False},
                    "partial": True, "segments": segments})
                audio_progress = min(1.0, float(item.end) / max(1.0, float(info.duration or video["duration"] or 1)))
                set_stage(job["job_id"], "transcription", 0.05 + audio_progress * 0.70,
                          {"segments_saved": len(segments), "audio_seconds_processed": float(item.end)})
        result = {"video_id": video["video_id"], "language": info.language, "asr_model": settings.asr_model,
                  "asr_config": {"device":"cpu","compute_type":settings.asr_compute_type,"cpu_threads":settings.asr_threads,"beam_size":5,"vad_filter":True,"word_timestamps":False},
                  "duration": float(info.duration or video["duration"] or 0), "segments": segments}
        atomic_json(transcript_path, result)
        transcript_path.with_suffix(".partial.json").unlink(missing_ok=True)
        return result
    finally:
        audio_path.unlink(missing_ok=True)


def persist_segments(video_id: str, transcript: dict) -> None:
    transcript_file = str(settings.data_dir / "transcripts" / f"{video_id}.json")
    with connect() as db:
        db.execute("DELETE FROM transcript_fts WHERE video_id=?", (video_id,))
        db.execute("DELETE FROM transcript_segments WHERE video_id=?", (video_id,))
        db.execute("INSERT INTO transcripts(video_id,language,asr_model,asr_config,file_path,segment_count,duration) VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET language=excluded.language,asr_model=excluded.asr_model,asr_config=excluded.asr_config,file_path=excluded.file_path,segment_count=excluded.segment_count,duration=excluded.duration,created_at=CURRENT_TIMESTAMP",
                   (video_id, transcript["language"], transcript["asr_model"], json.dumps(transcript["asr_config"]), transcript_file, len(transcript["segments"]), transcript["duration"]))
        for seg in transcript["segments"]:
            sid = f"{video_id}:{seg['sequence_number']}"
            db.execute("INSERT INTO transcript_segments(segment_id,video_id,sequence_number,start_time,end_time,text,language,confidence) VALUES(?,?,?,?,?,?,?,?)",
                       (sid, video_id, seg["sequence_number"], seg["start"], seg["end"], seg["text"], transcript["language"], seg["confidence"]))
            db.execute("INSERT INTO transcript_fts(segment_id,video_id,text) VALUES(?,?,?)", (sid, video_id, seg["text"]))


def embed_and_index(video, transcript: dict) -> int:
    from app.embedding import embed_documents, release_model, get_qdrant, collection_name, ensure_collection

    chunks = make_chunks(transcript["segments"], video["video_id"], transcript["language"])
    set_stage(video["job_id"], "segmentation", 0.78)
    with connect() as db:
        db.execute("DELETE FROM chunks_fts WHERE video_id=?", (video["video_id"],))
        db.execute("DELETE FROM semantic_chunks WHERE video_id=?", (video["video_id"],))
        for chunk in chunks:
            db.execute("INSERT INTO semantic_chunks(chunk_id,video_id,sequence_number,start_time,end_time,text,previous_chunk_id,next_chunk_id,language,segmentation_version,source_transcript_reference) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       tuple(chunk[k] for k in ("chunk_id","video_id","sequence_number","start_time","end_time","text","previous_chunk_id","next_chunk_id","language","segmentation_version","source_transcript_reference")))
            db.execute("INSERT INTO chunks_fts(chunk_id,video_id,text) VALUES(?,?,?)", (chunk["chunk_id"], video["video_id"], chunk["text"]))
    set_stage(video["job_id"], "embedding", 0.82)
    try:
        vectors = embed_documents([c["text"] for c in chunks]) if chunks else []
    finally:
        release_model()
    client = get_qdrant()
    collection = collection_name()
    ensure_collection(client, collection)
    from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
    client.delete(collection, points_selector=Filter(must=[FieldCondition(key="video_id", match=MatchValue(value=video["video_id"]))]))
    for start in range(0, len(chunks), settings.embedding_batch_size):
        points = []
        for chunk, vector in zip(chunks[start:start + settings.embedding_batch_size], vectors[start:start + settings.embedding_batch_size]):
            points.append(PointStruct(id=chunk["chunk_id"], vector=vector, payload={
                **chunk, "source_reference": Path(video["path"]).relative_to(settings.library_root).as_posix(),
                "embedding_model_version": settings.embedding_model, "score_note": "cosine similarity; not a probability"}))
        if points:
            client.upsert(collection, points=points, wait=True)
    with connect() as db:
        db.execute("INSERT INTO embedding_indexes(index_id,model_version,dimension,collection_name,segmentation_version,status) VALUES(?,?,?,?,?,'ready') ON CONFLICT(model_version,segmentation_version) DO UPDATE SET status='ready',updated_at=CURRENT_TIMESTAMP",
                   (f"{settings.embedding_model}:{SEGMENTATION_VERSION}", settings.embedding_model, settings.embedding_dimension, collection, SEGMENTATION_VERSION))
    set_stage(video["job_id"], "indexing", 0.98)
    return len(chunks)


def process_job(job) -> None:
    started = time.perf_counter()
    with connect() as db:
        video = db.execute("SELECT * FROM videos WHERE video_id=?", (job["video_id"],)).fetchone()
    if not video:
        finish_job(job["job_id"], job["video_id"], "failed", RuntimeError("Video metadata disappeared")); return
    try:
        if not video["has_audio"]:
            finish_job(job["job_id"], video["video_id"], "skipped"); return
        # A changed/retried video must not keep serving vectors from an older transcript.
        from app.embedding import remove_video_points
        remove_video_points(video["video_id"])
        transcript_path = settings.data_dir / "transcripts" / f"{video['video_id']}.json"
        if not json.loads(job["checkpoint"]).get("reprocess") and transcript_path.exists():
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        else:
            transcript = transcribe(job, video)
        set_stage(job["job_id"], "transcript_persist", 0.76)
        persist_segments(video["video_id"], transcript)
        # video row passed to indexer needs the current job id for progress updates.
        video_dict = dict(video); video_dict["job_id"] = job["job_id"]
        chunk_count = embed_and_index(video_dict, transcript)
        finish_job(job["job_id"], video["video_id"], "completed")
        event("Ingestion completed", video_id=video["video_id"], job_id=job["job_id"], stage="completed",
              details={"segment_count":len(transcript["segments"]),"chunk_count":chunk_count,"elapsed_seconds":round(time.perf_counter()-started,2),"asr_model":settings.asr_model,"embedding_model":settings.embedding_model})
        log.info("Ingestion complete video_id=%s segments=%d chunks=%d", video["video_id"], len(transcript["segments"]), chunk_count)
    except Exception as exc:
        log.exception("Ingestion failed video_id=%s job_id=%s", video["video_id"], job["job_id"])
        finish_job(job["job_id"], video["video_id"], "failed", exc)
        event("Ingestion failed", video_id=video["video_id"], job_id=job["job_id"], stage=job["stage"], level="ERROR", details={"type":type(exc).__name__,"message":str(exc)[:1000]})
