from app.segmentation import make_chunks


def test_chunks_preserve_timestamps_order_and_neighbors(monkeypatch):
    import app.segmentation as module
    class Cfg: chunk_target_chars = 10
    monkeypatch.setattr(module, "settings", Cfg())
    segments = [
        {"sequence_number": 0, "start": 0.0, "end": 2.0, "text": "Kalimat satu."},
        {"sequence_number": 1, "start": 2.5, "end": 4.0, "text": "Kalimat dua."},
        {"sequence_number": 2, "start": 5.0, "end": 6.0, "text": "Kalimat tiga."},
    ]
    chunks = make_chunks(segments, "vid", "id")
    assert len(chunks) == 3
    assert [(c["start_time"], c["end_time"]) for c in chunks] == [(0, 2), (2.5, 4), (5, 6)]
    assert chunks[0]["next_chunk_id"] == chunks[1]["chunk_id"]
    assert chunks[1]["previous_chunk_id"] == chunks[0]["chunk_id"]
    assert chunks[2]["next_chunk_id"] is None


def test_chunk_ids_are_deterministic():
    values = [{"sequence_number": 0, "start": 12, "end": 15, "text": "Jaga lisan."}]
    assert make_chunks(values, "same", "id") == make_chunks(values, "same", "id")
