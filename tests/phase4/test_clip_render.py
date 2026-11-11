import hashlib
import hmac
import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database, discovery, service
from app.api import main as api
from app.worker import pipeline


@pytest.fixture
def clip_env(monkeypatch, tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    source = root / "sample.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc=size=320x240:rate=24:duration=4", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", str(source),
    ], check=True, timeout=30)
    cfg = replace(database.settings, data_dir=tmp_path / "data", db_path=tmp_path / "data" / "metadata.sqlite3",
                  library_root=root, api_token="operator", retry_limit=2)
    for module in (database, discovery, service, pipeline, api):
        monkeypatch.setattr(module, "settings", cfg)
    database.initialize()
    with database.connect() as db:
        db.execute(
            "INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,content_fingerprint,duration,status,has_audio) "
            "VALUES('video',?,?,?,?,?,?,4,'completed',1)",
            (str(source), source.name, source.stat().st_size, source.stat().st_mtime,
             discovery.fingerprint(source), discovery.content_fingerprint(source)),
        )
        db.execute(
            "INSERT INTO content_proposals(proposal_id,video_id,status,proposal_json,created_at) VALUES('proposal','video',?,?,'now')",
            ("proposed", json.dumps({"start_time": 1.0, "end_time": 2.5, "duration": 1.5})),
        )
    return cfg, source


def test_render_requires_approval_and_reuses_active_job(clip_env):
    cfg, _ = clip_env
    with pytest.raises(service.ClipRequestError, match="approved"):
        service.request_clip_render("proposal")
    with database.connect() as db:
        db.execute("UPDATE content_proposals SET status='approved' WHERE proposal_id='proposal'")

    first = service.request_clip_render("proposal")
    with database.connect() as db:
        db.execute("UPDATE clip_jobs SET status='processing' WHERE job_id=?", (first["job_id"],))
    second = service.request_clip_render("proposal")
    assert first["job_id"] == second["job_id"]
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM clip_jobs").fetchone()[0] == 1


def test_worker_renders_approved_range_and_preserves_source(clip_env):
    cfg, source = clip_env
    with database.connect() as db:
        db.execute("UPDATE content_proposals SET status='approved' WHERE proposal_id='proposal'")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    requested = service.request_clip_render("proposal")
    job = database.claim_clip_job()
    assert job["job_id"] == requested["job_id"]

    pipeline.render_clip_job(job)

    result = service.get_clip_job(job["job_id"])
    output = Path(result["output_path"])
    assert result["status"] == "completed"
    assert output.is_file() and output.parent == cfg.data_dir / "clips"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(output),
    ], check=True, capture_output=True, text=True, timeout=15)
    assert abs(float(json.loads(probe.stdout)["format"]["duration"]) - 1.5) <= 1.0


def test_vertical_clip_is_center_cropped_to_social_dimensions(clip_env):
    cfg, _ = clip_env
    with database.connect() as db:
        db.execute("UPDATE content_proposals SET status='approved' WHERE proposal_id='proposal'")
    requested = service.request_clip_render("proposal", "vertical_9_16")
    job = database.claim_clip_job()

    pipeline.render_clip_job(job)

    result = service.get_clip_job(requested["job_id"])
    assert result["status"] == "completed"
    assert result["render_preset"] == "vertical_9_16"
    assert (result["output_width"], result["output_height"]) == (1080, 1920)
    probe = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=width,height",
        "-of", "json", str(result["output_path"]),
    ], check=True, capture_output=True, text=True, timeout=15)
    video = next(stream for stream in json.loads(probe.stdout)["streams"] if "width" in stream)
    assert (video["width"], video["height"]) == (1080, 1920)


def test_clip_profiles_have_separate_active_jobs(clip_env):
    with database.connect() as db:
        db.execute("UPDATE content_proposals SET status='approved' WHERE proposal_id='proposal'")
    original = service.request_clip_render("proposal")
    vertical = service.request_clip_render("proposal", "vertical_9_16")
    vertical_again = service.request_clip_render("proposal", "vertical_9_16")

    assert original["job_id"] != vertical["job_id"]
    assert vertical["job_id"] == vertical_again["job_id"]


