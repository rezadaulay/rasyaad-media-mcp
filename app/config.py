"""Environment-backed configuration for the local MVP."""
from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _positive_int(name: str, default: int) -> int:
    value = _int(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


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
    arabic_coarse_window_seconds: float = _float("ARABIC_COARSE_WINDOW_SECONDS", 12.0)
    arabic_coarse_stride_seconds: float = _float("ARABIC_COARSE_STRIDE_SECONDS", 6.0)
    arabic_fine_window_seconds: float = _float("ARABIC_FINE_WINDOW_SECONDS", 5.0)
    arabic_fine_stride_seconds: float = _float("ARABIC_FINE_STRIDE_SECONDS", 2.5)
    arabic_coarse_threshold: float = _float("ARABIC_COARSE_THRESHOLD", 0.01)
    arabic_fine_threshold: float = _float("ARABIC_FINE_THRESHOLD", 0.2)
    arabic_transcription_context_seconds: float = _float("ARABIC_TRANSCRIPTION_CONTEXT_SECONDS", 5.0)
    embedding_batch_size: int = _int("EMBEDDING_BATCH_SIZE", 2)
    scan_interval_seconds: int = _int("SCAN_INTERVAL_SECONDS", 300)
    stable_file_seconds: int = _int("STABLE_FILE_SECONDS", 60)
    clip_retention_hours: int = _positive_int("CLIP_RETENTION_HOURS", 48)
    clip_cleanup_interval_seconds: int = _positive_int("CLIP_CLEANUP_INTERVAL_SECONDS", 3600)
    retry_limit: int = _int("JOB_RETRY_LIMIT", 3)
    chunk_target_chars: int = _int("CHUNK_TARGET_CHARS", 1200)
    chunk_overlap_segments: int = _int("CHUNK_OVERLAP_SEGMENTS", 1)
    api_token: str = os.getenv("INGESTION_API_TOKEN", "")
    model_cache_dir: Path = Path(os.getenv("MODEL_CACHE_DIR", str(Path(os.getenv("APP_DATA_DIR", "/data")) / "models")))


settings = Settings()
