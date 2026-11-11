# Troubleshooting

- **Video remains `discovered`:** wait for two separate scans spaced by `STABLE_FILE_SECONDS`; confirm that modification time and size have stopped changing and that the folder is mounted.
- **`NoAudio`:** FFprobe found no audio stream; the job is marked `skipped`.
- **`Source file changed`:** the file changed after discovery. Let the scanner update its fingerprint before starting another job.
- **ASR failure or worker restart:** SQLite marks the job for retry. Partial JSON is an observability checkpoint only; ASR restarts from the beginning to avoid corrupt context.
- **Qdrant unavailable:** check `docker compose ps`, readiness, and logs; job retries use backoff.
- **Search returns 503:** the worker is running a heavy CPU model stage. Wait for that stage to finish; this avoids simultaneous model load.
- **Out of memory:** do not start another ingestion batch. Check `docker stats`, reduce `ASR_THREADS` or use `ASR_MODEL=small`, and reduce `EMBEDDING_BATCH_SIZE`. Re-evaluate quality before making a change the default.
- **Model download or disk space:** check free space on D: and `/data/models`; model files and cache should not be placed on C:.
- **MCP scan rejected:** confirm `INGESTION_API_TOKEN` matches in API and MCP configuration. Never put the token in logs.
- **FFprobe cannot read a file:** confirm the file plays and its codec/container is supported by FFmpeg. Record the filename and scanner event error. Do not delete status or database rows manually. Treat corrupt media as a discovery failure; escalate for scanner fixes if the status does not change.
- **Source moved or deleted:** restore the file to its original library location or scan after the move. A missing source does not automatically delete transcripts or metadata; check video status before relying on retrieval results.
- **Restoring a backup:** follow `operations.md`. Verify hashes before restore and stop the API/worker first. Restoring a Qdrant snapshot overwrites the target collection; verify the collection name before proceeding.

## Known verification gaps

- **Library mount unavailable:** the scanner rejects a scan before marking all sources missing. Recheck the host mount during operations.
- **Video without audio and duplicate copies:** discovery has unit coverage for these paths; this does not represent testing across all codec variations.
- **Worker restart:** job recovery and retries are available. Restart with an idle/completed worker was checked; a hard stop during active ASR has not been tested.
- **Qdrant unavailable, embedding failure, or low disk:** failure-injection drills have not confirmed retry, final status, and space recovery. Monitor logs, health, and free space; do not force new ingestion when capacity is critical.
- **Moved/deleted or corrupt source:** an end-to-end failure drill from API status through recovery has not been run. Confirm source availability and status before deleting related data.
