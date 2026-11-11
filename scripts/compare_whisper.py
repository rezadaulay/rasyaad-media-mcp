"""Transcribe a prepared comparison clip with a CPU faster-whisper model."""

import argparse
import json
import resource
import time
from pathlib import Path

from faster_whisper import WhisperModel


parser = argparse.ArgumentParser()
parser.add_argument("--input", type=Path, default=Path("/input/clip.wav"))
parser.add_argument("--output-dir", type=Path, default=Path("/output"))
parser.add_argument("--model", default="large-v3")
parser.add_argument("--threads", type=int, default=4)
args = parser.parse_args()

args.output_dir.mkdir(parents=True, exist_ok=True)
model = WhisperModel(
    args.model,
    device="cpu",
    compute_type="int8",
    cpu_threads=args.threads,
    num_workers=1,
    download_root="/models",
)

started = time.perf_counter()
segments_iter, info = model.transcribe(
    str(args.input),
    language="id",
    beam_size=5,
    vad_filter=False,
    word_timestamps=False,
)
segments = list(segments_iter)
elapsed = time.perf_counter() - started


def stamp(seconds: float) -> str:
    millis = max(0, int(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


stem = f"UstJoko.first-180s.{args.model}.int8"
srt_lines: list[str] = []
text_lines: list[str] = []
for index, segment in enumerate(segments, start=1):
    body = segment.text.strip()
    text_lines.append(body)
    srt_lines.extend(
        [str(index), f"{stamp(segment.start)} --> {stamp(segment.end)}", body, ""]
    )

(args.output_dir / f"{stem}.srt").write_text("\n".join(srt_lines), encoding="utf-8")
(args.output_dir / f"{stem}.txt").write_text("\n".join(text_lines) + "\n", encoding="utf-8")
metrics = {
    "source": args.input.name,
    "model": f"Systran/faster-whisper-{args.model}",
    "compute_type": "int8",
    "cpu_threads": args.threads,
    "beam_size": 5,
    "language_requested": "id",
    "language_detected": info.language,
    "language_probability": info.language_probability,
    "audio_duration_seconds": float(info.duration),
    "transcription_wall_seconds": elapsed,
    "real_time_factor": elapsed / float(info.duration) if info.duration else None,
    "segment_count": len(segments),
    "peak_process_rss_gb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024,
}
(args.output_dir / f"{stem}.metrics.json").write_text(
    json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
print(json.dumps(metrics, ensure_ascii=False))
