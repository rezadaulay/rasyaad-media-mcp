import hashlib
import hmac
import json
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import database, discovery, service
from app.api import main as api
from app.worker import pipeline
from app.worker import retention


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
    for module in (database, discovery, service, pipeline, retention, api):
        monkeypatch.setattr(module, "settings", cfg)
    def fake_arabic_srt(audio_path, output_path, progress_callback=None):
        assert audio_path.is_file()
        mp4_name = output_path.name.replace(".rendering.arabic.srt", ".mp4")
        assert (output_path.parent / mp4_name).is_file()
        output_path.write_text("1\n00:00:00,500 --> 00:00:01,200\nبِسْمِ اللَّهِ\n", encoding="utf-8")
        return 1, [{
            "rule": "la-yanqusu-min-ajr-as-saim-v1",
            "original": "يَنْقُسُ",
            "corrected": "يَنْقُصُ",
            "context": "لا ينقس من أجر الصائم",
            "cue_start": "00:00:00,500",
            "cue_end": "00:00:01,200",
        }]
    monkeypatch.setattr(pipeline, "_generate_arabic_srt", fake_arabic_srt)
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
        db.executemany(
            "INSERT INTO transcript_segments(segment_id,video_id,sequence_number,start_time,end_time,text,language) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("seg-before", "video", 1, 0.5, 1.2, "cue clipped at start", "id"),
                ("seg-middle", "video", 2, 1.2, 2.0, "middle cue", "id"),
                ("seg-after", "video", 3, 2.0, 3.0, "cue clipped at end", "id"),
            ],
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
    subtitle = Path(result["subtitle_path"])
    assert subtitle.is_file() and result["subtitle_cue_count"] == 3
    srt = subtitle.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:00,200\ncue clipped at start" in srt
    assert "00:00:00,200 --> 00:00:01,000\nmiddle cue" in srt
    assert "00:00:01,000 --> 00:00:01,500\ncue clipped at end" in srt
    arabic_subtitle = Path(result["subtitle_ar_path"])
    assert arabic_subtitle.is_file() and result["subtitle_ar_cue_count"] == 1
    assert "بِسْمِ اللَّهِ" in arabic_subtitle.read_text(encoding="utf-8")
    assert result["arabic_corrections"][0]["corrected"] == "يَنْقُصُ"
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
    assert Path(result["subtitle_path"]).is_file()
    assert result["subtitle_cue_count"] == 3
    assert Path(result["subtitle_ar_path"]).is_file()
    assert result["subtitle_ar_cue_count"] == 1
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


def test_arabic_subtitles_force_arabic_and_filter_latin(monkeypatch):
    from types import SimpleNamespace

    class FakeModel:
        def __init__(self):
            self.transcribe_options = []

        def detect_language(self, audio, language_detection_threshold):
            arabic_probability = sum(audio) / len(audio)
            language = "ar" if arabic_probability > 0.4 else "id"
            return language, max(arabic_probability, 1 - arabic_probability), [
                ("ar", arabic_probability), ("id", 1 - arabic_probability),
            ]

        def transcribe(self, audio, **options):
            self.transcribe_options.append(options)
            return iter([
                SimpleNamespace(start=1.0, end=2.0, text="بِسْمِ اللَّهِ", no_speech_prob=0.1, avg_logprob=-0.2),
                SimpleNamespace(start=2.0, end=3.0, text="bismillah", no_speech_prob=0.1, avg_logprob=-0.2),
            ]), SimpleNamespace(language="ar")

    audio = [0.0] * (10 * 16000)
    audio[2 * 16000:5 * 16000] = [1.0] * (3 * 16000)
    model = FakeModel()

    result, cue_count, corrections = pipeline._arabic_srt_text(model, audio)

    assert cue_count == 1
    assert "بِسْمِ اللَّهِ" in result
    assert "bismillah" not in result
    assert model.transcribe_options
    assert all(options["language"] == "ar" and options["task"] == "transcribe"
               for options in model.transcribe_options)
    assert corrections == []


