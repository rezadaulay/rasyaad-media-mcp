# ASR Comparison: First Three Minutes

Date: November 11, 2026

## Method

The same 180-second excerpt was extracted from a sample video and converted to mono 16 kHz WAV. Transcription ran sequentially in CPU containers using four threads. Whisper used faster-whisper with INT8 and beam size 5. Qwen used Qwen3-ASR-1.7B BF16 on CPU. Transcription time excludes installation; Qwen's first-time setup time below includes downloading weights.

## Results

| Model | Transcription time for 3 minutes | RTF | Peak RAM | Target excerpt result |
|---|---:|---:|---:|---|
| faster-whisper `small` INT8 | 67 seconds | 0.37 | 1.25 GB | Captured most of the sequence, but Arabic transliteration still had errors. |
| faster-whisper `large-v3` INT8 | 174 seconds | 0.96 | 3.42 GB | Clearest result on the checked Arabic quotation. |
| Qwen3-ASR-1.7B BF16 CPU | 630 seconds | 3.50 | 5.67 GB | Misrecognized more of the mixed Arabic passage. |

All models identified the language as Indonesian. Qwen required an additional 420 seconds for first-time setup and initialization. A warm-cache setup would be shorter, but transcription itself was still much slower than Whisper on the tested CPU.

## Sample conclusion

For the tested computer and corrected phrase, **`large-v3` produced the most accurate text**, at about 2.6 times the processing time of `small` and about 3.4 GB RAM. `small` was faster and more memory-efficient, but more often missed Arabic terms and some names in this excerpt. Qwen 1.7B did not improve this excerpt and was too slow on the tested CPU. This is a qualitative review of one excerpt, not WER/CER; a complete human-verified reference transcript was unavailable.

Nemotron 3.5 was **not tested**: the host had no NVIDIA GPU, Docker/WSL did not expose NVIDIA acceleration, and the measured Docker VM capacity was about 7.7 GiB. No audio was sent to an external service. Nemotron benchmarking requires a supported NVIDIA device and runtime.

## Local benchmark artifacts

SRT, TXT, and metrics artifacts were stored in a local benchmark export directory and are intentionally excluded from this public repository. They contain environment-specific output and are not required to reproduce the documented setup.

Model cards: [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B), [Nemotron 3.5 Transcribe](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Transcribe-30B-A4B).