def test_clip_api_authorization_and_status(clip_env):
    _, _ = clip_env
    with database.connect() as db:
        db.execute("UPDATE content_proposals SET status='approved' WHERE proposal_id='proposal'")
    with TestClient(api.app) as client:
        url = "/clip-jobs?proposal_id=proposal"
        assert client.post(url).status_code == 403
        response = client.post(url, headers={"X-Ingestion-Token": "operator"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert client.get(f"/clip-jobs/{job_id}").json()["status"] == "pending"
        assert client.get("/clip-jobs/unknown").status_code == 404

        vertical = client.post(
            "/clip-jobs?proposal_id=proposal&render_preset=vertical_9_16",
            headers={"X-Ingestion-Token": "operator"},
        )
        assert vertical.status_code == 202
        assert vertical.json()["render_preset"] == "vertical_9_16"


def test_mcp_vertical_tool_requests_vertical_profile(monkeypatch):
    from app import mcp_server

    seen = {}
    monkeypatch.setattr(mcp_server, "call", lambda path, params, method: seen.update(
        path=path, params=params, method=method) or {"job_id": "vertical-job", "status": "pending"})

    result = mcp_server.request_vertical_clip_render("proposal-1")

    assert result["job_id"] == "vertical-job"
    assert seen == {
        "path": "/clip-jobs",
        "params": {"proposal_id": "proposal-1", "render_preset": "vertical_9_16"},
        "method": "POST",
    }


def test_render_rejects_range_over_ten_minutes(clip_env):
    _, _ = clip_env
    with database.connect() as db:
        db.execute("UPDATE content_proposals SET status='approved',proposal_json=? WHERE proposal_id='proposal'",
                   (json.dumps({"start_time": 0, "end_time": 601, "duration": 601}),))
    with pytest.raises(service.ClipRequestError, match="600-second"):
        service.request_clip_render("proposal")


def test_clip_job_recovers_after_worker_restart(clip_env, monkeypatch):
    from app.worker import __main__ as worker

    cfg, _ = clip_env
    monkeypatch.setattr(worker, "settings", cfg)
    with database.connect() as db:
        db.execute("UPDATE content_proposals SET status='approved' WHERE proposal_id='proposal'")
    requested = service.request_clip_render("proposal")
    with database.connect() as db:
        db.execute("UPDATE clip_jobs SET status='processing' WHERE job_id=?", (requested["job_id"],))

    worker.recover_interrupted_clip_jobs()
    retried = database.claim_clip_job()
    assert retried["job_id"] == requested["job_id"]
    assert retried["status"] == "processing"
    assert json.loads(retried["checkpoint"])["end_time"] == 2.5


def test_signed_https_download_is_limited_and_expires(clip_env):
    cfg, _ = clip_env
    output = cfg.data_dir / "clips" / "render-job.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"mp4 fixture")
    with database.connect() as db:
        db.execute(
            "INSERT INTO clip_jobs(job_id,proposal_id,video_id,status,checkpoint) VALUES('render-job','proposal','video','completed',?)",
            (json.dumps({"output_path": str(output)}),),
        )
    expires = int(time.time()) + 300
    message = f"clip-job:render-job:{expires}".encode()
    signature = hmac.new(b"operator", message, hashlib.sha256).hexdigest()
    with TestClient(api.app) as client:
        response = client.get(f"/clip-download/render-job?expires={expires}&signature={signature}")
        assert response.status_code == 200
        assert response.content == b"mp4 fixture"
        assert client.get(f"/clip-download/render-job?expires={expires}&signature=wrong").status_code == 403
        assert client.get(f"/clip-download/render-job?expires=1&signature={signature}").status_code == 403


def test_mcp_job_status_builds_short_lived_download_url(monkeypatch):
    from app import mcp_server

    monkeypatch.setattr(mcp_server, "PUBLIC_BASE_URL", "https://clips.example.test")
    monkeypatch.setattr(mcp_server, "TOKEN", "secret")
    monkeypatch.setattr(mcp_server, "call", lambda *args: {"job_id": "job-1", "status": "completed"})

    result = mcp_server.get_clip_job("job-1")

    assert result["download_url"].startswith("https://clips.example.test/clip-download/job/job-1?")
    assert 0 < result["download_url_expires_at"] - int(time.time()) <= 900
