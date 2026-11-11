"""Run a CPU comparison on the prepared clip with official Qwen3-ASR."""

import json
import resource
import time
from pathlib import Path

import torch
from qwen_asr import Qwen3ASRModel


source = Path("/input/clip.wav")
output = Path("/output")
output.mkdir(parents=True, exist_ok=True)
torch.set_num_threads(4)
load_started = time.perf_counter()
model = Qwen3ASRModel.from_pretrained(
    "Qwen/Qwen3-ASR-1.7B",
    dtype=torch.bfloat16,
    device_map="cpu",
    max_inference_batch_size=1,
    max_new_tokens=4096,
)
load_elapsed = time.perf_counter() - load_started

started = time.perf_counter()
result = model.transcribe(audio=str(source), language="Indonesian")
elapsed = time.perf_counter() - started
first = result[0]
transcript = first.text.strip()
duration = 180.0
stem = "UstJoko.first-180s.Qwen3-ASR-1.7B.cpu"
(output / f"{stem}.txt").write_text(transcript + "\n", encoding="utf-8")
metrics = {
    "source": source.name,
    "model": "Qwen/Qwen3-ASR-1.7B",
    "device": "cpu",
    "dtype": "bfloat16",
    "cpu_threads": 4,
    "language_requested": "Indonesian",
    "language_detected": getattr(first, "language", None),
    "audio_duration_seconds": duration,
    "model_init_and_first_download_seconds": load_elapsed,
    "transcription_wall_seconds": elapsed,
    "real_time_factor": elapsed / duration,
    "peak_process_rss_gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024,
}
(output / f"{stem}.metrics.json").write_text(
    json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(metrics, ensure_ascii=False))
