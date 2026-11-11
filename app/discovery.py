"""Read-only library discovery and FFprobe metadata extraction."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from app.config import settings
from app.database import connect, event

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpeg", ".mpg", ".wmv", ".ts"}


def resolve_library_source(path: str) -> Path:
    try:
        source = Path(path).resolve()
        source.relative_to(settings.library_root.resolve())
    except (ValueError, RuntimeError, OSError) as exc:
        raise ValueError("Source video could not be resolved under the configured library root") from exc
    if not source.is_file():
        raise FileNotFoundError("Source video is missing from the configured library")
    return source


def is_partial_path(path: Path) -> bool:
    return any(".partial" in part.casefold() for part in path.parts)


def video_id_for(path: Path) -> str:
    """Stable id based on canonical library-relative path; content changes update the record."""
    rel = path.resolve().relative_to(settings.library_root.resolve()).as_posix().casefold()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "dakwah-video:" + rel))


def fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve().as_posix().casefold()}|{stat.st_size}|{stat.st_mtime_ns}"
    return hashlib.sha256(payload.encode()).hexdigest()


def content_fingerprint(path: Path) -> str:
    """Fast duplicate candidate fingerprint; full SHA-256 verifies candidates."""
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as stream:
        for offset in sorted({0, max(0, size // 2 - 512 * 1024), max(0, size - 1024 * 1024)}):
            stream.seek(offset); h.update(stream.read(1024 * 1024))
    return h.hexdigest()


def probe(path: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, timeout=120)
    data = json.loads(result.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    return {"duration": float(fmt.get("duration") or (video or {}).get("duration") or 0),
            "width": (video or {}).get("width"), "height": (video or {}).get("height"),
            "video_codec": (video or {}).get("codec_name"), "audio_codec": (audio or {}).get("codec_name"),
            "has_audio": int(audio is not None), "container": fmt.get("format_name")}


def scan_library() -> dict[str, int]:
    root = settings.library_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError("Configured video library is not mounted")
    counts = {"seen": 0, "queued": 0, "unchanged": 0, "unstable": 0, "failed": 0, "skipped": 0}
    seen_paths: set[str] = set()
    for path in root.rglob("*"):
        if is_partial_path(path) or not path.is_file() or path.suffix.casefold() not in VIDEO_EXTENSIONS:
            continue
        counts["seen"] += 1
        seen_paths.add(str(path))
        try:
            # Require two observations at least STABLE_FILE_SECONDS apart before processing.
            content_fp = content_fingerprint(path)
            current_fp = fingerprint(path)
            vid = video_id_for(path)
            stat = path.stat()
            with connect() as db:
                observation = db.execute("SELECT * FROM file_observations WHERE path=?", (str(path),)).fetchone()
                stable = bool(observation and observation["fingerprint"] == current_fp and
                              time.time() - observation["first_seen"] >= settings.stable_file_seconds)
                if observation and observation["fingerprint"] == current_fp:
                    db.execute("UPDATE file_observations SET last_seen=? WHERE path=?", (time.time(), str(path)))
                else:
                    db.execute("INSERT INTO file_observations(path,fingerprint,first_seen,last_seen) VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint,first_seen=excluded.first_seen,last_seen=excluded.last_seen",
                               (str(path), current_fp, time.time(), time.time()))
                existing = db.execute("SELECT * FROM videos WHERE video_id=?", (vid,)).fetchone()
                if existing and existing["fingerprint"] == current_fp and existing["content_fingerprint"] == content_fp:
                    active = db.execute("SELECT 1 FROM ingestion_jobs WHERE video_id=? AND status IN ('pending','processing','retry_pending','completed') LIMIT 1", (vid,)).fetchone()
                    if active:
                        counts["unchanged"] += 1
                        continue
                    # A previously failed file is not silently requeued on every scan.
                    if existing["status"] == "failed":
                        counts["unchanged"] += 1
                        continue
                    if not stable:
                        counts["unstable"] += 1
                        continue
                    meta = probe(path)
                    duplicate_of = None
                    if meta["has_audio"]:
                        candidate = db.execute("SELECT video_id,path,sha256 FROM videos WHERE video_id<>? AND size_bytes=? AND content_fingerprint=? AND status IN ('pending','processing','completed') LIMIT 1",
                                               (vid, stat.st_size, content_fp)).fetchone()
                        if candidate:
                            candidate_hash = candidate["sha256"] or sha256_file(Path(candidate["path"]))
                            if not candidate["sha256"]:
                                db.execute("UPDATE videos SET sha256=? WHERE video_id=?", (candidate_hash, candidate["video_id"]))
                            if sha256_file(path) == candidate_hash:
                                duplicate_of = candidate["video_id"]
                    if duplicate_of:
                        db.execute("UPDATE videos SET status='skipped',duplicate_of=?,duration=?,width=?,height=?,video_codec=?,audio_codec=?,has_audio=?,container=?,updated_at=CURRENT_TIMESTAMP WHERE video_id=?",
                                   (duplicate_of, *[meta[k] for k in ("duration","width","height","video_codec","audio_codec","has_audio","container")], vid))
                        db.execute("INSERT INTO ingestion_jobs(job_id,video_id,status,stage,error_type,error_message,finished_at) VALUES(?,?,'skipped','discovery','DuplicateVideo','Duplicate content',?)",
                                   (str(uuid.uuid4()), vid, time.time()))
                        counts["skipped"] += 1
                        continue
                    db.execute("INSERT INTO ingestion_jobs(job_id,video_id,status,stage) VALUES(?,?,'pending','queued')",
                               (str(uuid.uuid4()), vid))
                    db.execute("UPDATE videos SET status='pending',duration=?,width=?,height=?,video_codec=?,audio_codec=?,has_audio=?,container=?,updated_at=CURRENT_TIMESTAMP WHERE video_id=?",
                               (*[meta[k] for k in ("duration","width","height","video_codec","audio_codec","has_audio","container")], vid))
                    counts["queued"] += 1
                    continue
                if existing:
                    reprocess = db.execute(
                        "SELECT 1 FROM ingestion_jobs WHERE video_id=? "
                        "AND status IN ('pending','processing','retry_pending') "
                        "AND json_extract(checkpoint, '$.reprocess')=1 LIMIT 1", (vid,)
                    ).fetchone()
                    if reprocess:
                        counts["unchanged"] += 1
                        continue
                    db.execute("UPDATE videos SET path=?,file_name=?,size_bytes=?,mtime=?,fingerprint=?,content_fingerprint=?,duplicate_of=NULL,sha256=NULL,status='discovered',updated_at=CURRENT_TIMESTAMP WHERE video_id=?",
                               (str(path), path.name, stat.st_size, stat.st_mtime, current_fp, content_fp, vid))
                    db.execute("DELETE FROM ingestion_jobs WHERE video_id=? AND status IN ('pending','retry_pending')", (vid,))
                    db.execute("DELETE FROM transcripts WHERE video_id=?", (vid,))
                    db.execute("DELETE FROM semantic_chunks WHERE video_id=?", (vid,))
                else:
                    db.execute("INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,content_fingerprint,status) VALUES(?,?,?,?,?,?,?,'discovered')",
                               (vid, str(path), path.name, stat.st_size, stat.st_mtime, current_fp, content_fp))
            # Existing mtime is only accepted once stable interval has elapsed.
            if not stable:
                counts["unstable"] += 1
                continue
            meta = probe(path)
            # A matching sampled fingerprint is only a candidate. Confirm with full SHA-256
            # before suppressing a second library copy.
            with connect() as db:
                candidate = db.execute("SELECT video_id,path,sha256 FROM videos WHERE video_id<>? AND size_bytes=? AND content_fingerprint=? AND status IN ('pending','processing','completed') LIMIT 1",
                                       (vid, stat.st_size, content_fp)).fetchone()
            duplicate_of = None
            if candidate:
                candidate_hash = candidate["sha256"] or hash_video(Path(candidate["path"]), candidate["video_id"])
                own_hash = sha256_file(path)
                if own_hash == candidate_hash:
                    duplicate_of = candidate["video_id"]
            with connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT 1 FROM ingestion_jobs WHERE video_id=? "
                    "AND status IN ('pending','processing','retry_pending') LIMIT 1", (vid,)
                ).fetchone():
                    continue
                state = "skipped" if duplicate_of or not meta["has_audio"] else "pending"
                db.execute("UPDATE videos SET duration=?,width=?,height=?,video_codec=?,audio_codec=?,has_audio=?,container=?,duplicate_of=?,status=? WHERE video_id=?",
                           (*[meta[k] for k in ("duration","width","height","video_codec","audio_codec","has_audio","container")], duplicate_of, state, vid))
                if state == "pending":
                    db.execute("INSERT INTO ingestion_jobs(job_id,video_id,status,stage) VALUES(?,?,'pending','queued')", (str(uuid.uuid4()), vid))
                else:
                    reason = "Duplicate content" if duplicate_of else "Video has no audio stream"
                    err_type = "DuplicateVideo" if duplicate_of else "NoAudio"
                    db.execute("INSERT INTO ingestion_jobs(job_id,video_id,status,stage,error_type,error_message,finished_at) VALUES(?,?,'skipped','discovery',?,?,?)", (str(uuid.uuid4()), vid, err_type, reason, time.time()))
            counts["queued"] += int(state == "pending")
            counts["skipped"] += int(state == "skipped")
        except subprocess.CalledProcessError as exc:
            counts["failed"] += 1
            event("FFprobe could not read file", level="ERROR", details={"file_name": path.name, "error": exc.stderr[-1000:]})
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            counts["failed"] += 1
            event("Library scan failed for file", level="ERROR", details={"file_name": path.name, "error": str(exc)[:1000]})
    event("Library scan completed", details=counts)
    # Keep missing-source evidence without deleting transcripts or index history. Do not
    # infer mass deletion when the allowlisted mount itself is unavailable (checked above).
    missing_rows = []
    with connect() as db:
        missing = db.execute("SELECT video_id,path FROM videos WHERE status NOT IN ('skipped','failed')").fetchall()
        for row in missing:
            if row["path"] in seen_paths:
                continue
            db.execute("UPDATE videos SET status='skipped',updated_at=CURRENT_TIMESTAMP WHERE video_id=?", (row["video_id"],))
            db.execute("UPDATE ingestion_jobs SET status='skipped',stage='source_missing',error_type='SourceMissing',error_message='Source video is no longer present in the configured library',finished_at=?,updated_at=CURRENT_TIMESTAMP WHERE video_id=? AND status IN ('pending','retry_pending')", (time.time(), row["video_id"]))
            missing_rows.append(row["video_id"])
    for vid in missing_rows:
        event("Source video is missing from library", video_id=vid, stage="source_missing", level="WARNING")
    return counts


def hash_video(path: Path, video_id: str) -> str:
    """Full SHA-256, invoked only when requested for collision/change verification."""
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    digest = h.hexdigest()
    with connect() as db:
        db.execute("UPDATE videos SET sha256=? WHERE video_id=?", (digest, video_id))
    return digest


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
