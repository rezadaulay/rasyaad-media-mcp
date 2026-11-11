"""Deterministic timestamp-aware chunking; no video media is cut."""
from __future__ import annotations

import uuid
from typing import Any

from app.config import settings

SEGMENTATION_VERSION = "timestamp-sentence-v1"


def make_chunks(segments: list[dict[str, Any]], video_id: str, language: str | None) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    char_count = 0
    for seg in segments:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        # Prefer sentence boundaries, but enforce an upper bound for exceptionally long runs.
        if current and char_count >= settings.chunk_target_chars and current[-1]["text"].rstrip().endswith((".", "?", "!", "؟", "۔")):
            groups.append(current); current = []; char_count = 0
        current.append({**seg, "text": text})
        char_count += len(text) + 1
    if current:
        groups.append(current)
    rows: list[dict[str, Any]] = []
    for i, group in enumerate(groups):
        first, last = group[0], group[-1]
        body = " ".join(item["text"] for item in group)
        cid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{video_id}:{SEGMENTATION_VERSION}:{i}:{first['start']}:{last['end']}"))
        rows.append({"chunk_id": cid, "video_id": video_id, "sequence_number": i,
                     "start_time": float(first["start"]), "end_time": float(last["end"]),
                     "text": body, "language": language, "segmentation_version": SEGMENTATION_VERSION,
                     "source_transcript_reference": f"{video_id}#segments={first.get('sequence_number', i)}-{last.get('sequence_number', i)}"})
    for i, row in enumerate(rows):
        row["previous_chunk_id"] = rows[i-1]["chunk_id"] if i else None
        row["next_chunk_id"] = rows[i+1]["chunk_id"] if i+1 < len(rows) else None
    return rows
