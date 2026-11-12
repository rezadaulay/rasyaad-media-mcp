"""Periodic scanner and bounded single-job worker."""
import logging
import signal
import time
import os
import threading

from app.config import settings
from app.database import connect, initialize, claim_clip_job, claim_job, event, beat_worker
from app.discovery import scan_library
from app.worker.pipeline import process_job, render_clip_job
from app.worker.retention import cleanup_expired_clip_artifacts

logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger=logging.getLogger("dakwah.worker")
stopping=False
worker_id=f"worker-{os.getpid()}"
started_at=time.time()

def request_stop(signum, frame):
    global stopping
    stopping=True

signal.signal(signal.SIGTERM,request_stop)
signal.signal(signal.SIGINT,request_stop)

def recover_interrupted_jobs():
    with connect() as db:
        rows=db.execute("SELECT job_id,video_id FROM ingestion_jobs WHERE status='processing'").fetchall()
        for row in rows:
            current=db.execute("SELECT retry_count FROM ingestion_jobs WHERE job_id=?",(row['job_id'],)).fetchone()
            retries=int(current['retry_count'])+1
            status='failed' if retries >= settings.retry_limit else 'retry_pending'
            db.execute("UPDATE ingestion_jobs SET status=?,stage='recovered_after_restart',retry_count=?,error_type='WorkerRestart',error_message='Worker stopped while this job was processing',available_at=0,finished_at=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",(status,retries,time.time() if status=='failed' else None,row['job_id']))
            db.execute("UPDATE videos SET status=? WHERE video_id=?",(status,row['video_id']))
    if rows: event("Recovered interrupted jobs after worker restart",details={"count":len(rows)})


def recover_interrupted_clip_jobs():
    with connect() as db:
        rows = db.execute("SELECT job_id FROM clip_jobs WHERE status='processing'").fetchall()
        for row in rows:
            job = db.execute("SELECT retry_count FROM clip_jobs WHERE job_id=?", (row["job_id"],)).fetchone()
            retries = int(job["retry_count"]) + 1
            status = "failed" if retries >= settings.retry_limit else "retry_pending"
            db.execute("UPDATE clip_jobs SET status=?,stage='recovered_after_restart',retry_count=?,error_type='WorkerRestart',error_message='Worker stopped while this clip was rendering',available_at=0,finished_at=?,updated_at=CURRENT_TIMESTAMP WHERE job_id=?",
                       (status, retries, time.time() if status == "failed" else None, row["job_id"]))
    if rows:
        event("Recovered interrupted clip jobs after worker restart", details={"count": len(rows)})

def heartbeat_loop():
    while not stopping:
        try:
            with connect() as db:
                active=db.execute("SELECT stage FROM ingestion_jobs WHERE status='processing' ORDER BY started_at DESC LIMIT 1").fetchone()
            beat_worker(worker_id,os.getpid(),started_at,active['stage'] if active else 'idle')
        except Exception:
            logger.exception("Worker heartbeat update failed")
        time.sleep(10)

def main():
    initialize(); recover_interrupted_jobs(); recover_interrupted_clip_jobs()
    threading.Thread(target=heartbeat_loop,name="worker-heartbeat",daemon=True).start()
    next_scan=0.0
    next_clip_cleanup=0.0
    prefer_clip=True
    logger.info(
        "Worker started concurrency=1 scan_interval_seconds=%s clip_retention_hours=%s clip_cleanup_interval_seconds=%s",
        settings.scan_interval_seconds, settings.clip_retention_hours, settings.clip_cleanup_interval_seconds,
    )
    while not stopping:
        if time.monotonic() >= next_clip_cleanup:
            try:
                cleanup_expired_clip_artifacts()
            except Exception:
                logger.exception("Expired clip artifact cleanup failed")
            next_clip_cleanup = time.monotonic() + settings.clip_cleanup_interval_seconds
        if time.monotonic() >= next_scan:
            try:
                logger.info("Library scan: %s",scan_library())
            except Exception:
                logger.exception("Library scan failed")
            next_scan=time.monotonic()+settings.scan_interval_seconds
        clip_job = claim_clip_job() if prefer_clip else None
        job = claim_job() if clip_job is None else None
        if job is None and clip_job is None and not prefer_clip:
            clip_job = claim_clip_job()
        if clip_job:
            logger.info("Claimed clip job_id=%s proposal_id=%s stage=%s",clip_job["job_id"],clip_job["proposal_id"],clip_job["stage"])
            render_clip_job(clip_job)
            prefer_clip=False
            continue
        if job:
            logger.info("Claimed job_id=%s video_id=%s stage=%s",job['job_id'],job['video_id'],job['stage'])
            process_job(job)
            prefer_clip=True
            continue
        time.sleep(2)
    logger.info("Worker stopped cleanly")
    beat_worker(worker_id,os.getpid(),started_at,"stopped")

if __name__=="__main__": main()
