"""Create Qdrant snapshots and a consistent SQLite metadata backup."""

import json
import os
import shutil
import sqlite3
from pathlib import Path

from qdrant_client import QdrantClient

client = QdrantClient(
    url=os.environ["QDRANT_URL"],
    api_key=os.environ["QDRANT_API_KEY"],
    timeout=30,
)
snapshots: list[dict[str, str]] = []
for collection in client.get_collections().collections:
    snapshot = client.create_snapshot(collection.name)
    snapshots.append({"collection": collection.name, "name": snapshot.name})

data_dir = Path(os.environ.get("APP_DATA_DIR", "/data"))
staging = data_dir / "backup-staging"
staging.mkdir(parents=True, exist_ok=True)
source_db = Path(os.environ.get("METADATA_DB", str(data_dir / "metadata.sqlite3")))
if source_db.exists():
    source = sqlite3.connect(source_db)
    target_db = sqlite3.connect(staging / "metadata.sqlite3")
    try:
        source.backup(target_db)
    finally:
        source.close()
        target_db.close()
transcripts = data_dir / "transcripts"
target_transcripts = staging / "transcripts"
if target_transcripts.exists():
    shutil.rmtree(target_transcripts)
if transcripts.exists():
    shutil.copytree(transcripts, target_transcripts)
print(json.dumps({"qdrant_snapshots": snapshots, "metadata_backup": str(staging / "metadata.sqlite3") if source_db.exists() else None,
                  "transcripts_backup": str(target_transcripts) if transcripts.exists() else None}))
