"""Lightweight caption-vs-audio trust check.

Duration and metadata gates catch a caption track from another video. They do not
catch a same-video track whose lines were written as a joke: the words are in the
right language and fit the timeline, but they are not what the speaker says. This
module samples two short audio windows and compares what a small local ASR model
hears with the caption lines covering those windows.

It is deliberately conservative and cheap:
  * only called for non-AI caption tracks by the pipeline (human WBI included);
  * two 8s windows, concatenated into one sample;
  * only an already-cached model is used, never a fresh download;
  * no speech / no cached model / language mismatch => "unknown", keep captions.
"""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .config import Config
from .media import extract_audio_windows
from .text import to_simplified, transcribe_with_faster_whisper, whisper_cache_state

MIN_DURATION_MS = 60_000
WINDOW_MS = 8_000
MIN_TEXT_CHARS = 16
# Below REJECT the caption is clearly not the speech; only then do we pay for a
# full ASR pass. Between the two it is a gray zone: keep the caption but do not
# claim it was verified. A handful of incidental shared bigrams (今天/我们/聊聊)
# is not evidence: the longest common run must also be tiny.
REJECT_SCORE = 0.18
VERIFY_SCORE = 0.5
MAX_FILLER_RUN = 2
_CJK = re.compile(r"[\u3400-\u9fff]")
_WORD = re.compile(r"[a-z0-9']+")
_STOPWORDS = {
    "a", "about", "all", "also", "an", "and", "any", "are", "as", "at", "be",
    "because", "been", "being", "but", "by", "can", "could", "did", "do", "does",
    "for", "from", "going", "had", "has", "have", "he", "her", "here", "his",
    "how", "i", "if", "in", "is", "it", "its", "just", "like", "me", "more",
    "most", "my", "no", "not", "of", "on", "or", "our", "she", "should", "so",
    "some", "than", "that", "the", "their", "them", "then", "there", "these",
    "they", "this", "those", "to", "too", "us", "very", "was", "we", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your",
}


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(str(text or "").lower()) if w not in _STOPWORDS and len(w) > 1]


def _compact(text: str) -> str:
    simplified = to_simplified(str(text or ""))
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", "", simplified.lower())


def _cjk_ratio(text: str) -> float:
    compact = _compact(text)
    if not compact:
        return 0.0
    return len(_CJK.findall(compact)) / len(compact)


def _units(text: str) -> set[str]:
    compact = _compact(text)
    if _cjk_ratio(compact) >= 0.25:
        if len(compact) < 2:
            return set()
        return {compact[i:i + 2] for i in range(len(compact) - 1)}
    return set(_content_words(text))


def text_similarity(caption: str, asr: str) -> float:
    """Best of character/word containment and sequence ratio, in [0, 1]."""
    cap_units = _units(caption)
    asr_units = _units(asr)
    if len(cap_units) < 3 or len(asr_units) < 3:
        return 0.0
    containment = len(cap_units & asr_units) / max(1, len(cap_units))
    if _cjk_ratio(caption) >= 0.25 or _cjk_ratio(asr) >= 0.25:
        cap = _compact(caption)
        heard = _compact(asr)
        if not cap or not heard:
            return 0.0
        ratio = SequenceMatcher(None, cap, heard, autojunk=False).ratio()
        return max(containment, ratio)
    # English word order matters and common filler ("we are going to …") must not
    # count as evidence. Compare content words, not the compact character stream.
    cap_words = _content_words(caption)
    heard_words = _content_words(asr)
    if len(cap_words) < 3 or len(heard_words) < 3:
        return 0.0
    ratio = SequenceMatcher(None, cap_words, heard_words, autojunk=False).ratio()
    return max(containment, ratio)


def _common_run(caption: str, asr: str) -> int:
    """Longest contiguous shared character run (filler bigrams must not verify)."""
    cap = _compact(caption)
    heard = _compact(asr)
    if not cap or not heard:
        return 0
    match = SequenceMatcher(None, cap, heard, autojunk=False).find_longest_match(
        0, len(cap), 0, len(heard)
    )
    return int(match.size)


