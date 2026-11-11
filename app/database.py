"""SQLite metadata store. SQLite is the source of truth for job state."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.config import settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS videos (
 video_id TEXT PRIMARY KEY, path TEXT NOT NULL UNIQUE, file_name TEXT NOT NULL,
 size_bytes INTEGER NOT NULL, mtime REAL NOT NULL, fingerprint TEXT NOT NULL,
 content_fingerprint TEXT, duplicate_of TEXT, sha256 TEXT, duration REAL, width INTEGER, height INTEGER, video_codec TEXT,
 audio_codec TEXT, has_audio INTEGER, container TEXT, status TEXT NOT NULL DEFAULT 'discovered',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE TABLE IF NOT EXISTS file_observations (
 path TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ingestion_jobs (
 job_id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
 status TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'queued', retry_count INTEGER NOT NULL DEFAULT 0,
 progress REAL, error_type TEXT, error_message TEXT, checkpoint TEXT NOT NULL DEFAULT '{}',
 available_at REAL NOT NULL DEFAULT 0, started_at REAL, finished_at REAL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON ingestion_jobs(status,available_at,created_at);
CREATE TABLE IF NOT EXISTS transcripts (
 video_id TEXT PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
 language TEXT, asr_model TEXT NOT NULL, asr_config TEXT NOT NULL, file_path TEXT NOT NULL,
 segment_count INTEGER NOT NULL DEFAULT 0, duration REAL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transcript_segments (
 segment_id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
 sequence_number INTEGER NOT NULL, start_time REAL NOT NULL, end_time REAL NOT NULL,
 text TEXT NOT NULL, language TEXT, confidence REAL, words_json TEXT,
 UNIQUE(video_id,sequence_number)
);
CREATE INDEX IF NOT EXISTS idx_segments_video_time ON transcript_segments(video_id,start_time);
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_fts USING fts5(segment_id UNINDEXED, video_id UNINDEXED, text, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS semantic_chunks (
 chunk_id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
 sequence_number INTEGER NOT NULL, start_time REAL NOT NULL, end_time REAL NOT NULL, text TEXT NOT NULL,
 previous_chunk_id TEXT, next_chunk_id TEXT, language TEXT, segmentation_version TEXT NOT NULL,
 source_transcript_reference TEXT NOT NULL, UNIQUE(video_id,sequence_number)
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, video_id UNINDEXED, text, tokenize='unicode61');
CREATE TABLE IF NOT EXISTS embedding_indexes (
 index_id TEXT PRIMARY KEY, model_version TEXT NOT NULL, dimension INTEGER NOT NULL,
 collection_name TEXT NOT NULL, segmentation_version TEXT NOT NULL, status TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(model_version,segmentation_version)
);
CREATE TABLE IF NOT EXISTS processing_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, job_id TEXT, stage TEXT,
 level TEXT NOT NULL DEFAULT 'INFO', message TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS worker_status (
 worker_id TEXT PRIMARY KEY, process_id INTEGER NOT NULL, started_at REAL NOT NULL,
 heartbeat_at REAL NOT NULL, stage TEXT NOT NULL
);
"""

# SQLite's user_version is reserved here for ordered schema upgrades. Version 1
# is the schema shipped before migrations were introduced. Keeping that schema
# as an idempotent baseline lets existing installations adopt versioning
# without dropping or rewriting their data.
SCHEMA_VERSION = 3

MIGRATION_2 = """
CREATE TABLE IF NOT EXISTS content_proposals (
 proposal_id TEXT PRIMARY KEY,
 video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN ('draft','proposed','approved','rejected','needs_revision')),
 proposal_json TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 reviewed_at TEXT,
 review_decision TEXT CHECK(review_decision IS NULL OR review_decision IN ('approved','rejected','needs_revision')),
 review_notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_proposals_video_status ON content_proposals(video_id,status,created_at);
"""

