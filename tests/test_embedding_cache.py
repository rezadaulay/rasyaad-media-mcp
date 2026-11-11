import threading
from types import SimpleNamespace

from app import embedding


def test_query_model_is_released_after_idle_timeout(monkeypatch):
    class FakeModel:
        def encode(self, texts, **kwargs):
            return SimpleNamespace(shape=(len(texts), 2), tolist=lambda: [[1.0, 0.0] for _ in texts])

    monkeypatch.setattr(embedding, "settings", SimpleNamespace(
        embedding_batch_size=1,
        embedding_dimension=2,
        embedding_model_idle_seconds=0.1,
    ))
    released = threading.Event()

    def factory():
        return FakeModel()

    factory.cache_clear = released.set
    monkeypatch.setattr(embedding, "model", factory)

    assert embedding.embed_documents(["query"]) == [[1.0, 0.0]]
    assert released.wait(2)
