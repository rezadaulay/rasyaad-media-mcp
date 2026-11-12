"""Retention policy for rendered clip artifacts."""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from app.config import settings
from app.database import connect

log = logging.getLogger("dakwah.worker.retention")

_ARTIFACT_SUFFIXES = {
    ".mp4",
    ".srt",
    ".arabic.srt",
    ".ar.srt",
    ".rendering.mp4",
    ".rendering.srt",
    ".rendering.arabic.srt",
}
_TERMINAL_STATES = {"completed", "failed"}
_ACTIVE_STATES = {"pending", "processing", "retry_pending"}


def _valid_job_id(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _job_files(clips_dir: Path, job_id: str) -> list[Path]:
    files = []
    for path in clips_dir.glob(f"{job_id}.*"):
        if (path.name[len(job_id):] in _ARTIFACT_SUFFIXES
                and path.parent == clips_dir
                and not path.is_symlink()
                and path.is_file()):
            files.append(path)
    return files


def cleanup_expired_clip_artifacts(
    *, now: float | None = None, retention_hours: int | None = None,
) -> dict[str, int]:
    """Delete expired clip exports while retaining job history in SQLite.

    Completed and failed jobs expire from their terminal timestamp. Orphaned
    UUID-named artifacts expire from their file modification time. Jobs that
    are pending, processing, or awaiting retry are never touched.
    """
    current_time = time.time() if now is None else float(now)
    hours = settings.clip_retention_hours if retention_hours is None else int(retention_hours)
    if hours < 0:
        raise ValueError("retention_hours cannot be negative")
    cutoff = current_time - (hours * 3600)
    clips_dir = settings.data_dir / "clips"
    if not clips_dir.exists():
        return {"jobs_cleaned": 0, "files_deleted": 0}
    clips_dir = clips_dir.resolve()

    with connect() as db:
        rows = db.execute(
            "SELECT job_id,status,finished_at,checkpoint FROM clip_jobs"
        ).fetchall()
    jobs = {row["job_id"]: row for row in rows}
    expired: dict[str, list[Path]] = {}
    orphan_files: list[Path] = []

    for job_id, row in jobs.items():
        if not _valid_job_id(job_id):
            continue
        if row["status"] in _ACTIVE_STATES:
            continue
        files = _job_files(clips_dir, job_id)
        if row["status"] in _TERMINAL_STATES:
            finished_at = row["finished_at"]
            is_expired = (
                float(finished_at) <= cutoff if finished_at is not None
                else bool(files) and all(path.stat().st_mtime <= cutoff for path in files)
            )
            if is_expired:
                expired[job_id] = files

    for path in clips_dir.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        job_id, separator, suffix = path.name.partition(".")
        if not separator or suffix not in {item[1:] for item in _ARTIFACT_SUFFIXES}:
            continue
        if not _valid_job_id(job_id) or job_id in jobs:
            continue
        if path.stat().st_mtime <= cutoff:
            orphan_files.append(path)

    deleted_count = 0
    for job_id, files in expired.items():
        for path in files:
            try:
                path.unlink(missing_ok=True)
                deleted_count += 1
            except OSError:
                log.exception("Could not remove expired clip artifact path=%s", path)
        if not any(path.exists() for path in files):
            with connect() as db:
                row = db.execute(
                    "SELECT checkpoint,status FROM clip_jobs WHERE job_id=?", (job_id,),
                ).fetchone()
                if row and row["status"] in _TERMINAL_STATES:
                    checkpoint = json.loads(row["checkpoint"])
                    for key in ("output_path", "subtitle_path", "subtitle_ar_path"):
                        checkpoint.pop(key, None)
                    checkpoint["outputs_expired"] = True
                    checkpoint["outputs_expired_at"] = current_time
                    db.execute(
                        "UPDATE clip_jobs SET checkpoint=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                        (json.dumps(checkpoint, ensure_ascii=False), job_id),
                    )

    for path in orphan_files:
        try:
            path.unlink(missing_ok=True)
            deleted_count += 1
        except OSError:
            log.exception("Could not remove orphaned clip artifact path=%s", path)

    if deleted_count:
        log.info("Clip retention removed artifacts jobs=%d files=%d", len(expired), deleted_count)
    return {"jobs_cleaned": len(expired), "files_deleted": deleted_count}
