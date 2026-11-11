import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import database, service

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/phase3/fixtures/simulated_proposal.json"


def setup_db(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "settings", SimpleNamespace(data_dir=tmp_path, db_path=tmp_path / "metadata.sqlite3"))
    database.initialize()
    with database.connect() as db:
        db.execute("INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,duration,status) VALUES(?,?,?,?,?,?,?,?)",
                   ("SIMULATED-video-001", "/library/fixture.mp4", "SIMULATED - bukan materi library nyata.mp4", 1, 0, "fixture", 300, "completed"))
        db.execute("INSERT INTO semantic_chunks(chunk_id,video_id,sequence_number,start_time,end_time,text,segmentation_version,source_transcript_reference) VALUES(?,?,?,?,?,?,?,?)",
                   ("SIMULATED-chunk-004", "SIMULATED-video-001", 4, 110, 180,
                    "Contoh simulasi: sebelum menasihati orang lain, periksa dulu niat dan cara kita menyampaikan nasihat itu.", "test", "simulated"))


def proposal():
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["created_at"] = datetime.now(timezone.utc).isoformat()
    return value


def test_persist_list_get_and_review_proposal(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    p = proposal()
    assert service.save_content_proposal(p)["status"] == "proposed"
    assert service.list_content_proposals(status="proposed")["total"] == 1
    assert service.get_content_proposal(p["proposal_id"])["transcript_excerpt"] == p["transcript_excerpt"]
    reviewed = service.update_proposal_review(p["proposal_id"], "approved", "Editor reviewed the simulation")
    assert reviewed["status"] == "approved"
    with pytest.raises(service.ProposalValidationError, match="final review"):
        service.update_proposal_review(p["proposal_id"], "rejected")


def test_duplicate_id_cannot_overwrite_review_feedback(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    p = proposal()
    service.save_content_proposal(p)
    service.update_proposal_review(p["proposal_id"], "needs_revision", "Keep the adjacent qualification")
    revised = proposal()
    revised["selection_reason"] = "Changed text"
    with pytest.raises(service.ProposalValidationError, match="prior review feedback is preserved"):
        service.save_content_proposal(revised)
    assert service.get_content_proposal(p["proposal_id"])["review_notes"] == "Keep the adjacent qualification"


def test_rejects_untraceable_source_chunk_and_nonverbatim_excerpt(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    p = proposal()
    p["source_chunk_ids"] = ["not-a-source-chunk"]
    with pytest.raises(service.ProposalValidationError, match="do not belong"):
        service.save_content_proposal(p)
    p = proposal()
    p["transcript_excerpt"] = "A made-up quote"
    with pytest.raises(service.ProposalValidationError, match="verbatim"):
        service.save_content_proposal(p)


def test_rejects_incomplete_video_and_invalid_review_decision(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with database.connect() as db:
        db.execute("UPDATE videos SET status='processing' WHERE video_id='SIMULATED-video-001'")
    with pytest.raises(service.ProposalValidationError, match="not completed"):
        service.save_content_proposal(proposal())
    with pytest.raises(service.ProposalValidationError, match="Decision must be"):
        service.update_proposal_review("missing", "maybe")
