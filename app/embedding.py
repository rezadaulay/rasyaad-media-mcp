"""Lazy CPU embedding and versioned Qdrant collection helpers."""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from functools import lru_cache

from app.config import settings

log = logging.getLogger(__name__)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
_model_lock = threading.RLock()
_last_model_use = 0.0
_idle_timer: threading.Timer | None = None


@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    return SentenceTransformer(settings.embedding_model, device="cpu", cache_folder=str(settings.model_cache_dir))


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    global _last_model_use
    with _model_lock:
        vectors = model().encode(texts, batch_size=settings.embedding_batch_size, normalize_embeddings=True,
                                 show_progress_bar=False, convert_to_numpy=True)
        _last_model_use = time.monotonic()
        _schedule_idle_release_locked()
    if vectors.shape[1] != settings.embedding_dimension:
        raise ValueError(f"Embedding dimension mismatch: configured {settings.embedding_dimension}, got {vectors.shape[1]}")
    return vectors.tolist()


def embed_query(query: str) -> list[float]:
    instruction = "Instruct: Given a search query, retrieve relevant passages from Islamic sermon transcripts.\nQuery: " + query
    return embed_documents([instruction])[0]


def release_model() -> None:
    """Release the model immediately, used after worker indexing batches."""
    import gc
    global _idle_timer
    with _model_lock:
        if _idle_timer:
            _idle_timer.cancel()
            _idle_timer = None
        model.cache_clear()
        gc.collect()


def _schedule_idle_release_locked() -> None:
    global _idle_timer
    if _idle_timer:
        _idle_timer.cancel()
    timeout = max(0, settings.embedding_model_idle_seconds)
    _idle_timer = threading.Timer(timeout, _release_if_idle)
    _idle_timer.daemon = True
    _idle_timer.start()


def _release_if_idle() -> None:
    global _idle_timer
    import gc
    with _model_lock:
        elapsed = time.monotonic() - _last_model_use
        timeout = max(0, settings.embedding_model_idle_seconds)
        if elapsed < timeout:
            _idle_timer = threading.Timer(timeout - elapsed, _release_if_idle)
            _idle_timer.daemon = True
            _idle_timer.start()
            return
        _idle_timer = None
        model.cache_clear()
        gc.collect()


def collection_name() -> str:
    suffix = hashlib.sha1(f"{settings.embedding_model}|{settings.embedding_dimension}".encode()).hexdigest()[:8]
    return f"sermons_{suffix}"


def get_qdrant():
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=60)


def remove_video_points(video_id: str) -> None:
    """Remove stale vectors for a video from all engine-owned model versions."""
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    client=get_qdrant()
    for item in client.get_collections().collections:
        if item.name.startswith("sermons_"):
            client.delete(item.name,points_selector=Filter(must=[FieldCondition(key="video_id",match=MatchValue(value=video_id))]),wait=True)


def ensure_collection(client, name: str) -> None:
    from qdrant_client.models import Distance, VectorParams
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(collection_name=name, vectors_config=VectorParams(size=settings.embedding_dimension, distance=Distance.COSINE))
    info = client.get_collection(name)
    size = info.config.params.vectors.size
    if size != settings.embedding_dimension:
        raise ValueError(f"Qdrant collection {name} dimension {size} does not match configured dimension {settings.embedding_dimension}")
