# Host Audit (Sanitized)

This note records the deployment characteristics relevant to the project. It intentionally omits personal drive paths, backup locations, machine identifiers, and source-media filenames.

| Component | Verified configuration |
|---|---|
| Operating system | Windows host using Docker Desktop and WSL2 Linux containers |
| CPU and memory | 6-core / 12-thread CPU; 16 GB host RAM |
| Docker resources | Linux VM exposes about 7.7 GiB RAM and 12 CPUs to containers |
| Container stack | Python 3.12, FFmpeg/FFprobe 5.1, faster-whisper 1.2, CPU-only PyTorch, Qdrant 1.15, Redis 7.4 |
| Data volumes | Source library is mounted read-only; application data is on a separate writable data volume |
| Index | One versioned Qdrant collection with eight vectors at dimension 1024 after the documented ingestion run |
| GPU | AMD GPU is present on the host but is not available to the current Docker/WSL pipeline; workloads use CPU |

## Operational limits

- The Docker VM has less available memory than the host. Recorded peak memory was about 3.5 GiB for ASR and about 4 GiB for embedding work.
- ASR accuracy and retrieval relevance have not been validated across a representative corpus. See the [Phase 2 report](phase-2-report.md).
- The source library and backup destinations are environment-specific and must be configured in local `.env`; those values are not part of the repository.
- The workspace was not a Git repository when this audit was written. No earlier Git history was available for comparison.
