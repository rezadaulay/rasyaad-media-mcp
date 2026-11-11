import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import database, discovery, embedding, service
from app.api import main as api
from app.worker import pipeline


@pytest.fixture
def config(monkeypatch, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    cfg = replace(database.settings, library_root=root, data_dir=tmp_path,
                  db_path=tmp_path / "metadata.sqlite3", api_token="operator", retry_limit=2)
    for module in (database, discovery, pipeline, api):
        monkeypatch.setattr(module, "settings", cfg)
    database.initialize()
    return cfg


def add_video(video_id, path, status="completed"):
    with database.connect() as db:
        db.execute(
            "INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,status,has_audio) "
            "VALUES(?,?,?,1,0,'f',?,1)", (video_id, str(path), path.name, status)
        )
        db.execute(
            "INSERT INTO semantic_chunks(chunk_id,video_id,sequence_number,start_time,end_time,text,"
            "language,segmentation_version,source_transcript_reference) "
            "VALUES(?,?,0,10,20,'sermon','id','test','test')", (video_id, video_id)
        )
        db.execute("INSERT INTO chunks_fts VALUES(?,?,'sermon')", (video_id, video_id))


def test_search_filters_fts_before_fusion(config, monkeypatch):
    statuses = ("completed", "pending", "processing", "retry_pending", "failed", "skipped", "discovered")
    for status in statuses:
        add_video(status, config.library_root / f"{status}.mp4", status)
    add_video("missing", config.library_root / "missing.mp4")
    with database.connect() as db:
        db.execute("DELETE FROM videos WHERE video_id='missing'")
        db.execute("INSERT INTO embedding_indexes VALUES('test','test',1,'test','test','ready',CURRENT_TIMESTAMP)")
    points = [SimpleNamespace(payload={"video_id": key, "chunk_id": key}, score=0.9)
              for key in ("failed", "missing", "completed")]
    monkeypatch.setattr(service, "get_qdrant", lambda: SimpleNamespace(
        query_points=lambda **kwargs: SimpleNamespace(points=points)
    ))
    monkeypatch.setattr(service, "ensure_collection", lambda *args: None)
    monkeypatch.setattr(service, "embed_query", lambda query: [1.0])
    items = service.search_sermons("sermon", language="id", filters={"start_time_gte": 15})["items"]
    assert [(item["video_id"], item["matched_by"]) for item in items] == [("completed", "hybrid")]
    points.clear()
    assert [item["score_type"] for item in service.search_sermons("sermon")["items"]] == ["keyword_only"]
    assert service.search_sermons("sermon", video_id="failed")["items"] == []
    assert service.search_sermons("sermon", language="en")["items"] == []
    assert service.search_sermons("sermon", filters={"end_time_lte": 5})["items"] == []


def test_operator_api(config):
    source = config.library_root / "video.mp4"
    source.write_bytes(b"original")
    add_video("video", source)
    add_video("missing", config.library_root / "missing.mp4")
    outside = config.data_dir / "outside.mp4"
    outside.write_bytes(b"outside")
    add_video("outside", outside)
    with database.connect() as db:
        db.execute("INSERT INTO ingestion_jobs(job_id,video_id,status) VALUES('old','video','completed')")
        db.execute("INSERT INTO transcripts(video_id,asr_model,asr_config,file_path) VALUES('video','old','{}','old')")
    with TestClient(api.app) as client:
        url = "/videos/video/reprocess"
        assert client.post(url).status_code == 403
        assert client.post(url, headers={"X-Ingestion-Token": "wrong"}).status_code == 403
        headers = {"X-Ingestion-Token": "operator"}
        for video_id, status in (("unknown", 404), ("missing", 404), ("outside", 409)):
            assert client.post(f"/videos/{video_id}/reprocess", headers=headers).status_code == status
        assert client.get("/videos/video/transcript").json()["transcript"]["asr_model"] == "old"
        response = client.post(url, headers=headers)
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert response.json() == {"video_id": "video", "job_id": job_id, "status": "pending"}
        assert client.get("/videos/video").json()["job"]["job_id"] == job_id
        assert client.get("/videos/video/transcript").json()["transcript"] is None
        assert client.get("/chunks/video/context").status_code == 404
        for status in ("pending", "processing", "retry_pending"):
            with database.connect() as db:
                db.execute("UPDATE ingestion_jobs SET status=? WHERE job_id=?", (status, job_id))
            conflict = client.post(url, headers=headers)
            assert conflict.status_code == 409
            assert job_id in conflict.json()["detail"]
    with database.connect() as db:
        rows = db.execute("SELECT checkpoint FROM ingestion_jobs WHERE job_id <> 'old'").fetchall()
    assert [json.loads(row[0]) for row in rows] == [{"reprocess": True}]
    assert source.read_bytes() == b"original"


def test_scan_keeps_explicit_job_when_source_changes(config):
    source = config.library_root / "changed.mp4"
    source.write_bytes(b"original")
    video_id = discovery.video_id_for(source)
    add_video(video_id, source)
    job_id = service.request_reprocess(video_id)["job_id"]
    source.write_bytes(b"replacement")

    assert discovery.scan_library()["queued"] == 0
    job = database.claim_job()
    assert job["job_id"] == job_id
    assert json.loads(job["checkpoint"])["reprocess"] is True


def test_recovered_worker_transcribes_fresh(config, monkeypatch):
    from app.worker import __main__ as worker

    monkeypatch.setattr(worker, "settings", config)
    source = config.library_root / "video.mp4"
    source.write_bytes(b"original")
    add_video("video", source)
    pipeline.atomic_json(config.data_dir / "transcripts" / "video.json", {"old": True})
    job_id = service.request_reprocess("video")["job_id"]
    assert database.claim_job()["job_id"] == job_id
    database.set_stage(job_id, "transcription", 0.5, {"segments_saved": 100})
    worker.recover_interrupted_jobs()
    assert service.get_video_metadata("video")["job"]["error_type"] == "WorkerRestart"
    job = database.claim_job()
    assert json.loads(job["checkpoint"]) == {"reprocess": True, "segments_saved": 100}
    monkeypatch.setattr(embedding, "remove_video_points", lambda video_id: None)
    fresh = {"language": "id", "asr_model": "fresh", "asr_config": {}, "duration": 1, "segments": []}
    calls = []

    def transcribe(job, video):
        calls.append(job["job_id"])
        return fresh

    monkeypatch.setattr(pipeline, "transcribe", transcribe)
    monkeypatch.setattr(pipeline, "embed_and_index", lambda video, transcript: calls.append(transcript) or 0)
    pipeline.process_job(job)
    assert calls == [job_id, fresh]
    assert service.get_video_metadata("video")["job"]["status"] == "completed"
    assert service.get_transcript("video")["transcript"]["asr_model"] == "fresh"
    assert source.read_bytes() == b"original"
