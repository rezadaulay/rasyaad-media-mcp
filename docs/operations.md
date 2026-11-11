# Operations

## Health checks

```powershell
docker compose config --quiet
docker compose ps
docker compose logs --tail 100 qdrant redis api worker
docker stats --no-stream
Invoke-RestMethod http://localhost:8000/health/live
```

## Backup

The local deployment uses a weekly scheduled backup task when the operator's user session is active. Confirm Docker Desktop and the Compose stack are running. The backup script pauses the worker, snapshots each Qdrant collection, copies SQLite metadata through the backup API, saves transcript JSON and non-secret configuration, and writes a manifest with checksums. It does not include source videos or `.env` secrets. Do not copy live Qdrant storage files as a substitute for snapshots.

Backups are written to timestamped directories and do not have automatic retention. Monitor the destination disk and keep an additional copy on a separate device or offsite location.

Qdrant's health check verifies its executable because the upstream image is minimal. API readiness queries Qdrant with its API key, pings Redis, and reads SQLite. A Phase 2 restore drill recovered an eight-point snapshot into a temporary collection and removed the test collection afterward. The SQLite copy passed `integrity_check` with one video, 284 transcript segments, and eight chunks.

Run a manual backup with:

```powershell
./scripts/backup.ps1
```

## Restore from backup

Restore only after confirming that the selected backup contains metadata, transcripts, and snapshots for the same collection. Restoration temporarily stops access. Recovering a Qdrant snapshot into a collection with the same name replaces that collection's contents.

1. Select a timestamped backup directory. Check `manifest.json` and verify every hash in `sha256.csv`. Stop if any file is missing or a hash differs.
2. Confirm that the source videos remain available in their original library location. Source media is not included in application backups.
3. Save a copy of the current data as a precaution. Confirm Compose is running, then stop services that read or write the data:

   ```powershell
   docker compose stop mcp api worker
   ```

4. Restore `metadata.sqlite3` to the path configured by `APP_DATA_DIR` in `.env`; restore the `transcripts` folder to the same data directory. Do not copy SQLite files while a service is running.
5. For each snapshot under `qdrant-snapshots/<collection-name>`, copy the snapshot file into the matching collection snapshot directory inside the Qdrant container. The collection name must match the manifest. Find the container with `docker compose ps -q qdrant`, then use `docker cp <snapshot-file> <container>:/qdrant/snapshots/<collection-name>/`.
6. Recover the snapshot through the Qdrant API `PUT /collections/<collection-name>/snapshots/recover` with JSON body `{"location":"file:///qdrant/snapshots/<collection-name>/<snapshot-file>"}`. Include the Qdrant API key in the `api-key` header. This replaces the target collection. Verify the collection and snapshot names before proceeding. See [Qdrant snapshot recovery](https://qdrant.tech/documentation/concepts/snapshots/#recover-via-api).

   Example from the API container (replace the example values only after checking the manifest and copied file):

   ```powershell
   docker compose exec api python -c "import json,os,urllib.request; c='sermons_COLLECTION'; loc='file:///qdrant/snapshots/sermons_COLLECTION/SNAPSHOT_FILE'; req=urllib.request.Request('http://qdrant:6333/collections/'+c+'/snapshots/recover',data=json.dumps({'location':loc}).encode(),headers={'api-key':os.environ['QDRANT_API_KEY'],'Content-Type':'application/json'},method='PUT'); print(urllib.request.urlopen(req,timeout=300).read().decode())"
   ```

7. Restart services and verify readiness and restored data:

   ```powershell
   docker compose start api worker
   docker compose --profile mcp start mcp
   Invoke-RestMethod http://localhost:8000/health/ready
   docker compose exec worker python -m app status
   ```

   Compare video, transcript, chunk, and vector counts with the manifest or backup notes. Run one search and inspect its source video and timestamps. If verification fails, stop the worker and API before retrying the restore or returning to the saved copy from step 3.

The recorded restore drill verifies a SQLite copy and Qdrant recovery into a test collection only. The full-stack procedure above is operational guidance and has not been exercised as a complete disaster recovery. Test it in a copy of the environment or a test collection before relying on it.

## Capacity

Start with worker concurrency 1 and limits of 4 CPUs / 5 GB RAM. Keep free space on the system drive and monitor the data drive for Docker data, models, and media work. A backup on one local disk still needs another copy to mitigate disk failure.
