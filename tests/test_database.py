from types import SimpleNamespace

from app import database


def setup_db(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path, db_path=tmp_path / "metadata.sqlite3")
    monkeypatch.setattr(database, "settings", cfg)
    database.initialize()
    return cfg


def test_claim_is_persistent_and_single(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with database.connect() as db:
        db.execute("INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,status) VALUES('v','/lib/v.mp4','v.mp4',1,0,'f','pending')")
        db.execute("INSERT INTO ingestion_jobs(job_id,video_id,status) VALUES('j','v','pending')")
    job = database.claim_job()
    assert job["status"] == "processing"
    assert database.claim_job() is None
    with database.connect() as db:
        assert db.execute("SELECT status FROM videos WHERE video_id='v'").fetchone()[0] == "processing"


def test_job_failure_has_bounded_retry_state(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    class Cfg: retry_limit = 2
    monkeypatch.setattr(database, "settings", SimpleNamespace(data_dir=tmp_path, db_path=tmp_path / "metadata.sqlite3", retry_limit=2))
    with database.connect() as db:
        db.execute("INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,status) VALUES('v','/lib/v.mp4','v.mp4',1,0,'f','processing')")
        db.execute("INSERT INTO ingestion_jobs(job_id,video_id,status) VALUES('j','v','processing')")
    database.finish_job("j", "v", "failed", ValueError("sample"))
    with database.connect() as db:
        row = db.execute("SELECT status,retry_count,error_type FROM ingestion_jobs WHERE job_id='j'").fetchone()
    assert tuple(row) == ("retry_pending", 1, "ValueError")


def test_schema_contains_fts_and_dedup_columns(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with database.connect() as db:
        video_columns={r[1] for r in db.execute("pragma table_info(videos)")}
        tables={r[0] for r in db.execute("select name from sqlite_master")}
    assert {"content_fingerprint","sha256","duplicate_of"} <= video_columns
    assert {"transcript_fts","chunks_fts"} <= tables


def test_initialize_versions_new_database_and_is_idempotent(monkeypatch, tmp_path):
    setup_db(monkeypatch, tmp_path)
    with database.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    database.initialize()
    with database.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION


def test_initialize_adopts_existing_unversioned_database_without_data_loss(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path, db_path=tmp_path / "metadata.sqlite3")
    monkeypatch.setattr(database, "settings", cfg)
    # Simulate the pre-migration schema: the baseline exists but has no
    # user_version marker. Initialize again must preserve the row.
    with database.connect() as db:
        db.executescript(database.SCHEMA)
        db.execute("INSERT INTO videos(video_id,path,file_name,size_bytes,mtime,fingerprint,status) VALUES('old','/lib/old.mp4','old.mp4',1,0,'f','completed')")
    database.initialize()
    with database.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
        row = db.execute("SELECT video_id,status FROM videos WHERE video_id='old'").fetchone()
        assert tuple(row) == ("old", "completed")


def test_initialize_rejects_database_from_newer_schema(monkeypatch, tmp_path):
    cfg = SimpleNamespace(data_dir=tmp_path, db_path=tmp_path / "metadata.sqlite3")
    monkeypatch.setattr(database, "settings", cfg)
    with database.connect() as db:
        db.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")
    import pytest
    with pytest.raises(RuntimeError, match="newer than this application supports"):
        database.initialize()