def test_arabic_spelling_correction_is_limited_to_validated_context():
    raw = "وَمَنْ فَطَّرَ صَائِمًا غَيْرَ أَنَّهُ لَا يَنْقُسُ مِنْ أَجْرِ الصَّائِمِ شَيْئًا"
    corrected, corrections = pipeline._correct_arabic_spelling(raw)

    assert "لَا يَنْقُصُ مِنْ أَجْرِ الصَّائِمِ" in corrected
    assert corrections == [{
        "rule": "la-yanqusu-min-ajr-as-saim-v1",
        "original": "يَنْقُسُ",
        "corrected": "يَنْقُصُ",
        "context": "لا ينقس من أجر الصائم",
    }]

    unrelated, unrelated_corrections = pipeline._correct_arabic_spelling("هَذَا يَنْقُسُ هُنَا")
    assert unrelated == "هَذَا يَنْقُسُ هُنَا"
    assert unrelated_corrections == []


def test_arabic_subtitles_are_empty_when_no_arabic_is_detected():
    class IndonesianModel:
        def __init__(self):
            self.transcribe_called = False

        def detect_language(self, audio, language_detection_threshold):
            self.detection_calls += 1
            return "id", 0.995, [("id", 0.995), ("ar", 0.005)]

        def transcribe(self, audio, **options):
            self.transcribe_called = True
            return iter(()), None

    model = IndonesianModel()
    model.detection_calls = 0
    result, cue_count, corrections = pipeline._arabic_srt_text(model, [0.1] * (8 * 16000))

    assert result == ""
    assert cue_count == 0
    assert not model.transcribe_called
    assert model.detection_calls == 1
    assert corrections == []


def test_arabic_detector_uses_coarse_windows_before_refinement():
    class IndonesianModel:
        def __init__(self):
            self.detection_calls = 0

        def detect_language(self, audio, language_detection_threshold):
            self.detection_calls += 1
            return "id", 0.995, [("id", 0.995), ("ar", 0.005)]

        def transcribe(self, audio, **options):
            raise AssertionError("Arabic transcription should not run without Arabic candidates")

    model = IndonesianModel()
    progress = []
    result, cue_count, corrections = pipeline._arabic_srt_text(
        model, [0.1] * (30 * 16000), progress_callback=lambda *item: progress.append(item),
    )

    assert result == "" and cue_count == 0
    assert corrections == []
    assert model.detection_calls == 4  # 12-second windows every 6 seconds
    assert len(progress) == 4
    assert all(item[0] == "coarse_detection" for item in progress)


def test_mixed_long_window_with_low_arabic_probability_is_refined():
    from types import SimpleNamespace

    class MixedLanguageModel:
        def __init__(self):
            self.coarse_calls = 0
            self.fine_calls = 0

        def detect_language(self, audio, language_detection_threshold):
            if len(audio) >= 10 * 16000:
                self.coarse_calls += 1
                return "id", 0.98, [("id", 0.98), ("ar", 0.02)]
            self.fine_calls += 1
            return "ar", 0.77, [("ar", 0.77), ("id", 0.20)]

        def transcribe(self, audio, **options):
            return iter([SimpleNamespace(
                start=1.0, end=2.0, text="مثل أجره", no_speech_prob=0.1, avg_logprob=-0.2,
            )]), SimpleNamespace(language="ar")

    model = MixedLanguageModel()
    progress = []
    result, cue_count, _ = pipeline._arabic_srt_text(
        model, [0.1] * (20 * 16000), progress_callback=lambda *item: progress.append(item),
    )

    assert cue_count == 1
    assert "مثل أجره" in result
    assert model.coarse_calls > 0 and model.fine_calls > 0
    assert any(item[0] == "fine_detection" for item in progress)