def _language_code(lan: str | None) -> str | None:
    parts = re.split(r"[-_]", str(lan or "").lower())
    for part in parts:
        if part in {"zh", "en", "ja", "ko"}:
            return part
    return None


def _windows(duration_ms: int) -> list[tuple[int, int]]:
    span = min(WINDOW_MS, max(4_000, duration_ms // 10))
    starts = [int(duration_ms * 0.22), int(duration_ms * 0.62)]
    out: list[tuple[int, int]] = []
    for start in starts:
        if start + span > duration_ms - 500:
            start = max(0, duration_ms - span - 500)
        if start < 0:
            start = 0
        if (start, span) not in out:
            out.append((start, span))
    return out


def _caption_text(segments: list[dict[str, Any]], start: int, end: int) -> str:
    parts: list[str] = []
    for segment in segments:
        seg_start = int(segment.get("start_ms") or 0)
        seg_end = int(segment.get("end_ms") or 0)
        if seg_end > start and seg_start < end:
            text = str(segment.get("text") or "").strip()
            if text:
                parts.append(text)
    return " ".join(parts)


def _cached_model(cfg: Config) -> str | None:
    """Prefer the configured ASR model when cached; never load medium/large for 16s."""
    allowed = {"tiny", "base", "small"}
    preferred = str(cfg.get("asr_model") or "")
    order: list[str] = []
    if preferred in allowed:
        order.append(preferred)
    for model in ("tiny", "base", "small"):
        if model not in order:
            order.append(model)
    for model in order:
        try:
            if whisper_cache_state(model).get("cached"):
                return model
        except Exception:  # noqa: BLE001 - cache inspection must never break ingest
            continue
    return None


def _verify_caption_audio(
    video_path: str | Path,
    segments: list[dict[str, Any]],
    cfg: Config,
    duration_ms: int,
    *,
    caption_lang: str | None = None,
    temp_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a trust verdict for a caption track.

    ``verdict`` is ``verified``, ``mismatch`` or ``unknown``. ``unknown`` always
    means "keep the caption": no evidence to reject it (no speech, no cached
    model, different language, ASR failure).
    """
    result: dict[str, Any] = {
        "verdict": "unknown",
        "score": 0.0,
        "reason": "",
        "model": "",
        "windows": [],
        "window_scores": [],
        "caption_sample": "",
        "asr_sample": "",
    }
    if not segments or duration_ms < MIN_DURATION_MS:
        result["reason"] = "video_too_short"
        return result
    lang = _language_code(caption_lang)
    if lang not in {"zh", "en"}:
        result["reason"] = "language_not_checked"
        return result
    windows = _windows(duration_ms)
    result["windows"] = [[start, span] for start, span in windows]
    caption_parts = [_caption_text(segments, start, start + span) for start, span in windows]
    caption_all = " ".join(part for part in caption_parts if part).strip()
    result["caption_sample"] = caption_all[:200]
    if len(_compact(caption_all)) < MIN_TEXT_CHARS:
        result["reason"] = "caption_too_short"
        return result
    model = _cached_model(cfg)
    if not model:
        result["reason"] = "no_cached_asr_model"
        return result
    result["model"] = model
    sample = Path(temp_dir or Path(cfg.derived_dir) / "caption-check") / "caption_check.wav"
    try:
        extract_audio_windows(video_path, sample, windows, audio_index=0)
    except Exception as e:  # noqa: BLE001 - a failed sample must not reject a caption
        result["reason"] = "audio_unavailable"
        result["detail"] = str(e)[:160]
        return result
    try:
        asr_segments, detected = transcribe_with_faster_whisper(
            sample,
            model_size=model,
            device=str(cfg.get("asr_device") or "auto"),
            compute_type=str(cfg.get("asr_compute_type") or "int8"),
            language=None,
            beam_size=1,
            word_timestamps=False,
            cpu_threads=int(cfg.get("asr_cpu_threads") or 0),
        )
    except Exception as e:  # noqa: BLE001 - do not turn a trust check into an ingest failure
        result["reason"] = "asr_failed"
        result["detail"] = str(e)[:160]
        return result
    finally:
        try:
            sample.unlink(missing_ok=True)
        except OSError:
            pass
    asr_text = " ".join(str(segment.get("text") or "") for segment in asr_segments).strip()
    result["asr_sample"] = asr_text[:200]
    detected_base = _language_code(detected)
    if detected_base and detected_base != lang:
        # A translated subtitle is valid but cannot be compared to the speech
        # language; keep it and say it was not checked.
        result["reason"] = "caption_language_differs"
        return result
    # Bilingual/translated tracks: compare scripts before comparing words. A
    # Latin caption over Chinese speech is not evidence of a wrong track.
    cap_cjk = _cjk_ratio(caption_all)
    asr_cjk = _cjk_ratio(asr_text)
    if (cap_cjk >= 0.4 and asr_cjk <= 0.15) or (asr_cjk >= 0.4 and cap_cjk <= 0.15):
        result["reason"] = "script_differs"
        return result
    if len(_compact(asr_text)) < MIN_TEXT_CHARS:
        result["reason"] = "no_speech"
        return result
    # A Whisper hallucination on music/silence is often long and fluent. Prefer a
    # conservative unknown over rejecting a correct caption on low-confidence ASR.
    confidences = [
        float(segment.get("confidence") or 0.0)
        for segment in asr_segments
        if segment.get("confidence") is not None
    ]
    if confidences and sum(confidences) / len(confidences) < 0.25:
        result["reason"] = "asr_low_confidence"
        return result
    # Split the concatenated ASR at the window boundaries so one silent/musical
    # window cannot drag a valid caption under the reject line.
    boundaries: list[int] = []
    total = 0
    for _start, span in windows:
        total += span
        boundaries.append(total)
    asr_parts: list[str] = []
    previous = 0
    for boundary in boundaries:
        parts = []
        for segment in asr_segments:
            start_ms = int(segment.get("start_ms") or 0)
            if previous <= start_ms < boundary:
                text = str(segment.get("text") or "").strip()
                if text:
                    parts.append(text)
        asr_parts.append(" ".join(parts))
        previous = boundary
    window_scores: list[dict[str, Any]] = []
    for index, (cap_part, heard_part) in enumerate(zip(caption_parts, asr_parts)):
        if len(_compact(cap_part)) < MIN_TEXT_CHARS or len(_compact(heard_part)) < MIN_TEXT_CHARS:
            continue
        score = text_similarity(cap_part, heard_part)
        run = _common_run(cap_part, heard_part)
        window_scores.append({
            "index": index,
            "score": round(score, 3),
            "run": run,
            "caption_chars": len(_compact(cap_part)),
            "asr_chars": len(_compact(heard_part)),
        })
    result["window_scores"] = window_scores
    if not window_scores:
        result["reason"] = "no_speech"
        return result
    result["score"] = round(sum(item["score"] for item in window_scores) / len(window_scores), 3)
    all_fail = all(item["score"] < REJECT_SCORE and item["run"] <= MAX_FILLER_RUN for item in window_scores)
    all_pass = all(item["score"] >= VERIFY_SCORE for item in window_scores)
    if len(window_scores) >= 2 and all_fail:
        result["verdict"] = "mismatch"
        result["reason"] = "speech_differs"
    elif len(window_scores) >= 2 and all_pass:
        result["verdict"] = "verified"
        result["reason"] = "speech_matches"
    else:
        # One scorable window is not enough to reject **or** verify a caption:
        # the other may have been music, silence, or an ASR miss. Keep it.
        result["verdict"] = "unknown"
        result["reason"] = "low_confidence"
    return result


def verify_caption_audio(
    video_path: str | Path,
    segments: list[dict[str, Any]],
    cfg: Config,
    duration_ms: int,
    *,
    caption_lang: str | None = None,
    temp_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Timed public wrapper; ``seconds`` makes the cost visible in metrics."""
    started = time.perf_counter()
    result = _verify_caption_audio(
        video_path,
        segments,
        cfg,
        duration_ms,
        caption_lang=caption_lang,
        temp_dir=temp_dir,
    )
    result["seconds"] = round(time.perf_counter() - started, 2)
    return result
