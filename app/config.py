"""Environment-backed configuration for the local MVP."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path(os.getenv("APP_DATA_DIR", "/data"))
    library_root: Path = Path(os.getenv("LIBRARY_ROOT", "/library"))
    db_path: Path = Path(os.getenv("METADATA_DB", str(Path(os.getenv("APP_DATA_DIR", "/data")) / "metadata.sqlite3")))
    qdrant_url: str = os.getenv("QDRANT_URL", "http://qdrant:6333")
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
    embedding_dimension: int = _int("EMBEDDING_DIMENSION", 1024)
    embedding_model_idle_seconds: int = _int("EMBEDDING_MODEL_IDLE_SECONDS", 600)
    asr_model: str = os.getenv("ASR_MODEL", "large-v3")
    asr_language: str = os.getenv("ASR_LANGUAGE", "id")
    asr_compute_type: str = os.getenv("ASR_COMPUTE_TYPE", "int8")
    asr_threads: int = _int("ASR_THREADS", 4)
    embedding_batch_size: int = _int("EMBEDDING_BATCH_SIZE", 2)
    scan_interval_seconds: int = _int("SCAN_INTERVAL_SECONDS", 300)
    stable_file_seconds: int = _int("STABLE_FILE_SECONDS", 60)
    retry_limit: int = _int("JOB_RETRY_LIMIT", 3)
    chunk_target_chars: int = _int("CHUNK_TARGET_CHARS", 1200)
    chunk_overlap_segments: int = _int("CHUNK_OVERLAP_SEGMENTS", 1)
    api_token: str = os.getenv("INGESTION_API_TOKEN", "")
    model_cache_dir: Path = Path(os.getenv("MODEL_CACHE_DIR", str(Path(os.getenv("APP_DATA_DIR", "/data")) / "models")))


settings = Settings()