def test_fine_windows_align_to_clip_time_for_short_arabic_passage():
    from types import SimpleNamespace

    class AlignedWindowModel:
        def __init__(self):
            self.fine_window_centers = []
            self.transcription_lengths = []

        def detect_language(self, audio, language_detection_threshold):
            center = sum(audio) / len(audio)
            if len(audio) >= 10 * 16000:
                return "id", 0.98, [("id", 0.98), ("ar", 0.02)]
            self.fine_window_centers.append(center)
            if 12.0 <= center <= 13.0:
                return "ar", 0.77, [("ar", 0.77), ("id", 0.20)]
            return "id", 0.95, [("id", 0.95), ("ar", 0.05)]

        def transcribe(self, audio, **options):
            self.transcription_lengths.append(len(audio))
            return iter([SimpleNamespace(
                start=1.0, end=2.0, text="مثل أجره", no_speech_prob=0.1, avg_logprob=-0.2,
            )]), SimpleNamespace(language="ar")

    sample_rate = 16000
    audio = [index / sample_rate for index in range(20 * sample_rate)]
    model = AlignedWindowModel()

    result, cue_count, _ = pipeline._arabic_srt_text(model, audio, sample_rate=sample_rate)

    assert any(abs(center - 12.5) < 0.01 for center in model.fine_window_centers)
    assert cue_count == 1
    assert "مثل أجره" in result
    assert model.transcription_lengths == [15 * sample_rate]


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
        subtitle = cfg.data_dir / "clips" / "render-job.srt"
        subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\ntest subtitle\n", encoding="utf-8")
        arabic_subtitle = cfg.data_dir / "clips" / "render-job.arabic.srt"
        arabic_subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nنص عربي\n", encoding="utf-8")
        db.execute(
            "INSERT INTO clip_jobs(job_id,proposal_id,video_id,status,checkpoint) VALUES('render-job','proposal','video','completed',?)",
            (json.dumps({"output_path": str(output), "subtitle_path": str(subtitle),
                         "subtitle_ar_path": str(arabic_subtitle)}),),
        )
    expires = int(time.time()) + 300
    message = f"clip-job:render-job:{expires}".encode()
    signature = hmac.new(b"operator", message, hashlib.sha256).hexdigest()
    with TestClient(api.app) as client:
        response = client.get(f"/clip-download/render-job?expires={expires}&signature={signature}")
        assert response.status_code == 200
        assert response.content == b"mp4 fixture"
        subtitle_response = client.get(f"/clip-download/render-job/subtitle?expires={expires}&signature={signature}")
        assert subtitle_response.status_code == 200
        assert b"test subtitle" in subtitle_response.content
        arabic_response = client.get(
            f"/clip-download/render-job/subtitle/ar?expires={expires}&signature={signature}"
        )
        assert arabic_response.status_code == 200
        assert "نص عربي".encode("utf-8") in arabic_response.content
        assert 'filename="render-job.arabic.srt"' in arabic_response.headers["content-disposition"]

        legacy_path = cfg.data_dir / "clips" / "legacy-job.ar.srt"
        legacy_path.write_text("legacy Arabic", encoding="utf-8")
        with database.connect() as db:
            db.execute(
                "INSERT INTO clip_jobs(job_id,proposal_id,video_id,status,checkpoint) "
                "VALUES('legacy-job','proposal','video','completed',?)",
                (json.dumps({"output_path": str(output), "subtitle_ar_path": str(legacy_path)}),),
            )
        legacy_expires = int(time.time()) + 300
        legacy_signature = hmac.new(
            b"operator", f"clip-job:legacy-job:{legacy_expires}".encode(), hashlib.sha256,
        ).hexdigest()
        legacy_response = client.get(
            f"/clip-download/legacy-job/subtitle/ar?expires={legacy_expires}&signature={legacy_signature}"
        )
        assert legacy_response.status_code == 200
        assert legacy_response.content == b"legacy Arabic"
        assert 'filename="legacy-job.ar.srt"' in legacy_response.headers["content-disposition"]
        assert client.get(f"/clip-download/render-job?expires={expires}&signature=wrong").status_code == 403
        assert client.get(f"/clip-download/render-job?expires=1&signature={signature}").status_code == 403


