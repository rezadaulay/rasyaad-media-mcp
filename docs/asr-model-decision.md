# ASR Model Decision

Date: November 10, 2026

## Decision

The target ASR model selected for a future implementation stage is **NVIDIA Nemotron 3.5 Transcribe** (`nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B`). This is a target decision, not a claim that the model has been installed or run.

## Rationale

- The model supports Indonesian and Arabic and lists code-switching for both languages in its official matrix.
- It supports contextual transcription and word-level timestamps; vocabulary context may help with religious terminology and speaker names.
- The official model card reports mean WER 4.62 on the Multilingual Open ASR Leaderboard and mean WER 10.98 for the long-form track. These general benchmark scores do not directly predict accuracy on Indonesian-Arabic sermons.
- The architecture is speech-specific, with a 34B total / about 4.3B active MoE backbone, rather than a general text LLM adapted for transcription.

Primary source: [NVIDIA model card, language matrix, deployment requirements, and evaluation results](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B).

## Hardware and license limits

- The tested host (Ryzen 5 3600, 16 GB RAM, Radeon RX 580 4 GB) does not meet the listed reference configuration. The model is optimized for NVIDIA GPUs; the deployment reference calls for 1x H100 80 GB. Do not download large weights or benchmark it on that host.
- FP8 and NVFP4 variants exist, but do not assume quantized variants will run on consumer GPUs without checking runtime, VRAM, quality, and kernel support.
- The model license is **OpenMDW-1.1**, not Apache-2.0 or MIT. Review its terms before commercial use or redistribution.
- The project has not activated an ASR pipeline at this decision point; the worker was idle and no library was scanned.

## Acceptance plan before production

Run Nemotron, Qwen3-ASR-1.7B, and faster-whisper `large-v3` on the same excerpt after suitable hardware is available. Prepare human references for clean, noisy, and Indonesian-Arabic samples. Evaluate WER/CER, religious term accuracy, repetitions or hallucinations, timestamps, processing time, VRAM/RAM, and license requirements. Select a production model based on the project's sermon audio; public benchmarks do not replace corpus evaluation.

## Initial local comparison

The first 180 seconds of the benchmark sample showed that faster-whisper `large-v3` INT8 performed best qualitatively on a hadith quotation around 01:30–01:38. It took 174 seconds and peaked at 3.42 GB RAM. faster-whisper `small` finished in 67 seconds / 1.25 GB but had more quotation errors. Qwen3-ASR-1.7B BF16 on CPU had more errors and took 630 seconds / 5.67 GB. Nemotron was not tested because the host lacked an NVIDIA GPU. See `docs/asr-comparison-first-180s.md` for details and limitations.
