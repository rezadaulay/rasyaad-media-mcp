from types import SimpleNamespace

import pytest

from app import database, discovery


def test_content_fingerprint_matches_identical_copies(tmp_path):
    first=tmp_path/"one.mp4"; second=tmp_path/"copy.mp4"
    payload=b"audio-video-sample"*100000
    first.write_bytes(payload); second.write_bytes(payload)
    assert discovery.content_fingerprint(first)==discovery.content_fingerprint(second)
    assert discovery.fingerprint(first)!=discovery.fingerprint(second)


def test_video_identifier_is_stable_and_root_relative(monkeypatch,tmp_path):
    monkeypatch.setattr(discovery,"settings",SimpleNamespace(library_root=tmp_path))
    path=tmp_path/"sub"/"sermon.mp4"; path.parent.mkdir(); path.write_bytes(b"video")
    assert discovery.video_id_for(path)==discovery.video_id_for(path)


def test_scan_queues_one_copy_and_skips_identical_duplicate(monkeypatch,tmp_path):
    root=tmp_path/"library"; root.mkdir()
    data=tmp_path/"data"
    cfg=SimpleNamespace(library_root=root,data_dir=data,db_path=data/"metadata.sqlite3",stable_file_seconds=0)
    monkeypatch.setattr(database,"settings",SimpleNamespace(data_dir=data,db_path=data/"metadata.sqlite3",retry_limit=3))
    monkeypatch.setattr(discovery,"settings",cfg)
    (root/"a.mp4").write_bytes(b"same-content"*1000)
    (root/"b.mp4").write_bytes(b"same-content"*1000)
    monkeypatch.setattr(discovery,"probe",lambda path:{"duration":60.0,"width":1280,"height":720,"video_codec":"h264","audio_codec":"aac","has_audio":1,"container":"mov,mp4"})
    database.initialize()
    discovery.scan_library()  # first stable observation
    result=discovery.scan_library()
    assert result["queued"]==1
    with database.connect() as db:
        rows=db.execute("SELECT status,duplicate_of FROM videos ORDER BY file_name").fetchall()
        jobs=db.execute("SELECT COUNT(*) FROM ingestion_jobs WHERE status='pending'").fetchone()[0]
    pending=[r for r in rows if r["status"]=="pending"]
    skipped=[r for r in rows if r["status"]=="skipped"]
    assert len(pending)==1 and len(skipped)==1
    assert skipped[0]["duplicate_of"] is not None
    assert jobs==1


def test_missing_library_mount_does_not_mark_existing_sources_missing(monkeypatch,tmp_path):
    data=tmp_path/"data"
    missing_root=tmp_path/"unmounted-library"
    monkeypatch.setattr(database,"settings",SimpleNamespace(data_dir=data,db_path=data/"metadata.sqlite3",retry_limit=3))
    monkeypatch.setattr(discovery,"settings",SimpleNamespace(library_root=missing_root,data_dir=data,db_path=data/"metadata.sqlite3",stable_file_seconds=0))
    database.initialize()
    with database.connect() as db:
        db.execute("INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,status) VALUES('v','/library/sermon.mp4','sermon.mp4',10,0,'f','completed')")

    with pytest.raises(FileNotFoundError,match="not mounted"):
        discovery.scan_library()

    with database.connect() as db:
        assert db.execute("SELECT status FROM videos WHERE video_id='v'").fetchone()[0]=="completed"