def test_clip_retention_removes_only_expired_job_artifacts(clip_env):
    cfg, _ = clip_env
    now = 2_000_000.0
    cutoff = now - 48 * 3600
    clips_dir = cfg.data_dir / "clips"
    clips_dir.mkdir(parents=True)
    old_job = "11111111-1111-4111-8111-111111111111"
    recent_job = "22222222-2222-4222-8222-222222222222"
    active_job = "33333333-3333-4333-8333-333333333333"
    orphan_job = "44444444-4444-4444-8444-444444444444"
    old_files = [
        clips_dir / f"{old_job}.mp4",
        clips_dir / f"{old_job}.srt",
        clips_dir / f"{old_job}.arabic.srt",
        clips_dir / f"{old_job}.ar.srt",
    ]
    for path in old_files:
        path.write_text("derived clip fixture", encoding="utf-8")
    recent_path = clips_dir / f"{recent_job}.mp4"
    active_path = clips_dir / f"{active_job}.mp4"
    orphan_path = clips_dir / f"{orphan_job}.mp4"
    unrelated_path = clips_dir / "keep.txt"
    for path in (recent_path, active_path, orphan_path, unrelated_path):
        path.write_text("fixture", encoding="utf-8")
    for path in (*old_files, orphan_path):
        os.utime(path, (cutoff - 1, cutoff - 1))

    with database.connect() as db:
        db.executemany(
            "INSERT INTO clip_jobs(job_id,proposal_id,video_id,status,finished_at,checkpoint) "
            "VALUES(?, 'proposal', 'video', ?, ?, ?)",
            [
                (old_job, "completed", cutoff - 1, json.dumps({
                    "output_path": str(old_files[0]), "subtitle_path": str(old_files[1]),
                    "subtitle_ar_path": str(old_files[2]),
                })),
                (recent_job, "completed", cutoff + 1, json.dumps({"output_path": str(recent_path)})),
                (active_job, "processing", cutoff - 3600, json.dumps({"output_path": str(active_path)})),
            ],
        )

    result = retention.cleanup_expired_clip_artifacts(now=now, retention_hours=48)

    assert result == {"jobs_cleaned": 1, "files_deleted": 5}
    assert all(not path.exists() for path in old_files)
    assert not orphan_path.exists()
    assert recent_path.is_file() and active_path.is_file() and unrelated_path.is_file()
    old_result = service.get_clip_job(old_job)
    assert old_result["outputs_expired"] is True
    assert old_result["output_path"] is None
    with database.connect() as db:
        checkpoint = json.loads(db.execute(
            "SELECT checkpoint FROM clip_jobs WHERE job_id=?", (old_job,),
        ).fetchone()[0])
    assert checkpoint["outputs_expired"] is True
    assert "subtitle_path" not in checkpoint and "subtitle_ar_path" not in checkpoint


def test_expired_clip_job_does_not_return_dead_download_links(monkeypatch):
    from app import mcp_server

    monkeypatch.setattr(mcp_server, "PUBLIC_BASE_URL", "https://clips.example.test")
    monkeypatch.setattr(mcp_server, "TOKEN", "secret")
    monkeypatch.setattr(mcp_server, "call", lambda *args: {
        "job_id": "expired-job", "status": "completed", "outputs_expired": True,
        "output_path": None,
    })

    result = mcp_server.get_clip_job("expired-job")

    assert result["outputs_expired"] is True
    assert "download_url" not in result


def test_mcp_job_status_builds_short_lived_download_url(monkeypatch):
    from app import mcp_server

    monkeypatch.setattr(mcp_server, "PUBLIC_BASE_URL", "https://clips.example.test")
    monkeypatch.setattr(mcp_server, "TOKEN", "secret")
    monkeypatch.setattr(mcp_server, "call", lambda *args: {
        "job_id": "job-1", "status": "completed", "subtitle_path": "/data/clips/job-1.srt",
        "subtitle_ar_path": "/data/clips/job-1.arabic.srt", "output_path": "/data/clips/job-1.mp4",
    })

    result = mcp_server.get_clip_job("job-1")

    assert result["download_url"].startswith("https://clips.example.test/clip-download/job/job-1?")
    assert result["subtitle_url"].startswith("https://clips.example.test/clip-download/job/job-1/subtitle?")
    assert result["subtitle_ar_url"].startswith("https://clips.example.test/clip-download/job/job-1/subtitle/ar?")
    assert 0 < result["download_url_expires_at"] - int(time.time()) <= 900
