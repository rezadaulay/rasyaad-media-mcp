"""CPU-only sample benchmark for faster-whisper; no library scanning is performed."""

import json
import resource
import time
from pathlib import Path

from faster_whisper import WhisperModel

source = Path("/input/Ust Joko.mp4")
output = Path("/output")
output.mkdir(parents=True, exist_ok=True)
if not source.is_file():
    raise FileNotFoundError(source)

model = WhisperModel(
    "small",
    device="cpu",
    compute_type="int8",
    cpu_threads=4,
    num_workers=1,
    download_root="/models",
)
started = time.perf_counter()
segments_iter, info = model.transcribe(
    str(source),
    language="id",
    beam_size=5,
    vad_filter=False,
    word_timestamps=False,
)
segments = list(segments_iter)
elapsed = time.perf_counter() - started
duration = float(info.duration)

lines: list[str] = []
for index, segment in enumerate(segments, start=1):
    start = max(0, int(segment.start * 1000))
    end = max(start, int(segment.end * 1000))

    def stamp(milliseconds: int) -> str:
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

    lines.extend([str(index), f"{stamp(start)} --> {stamp(end)}", segment.text.strip(), ""])

stem = "Ust Joko.small.int8"
(output / f"{stem}.srt").write_text("\n".join(lines), encoding="utf-8")
metrics = {
    "source": source.name,
    "model": "Systran/faster-whisper-small",
    "compute_type": "int8",
    "cpu_threads": 4,
    "beam_size": 5,
    "language_requested": "id",
    "language_detected": info.language,
    "language_probability": info.language_probability,
    "audio_duration_seconds": duration,
    "transcription_wall_seconds": elapsed,
    "real_time_factor": elapsed / duration if duration else None,
    "segment_count": len(segments),
    "peak_process_rss_gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024,
}
(output / f"{stem}.metrics.json").write_text(
    json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(metrics, ensure_ascii=False))
