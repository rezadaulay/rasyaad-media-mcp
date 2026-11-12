"""Single-job-at-a-time local ingestion pipeline."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import unicodedata
from pathlib import Path

from app.config import settings
from app.database import connect, event, finish_clip_job, finish_job, set_stage
from app.discovery import fingerprint, content_fingerprint, resolve_library_source
from app.segmentation import SEGMENTATION_VERSION, make_chunks

log = logging.getLogger("dakwah.pipeline")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{milliseconds:03}"


def _clip_srt_text(video_id: str, start_time: float, end_time: float) -> tuple[str, int]:
    """Build sidecar subtitles from saved transcript cues, rebased to clip time zero."""
    with connect() as db:
        rows = db.execute(
            "SELECT start_time,end_time,text FROM transcript_segments "
            "WHERE video_id=? AND end_time>? AND start_time<? ORDER BY start_time,sequence_number",
            (video_id, start_time, end_time),
        ).fetchall()

    cues = []
    for row in rows:
        text = " ".join(str(row["text"]).split())
        cue_start = max(float(row["start_time"]), start_time) - start_time
        cue_end = min(float(row["end_time"]), end_time) - start_time
        if not text or cue_end <= cue_start:
            continue
        cues.append((cue_start, cue_end, text))

    blocks = [
        f"{index}\n{_srt_timestamp(cue_start)} --> {_srt_timestamp(cue_end)}\n{text}"
        for index, (cue_start, cue_end, text) in enumerate(cues, start=1)
    ]
    return ("\n\n".join(blocks) + ("\n" if blocks else ""), len(cues))


def _has_arabic_script(text: str) -> bool:
    return any(
        "\u0600" <= char <= "\u06ff"
        or "\ufb50" <= char <= "\ufdff"
        or "\ufe70" <= char <= "\ufeff"
        for char in text
    )


_ARABIC_WORDS = re.compile(
    r"[\u0621-\u064a\u064b-\u065f\u066e-\u06ed\u06fa-\u06fc\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]+"
)


def _normalize_arabic_word(word: str) -> str:
    decomposed = unicodedata.normalize("NFD", word)
    return "".join(
        char for char in decomposed
        if unicodedata.category(char) != "Mn" and char != "ـ"
    )


def _correct_arabic_spelling(text: str) -> tuple[str, list[dict[str, str]]]:
    """Apply only a validated, context-specific Arabic ASR spelling correction."""
    tokens = [
        (match.start(), match.end(), _normalize_arabic_word(match.group()))
        for match in _ARABIC_WORDS.finditer(text)
    ]
    expected_context = ["لا", "ينقس", "من", "اجر", "الصايم"]
    for index in range(len(tokens) - len(expected_context) + 1):
        window = tokens[index:index + len(expected_context)]
        if [token[2] for token in window] != expected_context:
            continue

        word_start, word_end, _ = window[1]
        original_word = text[word_start:word_end]
        if "س" not in original_word:
            continue
        corrected_word = original_word.replace("س", "ص", 1)
        corrected_text = text[:word_start] + corrected_word + text[word_end:]
        correction = {
            "rule": "la-yanqusu-min-ajr-as-saim-v1",
            "original": original_word,
            "corrected": corrected_word,
            "context": "لا ينقس من أجر الصائم",
        }
        return corrected_text, [correction]
    return text, []


def _merge_time_ranges(ranges: list[list[float]], max_gap: float = 0.1) -> list[list[float]]:
    merged: list[list[float]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + max_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _arabic_srt_text(model, audio, sample_rate: int = 16000, progress_callback=None) -> tuple[str, int, list[dict[str, str]]]:
    """Coarse-to-fine Arabic detection followed by native-script Arabic transcription."""
    import math

    total_samples = len(audio)
    duration = total_samples / sample_rate
    coarse_window = max(4.0, settings.arabic_coarse_window_seconds)
    coarse_stride = max(1.0, min(coarse_window, settings.arabic_coarse_stride_seconds))
    fine_window = max(2.0, settings.arabic_fine_window_seconds)
    fine_stride = max(0.5, min(fine_window, settings.arabic_fine_stride_seconds))
    coarse_threshold = min(1.0, max(0.0, settings.arabic_coarse_threshold))
    fine_threshold = min(1.0, max(0.0, settings.arabic_fine_threshold))
    transcription_context = min(30.0, max(0.0, settings.arabic_transcription_context_seconds))

    def windows(start_time: float, end_time: float, window_seconds: float, stride_seconds: float):
        start_sample = max(0, int(start_time * sample_rate))
        end_limit = min(total_samples, int(end_time * sample_rate))
        window_samples = max(sample_rate, int(window_seconds * sample_rate))
        stride_samples = max(1, int(stride_seconds * sample_rate))
        available_samples = end_limit - start_sample
        if available_samples < sample_rate:
            return []
        if available_samples <= window_samples:
            return [(start_sample, end_limit)]

        last_start = end_limit - window_samples
        offsets = list(range(start_sample, last_start + 1, stride_samples))
        # Shift the final window to the end so every sample is covered without
        # adding a short, nearly duplicate tail window.
        if offsets[-1] < last_start:
            offsets.append(last_start)
        return [(offset, offset + window_samples) for offset in offsets]

    def arabic_probability(detection) -> float:
        language, probability, all_probabilities = detection
        for candidate, candidate_probability in all_probabilities:
            if candidate == "ar":
                return float(candidate_probability)
        return float(probability) if language == "ar" else 0.0

    coarse_windows = windows(0.0, duration, coarse_window, coarse_stride)
    coarse_ranges = []
    for index, (start_sample, end_sample) in enumerate(coarse_windows, start=1):
        detection = model.detect_language(
            audio=audio[start_sample:end_sample], language_detection_threshold=0.5,
        )
        if arabic_probability(detection) >= coarse_threshold:
            coarse_ranges.append((start_sample / sample_rate, end_sample / sample_rate))
        if progress_callback:
            progress_callback("coarse_detection", index, len(coarse_windows))

    coarse_ranges = _merge_time_ranges([list(item) for item in coarse_ranges], max_gap=coarse_stride)
    fine_windows = []
    for range_start, range_end in coarse_ranges:
        expanded_start = max(0.0, range_start - fine_stride)
        expanded_end = min(duration, range_end + fine_stride)
        # Anchor refinement windows to clip time zero. Starting the grid at each
        # candidate boundary can miss short speech that falls between windows.
        aligned_start = math.floor(expanded_start / fine_stride) * fine_stride
        fine_windows.extend(windows(aligned_start, expanded_end, fine_window, fine_stride))
    # Coarse ranges can overlap around adjacent candidates; do not repeat model inference.
    fine_windows = sorted(set(fine_windows))

    arabic_ranges = []
    for index, (start_sample, end_sample) in enumerate(fine_windows, start=1):
        detection = model.detect_language(
            audio=audio[start_sample:end_sample], language_detection_threshold=0.5,
        )
        if arabic_probability(detection) >= fine_threshold:
            arabic_ranges.append((start_sample / sample_rate, end_sample / sample_rate))
        if progress_callback:
            progress_callback("fine_detection", index, len(fine_windows))
    arabic_ranges = _merge_time_ranges([list(item) for item in arabic_ranges], max_gap=fine_stride)

    cues: list[tuple[float, float, str]] = []
    corrections: list[dict[str, str]] = []
    for index, (range_start, range_end) in enumerate(arabic_ranges, start=1):
        padded_start = max(0.0, range_start - transcription_context)
        padded_end = min(duration, range_end + transcription_context)
        audio_start = int(padded_start * sample_rate)
        audio_end = min(total_samples, math.ceil(padded_end * sample_rate))
        segments, _ = model.transcribe(
            audio[audio_start:audio_end], language="ar", task="transcribe", beam_size=5,
            vad_filter=False, condition_on_previous_text=False, word_timestamps=False,
        )
        for segment in segments:
            text = " ".join(str(segment.text).split())
            if (not text or not _has_arabic_script(text)
                    or float(getattr(segment, "no_speech_prob", 0.0)) > 0.6
                    or float(getattr(segment, "avg_logprob", 0.0)) < -1.5):
                continue
            cue_start = max(0.0, min(duration, padded_start + float(segment.start)))
            cue_end = max(0.0, min(duration, padded_start + float(segment.end)))
            if cue_end > cue_start:
                text, segment_corrections = _correct_arabic_spelling(text)
                for correction in segment_corrections:
                    corrections.append({
                        **correction,
                        "cue_start": _srt_timestamp(cue_start),
                        "cue_end": _srt_timestamp(cue_end),
                    })
                cues.append((cue_start, cue_end, text))
        if progress_callback:
            progress_callback("arabic_transcription", index, len(arabic_ranges))

    blocks = [
        f"{index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}"
        for index, (start, end, text) in enumerate(cues, start=1)
    ]
    return ("\n\n".join(blocks) + ("\n" if blocks else ""), len(cues), corrections)


def _generate_arabic_srt(audio_path: Path, output_path: Path, progress_callback=None) -> tuple[int, list[dict[str, str]]]:
    """Run the local multilingual ASR on a rendered clip and write Arabic-only cues."""
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio

    audio = decode_audio(str(audio_path), sampling_rate=16000)
    model = WhisperModel(
        settings.asr_model, device="cpu", compute_type=settings.asr_compute_type,
        cpu_threads=settings.asr_threads, num_workers=1,
        download_root=str(settings.model_cache_dir),
    )
    try:
        subtitle_text, cue_count, corrections = _arabic_srt_text(
            model, audio, progress_callback=progress_callback,
        )
        output_path.write_text(subtitle_text, encoding="utf-8", newline="\n")
        return cue_count, corrections
    finally:
        del model


def render_clip_job(job) -> None:
    """Render an approved proposal to a new MP4 without modifying its source."""
    import subprocess

    output_dir = settings.data_dir / "clips"
    temp_path = None
    try:
        checkpoint = json.loads(job["checkpoint"])
        source = resolve_library_source(checkpoint["source_path"])
        output_dir.mkdir(parents=True, exist_ok=True)
        start_time = float(checkpoint["start_time"])
        duration = float(checkpoint["end_time"]) - start_time
        render_preset = checkpoint.get("render_preset", "original")
        if render_preset not in {"original", "vertical_9_16"}:
            raise RuntimeError("Stored clip render preset is invalid")
        if start_time < 0 or duration <= 0 or duration > 600:
            raise RuntimeError("Stored proposal time range is invalid")
    except Exception as exc:
        log.exception("Clip job data is invalid job_id=%s", job["job_id"])
        finish_clip_job(job["job_id"], "failed", exc)
        return
    output_path = output_dir / f"{job['job_id']}.mp4"
    temp_path = output_dir / f"{job['job_id']}.rendering.mp4"
    subtitle_path = output_dir / f"{job['job_id']}.srt"
    subtitle_temp_path = output_dir / f"{job['job_id']}.rendering.srt"
    arabic_subtitle_path = output_dir / f"{job['job_id']}.arabic.srt"
    arabic_subtitle_temp_path = output_dir / f"{job['job_id']}.rendering.arabic.srt"
    audio_temp_path = settings.data_dir / "temporary" / f"{job['job_id']}.arabic.wav"
    try:
        if (fingerprint(source) != checkpoint["source_fingerprint"] or
                content_fingerprint(source) != checkpoint["source_content_fingerprint"]):
            raise RuntimeError("Source video changed after the render request")
        set_stage(job["job_id"], "rendering", 0.05)
        render_args = []
        if render_preset == "vertical_9_16":
            render_args = [
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920",
            ]
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
            "-ss", f"{start_time:.3f}", "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "0:a?", *render_args,
            "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(temp_path),
        ], check=True, timeout=max(300, int(duration * 10)))
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
            "-of", "json", str(temp_path),
        ], check=True, capture_output=True, text=True, timeout=30)
        media = json.loads(probe.stdout)
        video_stream = next((stream for stream in media.get("streams", []) if stream.get("codec_type") == "video"), None)
        if video_stream is None:
            raise RuntimeError("FFmpeg output does not contain a video stream")
        has_audio = any(stream.get("codec_type") == "audio" for stream in media.get("streams", []))
        output_width = int(video_stream.get("width") or 0)
        output_height = int(video_stream.get("height") or 0)
        if render_preset == "vertical_9_16" and (output_width, output_height) != (1080, 1920):
            raise RuntimeError("Vertical clip output must be exactly 1080x1920")
        rendered_duration = float(media.get("format", {}).get("duration") or 0)
        if rendered_duration <= 0 or abs(rendered_duration - duration) > 1.0:
            raise RuntimeError("Rendered clip duration does not match the approved time range")
        if (fingerprint(source) != checkpoint["source_fingerprint"] or
                content_fingerprint(source) != checkpoint["source_content_fingerprint"]):
            raise RuntimeError("Source video changed during rendering")
        os.replace(temp_path, output_path)
        set_stage(job["job_id"], "indonesian_subtitles", 0.82)
        subtitle_text, subtitle_cue_count = _clip_srt_text(job["video_id"], start_time, start_time + duration)
        subtitle_temp_path.write_text(subtitle_text, encoding="utf-8", newline="\n")

        set_stage(job["job_id"], "arabic_subtitles", 0.85)
        audio_temp_path.parent.mkdir(parents=True, exist_ok=True)
        if has_audio:
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(output_path),
                "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                str(audio_temp_path),
            ], check=True, timeout=max(120, int(duration * 4)))

            def report_arabic_progress(phase: str, completed: int, total: int) -> None:
                if phase == "coarse_detection":
                    stage_progress = 0.85 + 0.05 * completed / max(1, total)
                elif phase == "fine_detection":
                    stage_progress = 0.90 + 0.05 * completed / max(1, total)
                else:
                    stage_progress = 0.95 + 0.03 * completed / max(1, total)
                set_stage(job["job_id"], "arabic_subtitles", stage_progress, {
                    "arabic_detection": {"phase": phase, "completed": completed, "total": total},
                })
                if completed == 1 or completed == total or completed % 5 == 0:
                    log.info("Arabic subtitle progress job_id=%s phase=%s progress=%d/%d",
                             job["job_id"], phase, completed, total)

            arabic_subtitle_cue_count, arabic_corrections = _generate_arabic_srt(
                audio_temp_path, arabic_subtitle_temp_path, progress_callback=report_arabic_progress,
            )
        else:
            arabic_subtitle_cue_count = 0
            arabic_corrections = []
            arabic_subtitle_temp_path.write_text("", encoding="utf-8")

        os.replace(subtitle_temp_path, subtitle_path)
        os.replace(arabic_subtitle_temp_path, arabic_subtitle_path)
        set_stage(job["job_id"], "completed", 1, {
            "output_path": str(output_path), "duration": rendered_duration,
            "output_width": output_width, "output_height": output_height,
            "subtitle_path": str(subtitle_path), "subtitle_cue_count": subtitle_cue_count,
            "subtitle_ar_path": str(arabic_subtitle_path),
            "subtitle_ar_cue_count": arabic_subtitle_cue_count,
            "arabic_corrections": arabic_corrections,
        })
        finish_clip_job(job["job_id"], "completed")
        event("Approved clip rendered", video_id=job["video_id"], job_id=job["job_id"], stage="completed",
              details={"proposal_id": job["proposal_id"], "duration": rendered_duration,
                       "render_preset": render_preset, "width": output_width, "height": output_height,
                       "subtitle_cue_count": subtitle_cue_count,
                       "subtitle_ar_cue_count": arabic_subtitle_cue_count,
                       "arabic_correction_count": len(arabic_corrections)})
    except Exception as exc:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        subtitle_temp_path.unlink(missing_ok=True)
        arabic_subtitle_temp_path.unlink(missing_ok=True)
        audio_temp_path.unlink(missing_ok=True)
        log.exception("Clip render failed job_id=%s", job["job_id"])
        finish_clip_job(job["job_id"], "failed", exc)
        event("Clip render failed", video_id=job["video_id"], job_id=job["job_id"], stage="failed",
              level="ERROR", details={"type": type(exc).__name__, "message": str(exc)[:1000]})
    finally:
        audio_temp_path.unlink(missing_ok=True)


def transcribe(job, video) -> dict:
    from faster_whisper import WhisperModel

    source = resolve_library_source(video["path"])
    if fingerprint(source) != video["fingerprint"] or content_fingerprint(source) != video["content_fingerprint"]:
        raise RuntimeError("Source file changed after discovery; rescan required")
    temp_dir = settings.data_dir / "temporary"
    temp_dir.mkdir(parents=True, exist_ok=True)
    audio_path = temp_dir / f"{video['video_id']}.wav"
    set_stage(job["job_id"], "audio_extraction", 0.02)
    import subprocess
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio_path)], check=True, timeout=max(3600, int((video["duration"] or 0) * 3)))
    try:
        set_stage(job["job_id"], "transcription", 0.05)
        model = WhisperModel(settings.asr_model, device="cpu", compute_type=settings.asr_compute_type,
                             cpu_threads=settings.asr_threads, num_workers=1,
                             download_root=str(settings.model_cache_dir))
        iterator, info = model.transcribe(str(audio_path), language=settings.asr_language or None,
                                          beam_size=5, vad_filter=True, word_timestamps=False,
                                          condition_on_previous_text=True)
        segments = []
        transcript_path = settings.data_dir / "transcripts" / f"{video['video_id']}.json"
        for i, item in enumerate(iterator):
            segments.append({"sequence_number": i, "start": float(item.start), "end": float(item.end),
                             "text": item.text.strip(), "confidence": None})
            if (i + 1) % 100 == 0:
                atomic_json(transcript_path.with_suffix(".partial.json"), {
                    "video_id": video["video_id"], "language": info.language, "asr_model": settings.asr_model,
                    "asr_config": {"device":"cpu","compute_type":settings.asr_compute_type,"beam_size":5,"vad_filter":True,"word_timestamps":False},
                    "partial": True, "segments": segments})
                audio_progress = min(1.0, float(item.end) / max(1.0, float(info.duration or video["duration"] or 1)))
                set_stage(job["job_id"], "transcription", 0.05 + audio_progress * 0.70,
                          {"segments_saved": len(segments), "audio_seconds_processed": float(item.end)})
        result = {"video_id": video["video_id"], "language": info.language, "asr_model": settings.asr_model,
                  "asr_config": {"device":"cpu","compute_type":settings.asr_compute_type,"cpu_threads":settings.asr_threads,"beam_size":5,"vad_filter":True,"word_timestamps":False},
                  "duration": float(info.duration or video["duration"] or 0), "segments": segments}
        atomic_json(transcript_path, result)
        transcript_path.with_suffix(".partial.json").unlink(missing_ok=True)
        return result
    finally:
        audio_path.unlink(missing_ok=True)


def persist_segments(video_id: str, transcript: dict) -> None:
    transcript_file = str(settings.data_dir / "transcripts" / f"{video_id}.json")
    with connect() as db:
        db.execute("DELETE FROM transcript_fts WHERE video_id=?", (video_id,))
        db.execute("DELETE FROM transcript_segments WHERE video_id=?", (video_id,))
        db.execute("INSERT INTO transcripts(video_id,language,asr_model,asr_config,file_path,segment_count,duration) VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET language=excluded.language,asr_model=excluded.asr_model,asr_config=excluded.asr_config,file_path=excluded.file_path,segment_count=excluded.segment_count,duration=excluded.duration,created_at=CURRENT_TIMESTAMP",
                   (video_id, transcript["language"], transcript["asr_model"], json.dumps(transcript["asr_config"]), transcript_file, len(transcript["segments"]), transcript["duration"]))
        for seg in transcript["segments"]:
            sid = f"{video_id}:{seg['sequence_number']}"
            db.execute("INSERT INTO transcript_segments(segment_id,video_id,sequence_number,start_time,end_time,text,language,confidence) VALUES(?,?,?,?,?,?,?,?)",
                       (sid, video_id, seg["sequence_number"], seg["start"], seg["end"], seg["text"], transcript["language"], seg["confidence"]))
            db.execute("INSERT INTO transcript_fts(segment_id,video_id,text) VALUES(?,?,?)", (sid, video_id, seg["text"]))


def embed_and_index(video, transcript: dict) -> int:
    from app.embedding import embed_documents, release_model, get_qdrant, collection_name, ensure_collection

    chunks = make_chunks(transcript["segments"], video["video_id"], transcript["language"])
    set_stage(video["job_id"], "segmentation", 0.78)
    with connect() as db:
        db.execute("DELETE FROM chunks_fts WHERE video_id=?", (video["video_id"],))
        db.execute("DELETE FROM semantic_chunks WHERE video_id=?", (video["video_id"],))
        for chunk in chunks:
            db.execute("INSERT INTO semantic_chunks(chunk_id,video_id,sequence_number,start_time,end_time,text,previous_chunk_id,next_chunk_id,language,segmentation_version,source_transcript_reference) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       tuple(chunk[k] for k in ("chunk_id","video_id","sequence_number","start_time","end_time","text","previous_chunk_id","next_chunk_id","language","segmentation_version","source_transcript_reference")))
            db.execute("INSERT INTO chunks_fts(chunk_id,video_id,text) VALUES(?,?,?)", (chunk["chunk_id"], video["video_id"], chunk["text"]))
    set_stage(video["job_id"], "embedding", 0.82)
    try:
        vectors = embed_documents([c["text"] for c in chunks]) if chunks else []
    finally:
        release_model()
    client = get_qdrant()
    collection = collection_name()
    ensure_collection(client, collection)
    from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
    client.delete(collection, points_selector=Filter(must=[FieldCondition(key="video_id", match=MatchValue(value=video["video_id"]))]))
    for start in range(0, len(chunks), settings.embedding_batch_size):
        points = []
        for chunk, vector in zip(chunks[start:start + settings.embedding_batch_size], vectors[start:start + settings.embedding_batch_size]):
            points.append(PointStruct(id=chunk["chunk_id"], vector=vector, payload={
                **chunk, "source_reference": Path(video["path"]).relative_to(settings.library_root).as_posix(),
                "embedding_model_version": settings.embedding_model, "score_note": "cosine similarity; not a probability"}))
        if points:
            client.upsert(collection, points=points, wait=True)
    with connect() as db:
        db.execute("INSERT INTO embedding_indexes(index_id,model_version,dimension,collection_name,segmentation_version,status) VALUES(?,?,?,?,?,'ready') ON CONFLICT(model_version,segmentation_version) DO UPDATE SET status='ready',updated_at=CURRENT_TIMESTAMP",
                   (f"{settings.embedding_model}:{SEGMENTATION_VERSION}", settings.embedding_model, settings.embedding_dimension, collection, SEGMENTATION_VERSION))
    set_stage(video["job_id"], "indexing", 0.98)
    return len(chunks)


def process_job(job) -> None:
    started = time.perf_counter()
    with connect() as db:
        video = db.execute("SELECT * FROM videos WHERE video_id=?", (job["video_id"],)).fetchone()
    if not video:
        finish_job(job["job_id"], job["video_id"], "failed", RuntimeError("Video metadata disappeared")); return
    try:
        if not video["has_audio"]:
            finish_job(job["job_id"], video["video_id"], "skipped"); return
        # A changed/retried video must not keep serving vectors from an older transcript.
        from app.embedding import remove_video_points
        remove_video_points(video["video_id"])
        transcript_path = settings.data_dir / "transcripts" / f"{video['video_id']}.json"
        if not json.loads(job["checkpoint"]).get("reprocess") and transcript_path.exists():
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        else:
            transcript = transcribe(job, video)
        set_stage(job["job_id"], "transcript_persist", 0.76)
        persist_segments(video["video_id"], transcript)
        # video row passed to indexer needs the current job id for progress updates.
        video_dict = dict(video); video_dict["job_id"] = job["job_id"]
        chunk_count = embed_and_index(video_dict, transcript)
        finish_job(job["job_id"], video["video_id"], "completed")
        event("Ingestion completed", video_id=video["video_id"], job_id=job["job_id"], stage="completed",
              details={"segment_count":len(transcript["segments"]),"chunk_count":chunk_count,"elapsed_seconds":round(time.perf_counter()-started,2),"asr_model":settings.asr_model,"embedding_model":settings.embedding_model})
        log.info("Ingestion complete video_id=%s segments=%d chunks=%d", video["video_id"], len(transcript["segments"]), chunk_count)
    except Exception as exc:
        log.exception("Ingestion failed video_id=%s job_id=%s", video["video_id"], job["job_id"])
        finish_job(job["job_id"], video["video_id"], "failed", exc)
        event("Ingestion failed", video_id=video["video_id"], job_id=job["job_id"], stage=job["stage"], level="ERROR", details={"type":type(exc).__name__,"message":str(exc)[:1000]})