MIGRATION_3 = """
CREATE TABLE IF NOT EXISTS clip_jobs (
 job_id TEXT PRIMARY KEY,
 proposal_id TEXT NOT NULL REFERENCES content_proposals(proposal_id) ON DELETE CASCADE,
 video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_pending','completed','failed')),
 stage TEXT NOT NULL DEFAULT 'queued',
 retry_count INTEGER NOT NULL DEFAULT 0,
 progress REAL,
 error_type TEXT,
 error_message TEXT,
 checkpoint TEXT NOT NULL DEFAULT '{}',
 available_at REAL NOT NULL DEFAULT 0,
 started_at REAL,
 finished_at REAL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_clip_jobs_claim ON clip_jobs(status,available_at,created_at);
CREATE INDEX IF NOT EXISTS idx_clip_jobs_proposal ON clip_jobs(proposal_id,created_at);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(settings.db_path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    for attempt in range(5):
        try:
            with connect() as db:
                current_version = int(db.execute("PRAGMA user_version").fetchone()[0])
                if current_version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"Database schema version {current_version} is newer than "
                        f"this application supports ({SCHEMA_VERSION})"
                    )

                # Version 0 includes both a new/empty database and databases
                # created before version tracking. CREATE IF NOT EXISTS keeps
                # existing rows intact while establishing the v1 baseline.
                if current_version == 0:
                    db.executescript(SCHEMA)
                    current_version = 1
                    db.execute("PRAGMA user_version = 1")
                if current_version < 2:
                    db.executescript(MIGRATION_2)
                    db.execute("PRAGMA user_version = 2")
                    current_version = 2
                if current_version < 3:
                    db.executescript(MIGRATION_3)
                    db.execute("PRAGMA user_version = 3")
            return
        except sqlite3.OperationalError as exc:
            if "lock" not in str(exc).lower() or attempt == 4:
                raise
            # The API and worker can start together against the same SQLite
            # file. Retry brief startup lock contention before failing health.
            time.sleep(0.2 * (attempt + 1))


def event(message: str, *, video_id: str | None = None, job_id: str | None = None,
          stage: str | None = None, level: str = "INFO", details: dict[str, Any] | None = None) -> None:
    with connect() as db:
        db.execute("INSERT INTO processing_events(video_id,job_id,stage,level,message,details_json) VALUES(?,?,?,?,?,?)",
                   (video_id, job_id, stage, level, message, json.dumps(details or {})))


def beat_worker(worker_id: str, process_id: int, started_at: float, stage: str = "idle") -> None:
    with connect() as db:
        db.execute("INSERT INTO worker_status(worker_id,process_id,started_at,heartbeat_at,stage) VALUES(?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET process_id=excluded.process_id,started_at=excluded.started_at,heartbeat_at=excluded.heartbeat_at,stage=excluded.stage",
                   (worker_id, process_id, started_at, time.time(), stage))


def claim_job() -> sqlite3.Row | None:
    now = time.time()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM ingestion_jobs WHERE status IN ('pending','retry_pending') AND available_at<=? ORDER BY created_at LIMIT 1", (now,)).fetchone()
        if not row:
            return None
        db.execute("UPDATE ingestion_jobs SET status='processing',started_at=?,error_type=NULL,error_message=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (now, row['job_id']))
        db.execute("UPDATE videos SET status='processing',updated_at=CURRENT_TIMESTAMP WHERE video_id=?", (row['video_id'],))
        return db.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (row['job_id'],)).fetchone()


def set_stage(job_id: str, stage: str, progress: float | None = None, checkpoint: dict[str, Any] | None = None) -> None:
    with connect() as db:
        db.execute("UPDATE ingestion_jobs SET stage=?,progress=COALESCE(?,progress),checkpoint=COALESCE(json_patch(checkpoint,?),checkpoint),updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                   (stage, progress, json.dumps(checkpoint) if checkpoint is not None else None, job_id))
        db.execute("UPDATE clip_jobs SET stage=?,progress=COALESCE(?,progress),checkpoint=COALESCE(json_patch(checkpoint,?),checkpoint),updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                   (stage, progress, json.dumps(checkpoint) if checkpoint is not None else None, job_id))


def finish_job(job_id: str, video_id: str, status: str, error: Exception | None = None) -> None:
    with connect() as db:
        job = db.execute("SELECT retry_count FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
        retries = int(job['retry_count']) if job else 0
        if error:
            retries += 1
            terminal = retries >= settings.retry_limit
            state = 'failed' if terminal else 'retry_pending'
            delay = min(3600, 30 * (2 ** (retries - 1)))
            db.execute("UPDATE ingestion_jobs SET status=?,retry_count=?,error_type=?,error_message=?,available_at=?,finished_at=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                       (state, retries, type(error).__name__, str(error)[:2000], time.time()+delay, time.time() if terminal else None, job_id))
            db.execute("UPDATE videos SET status=?,updated_at=CURRENT_TIMESTAMP WHERE video_id=?", (state, video_id))
        else:
            db.execute("UPDATE ingestion_jobs SET status=?,stage='completed',progress=1,error_type=NULL,error_message=NULL,finished_at=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                       (status, time.time(), job_id))
            db.execute("UPDATE videos SET status=?,updated_at=CURRENT_TIMESTAMP WHERE video_id=?", (status, video_id))


def claim_clip_job() -> sqlite3.Row | None:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM clip_jobs WHERE status IN ('pending','retry_pending') AND available_at<=? ORDER BY created_at LIMIT 1", (time.time(),)).fetchone()
        if not row:
            return None
        db.execute("UPDATE clip_jobs SET status='processing',stage='rendering',started_at=?,error_type=NULL,error_message=NULL,updated_at=CURRENT_TIMESTAMP WHERE job_id=?", (time.time(), row['job_id']))
        return db.execute("SELECT * FROM clip_jobs WHERE job_id=?", (row['job_id'],)).fetchone()


def finish_clip_job(job_id: str, status: str, error: Exception | None = None) -> None:
    with connect() as db:
        row = db.execute("SELECT retry_count FROM clip_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return
        if error:
            retries = int(row['retry_count']) + 1
            terminal = retries >= settings.retry_limit
            state = 'failed' if terminal else 'retry_pending'
            delay = min(3600, 30 * (2 ** (retries - 1)))
            db.execute("UPDATE clip_jobs SET status=?,stage='failed',retry_count=?,error_type=?,error_message=?,available_at=?,finished_at=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                       (state, retries, type(error).__name__, str(error)[:2000], time.time()+delay, time.time() if terminal else None, job_id))
        else:
            db.execute("UPDATE clip_jobs SET status=?,stage='completed',progress=1,error_type=NULL,error_message=NULL,finished_at=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                       (status, time.time(), job_id))

