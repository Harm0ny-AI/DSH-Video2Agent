"""One-call, extractive video index for an agent.

This is intentionally not a generated summary. It bundles the timestamps and a
contact sheet so the host model can decide what to inspect next.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .db import Database
from .media import audio_profile
from .text import normalize_text
from .util import Video2AgentError, ensure_dir, not_ready_error

OCR_RELIABLE_MIN = 0.5
# Bounded on purpose: these hints ride in every digest call, so 16 cuts and 6
# silence intervals are the whole budget (roughly 120 tokens, digits only).
MAX_SCENE_CUTS = 16
MAX_SILENCES = 6
MAX_SCORE_CUES = 8
# "9-7", "2:1", "10 - 8": a score between short numbers. A date ("2024-01-01",
# "24-01-01") and a chain ("1-9-7") must not count as one; `_looks_like_score`
# applies the context checks the regex alone cannot express.
_SCORE_RE = re.compile(r"(?<![A-Za-z\d])(\d{1,2})\s*([-:：])\s*(\d{1,2})(?!\d)")
_YEAR_PREFIX = re.compile(r"\d{4}\s*[-:：]\s*$")
_DATE_PREFIX = re.compile(r"\d{4}\s*[-:：]\s*\d{1,2}\s*[-:：]\s*$")
_CHAIN_SUFFIX = re.compile(r"\s*[-:：]\s*\d")
_LABEL_PREFIX = re.compile(r"[A-Za-z]+\s*\d{1,2}\s*[:：]\s*")


def _looks_like_score(text: str) -> bool:
    # "Game 1: 9-7" consumes "1: 9" first; retrying without the label lets the
    # actual score be seen instead of being swallowed by the match before it.
    for candidate in (text, _LABEL_PREFIX.sub(" ", text)):
        for match in _SCORE_RE.finditer(candidate):
            prefix = candidate[:match.start()]
            suffix = candidate[match.end():]
            if _YEAR_PREFIX.search(prefix) or _DATE_PREFIX.search(prefix):
                continue
            if _CHAIN_SUFFIX.match(suffix):
                continue
            return True
    return False


def _score_cues(ocr: list[dict[str, Any]], max_cues: int = MAX_SCORE_CUES) -> list[dict[str, Any]]:
    """Timestamped score-like OCR lines (sports counting is otherwise blind).

    Only returned when something matches; a cue is text the model can read, not
    a computed score. Consecutive identical lines collapse to the first one.
    """
    cues: list[dict[str, Any]] = []
    previous = None
    for track in ocr:
        text = normalize_text(str(track.get("text") or ""))
        if not text or not _looks_like_score(text):
            continue
        if text == previous:
            continue
        previous = text
        cues.append({"start_ms": int(track.get("start_ms") or 0),
                     "timecode": _format_ms(int(track.get("start_ms") or 0)),
                     "text": text[:80]})
        if len(cues) >= max_cues:
            break
    return cues


def _reliable(value: Any) -> bool | None:
    if value is None:
        return None
    try:
        return float(value) >= OCR_RELIABLE_MIN
    except (TypeError, ValueError):
        return None


def _format_ms(ms: int) -> str:
    total = max(0, int(ms))
    h, rest = divmod(total, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s = rest // 1000
    return f"{h:02d}:{m:02d}:{s:02d}"


def _evenly(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not items:
        return []
    if len(items) <= count:
        return items
    if count == 1:
        return [items[0]]
    idx = [round(i * (len(items) - 1) / (count - 1)) for i in range(count)]
    return [items[i] for i in idx]


def _contact_sheet(frames: list[dict[str, Any]], out_dir: Path, max_frames: int = 6) -> tuple[str | None, list[dict[str, Any]], int]:
    limit = max(1, min(6, int(max_frames or 6)))
    picked = _evenly([f for f in frames if f.get("path") and Path(str(f["path"])).exists()], limit)
    if not picked:
        return None, [], 0
    th, tw = 180, 320
    label_h = 24
    # Decode first, then size the canvas from usable tiles. This avoids both
    # a blank slot for a corrupt frame and a needlessly wide black canvas.
    tiles: list[tuple[Any, dict[str, Any]]] = []
    for frame in picked:
        try:
            with Image.open(str(frame["path"])) as img:
                tile = img.convert("RGB")
                # Cover-fit; never stretch a UI screenshot.
                ratio = max(tw / tile.width, th / tile.height)
                tile = tile.resize((max(1, int(tile.width * ratio)), max(1, int(tile.height * ratio))), Image.Resampling.LANCZOS)
                left = max(0, (tile.width - tw) // 2)
                top = max(0, (tile.height - th) // 2)
                tile = tile.crop((left, top, left + tw, top + th))
                tiles.append((tile, frame))
        except Exception:
            # A corrupt frame must not become a black tile in a successful sheet.
            continue
    if not tiles:
        return None, [], 0
    columns = min(3, len(tiles))
    rows = max(1, (len(tiles) + columns - 1) // columns)
    sheet = Image.new("RGB", (tw * columns, (th + label_h) * rows), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    keys: list[dict[str, Any]] = []
    for slot, (tile, frame) in enumerate(tiles):
        x = (slot % columns) * tw
        y = (slot // columns) * (th + label_h)
        sheet.paste(tile, (x, y))
        draw.rectangle((x, y + th, x + tw, y + th + label_h), fill=(16, 16, 16))
        draw.text((x + 6, y + th + 5), _format_ms(int(frame.get("pts_ms") or 0)), fill=(235, 235, 235), font=font)
        keys.append({"index": slot, "t_ms": int(frame.get("pts_ms") or 0),
                     "timecode": _format_ms(int(frame.get("pts_ms") or 0))})
    out_dir = ensure_dir(out_dir)
    target = out_dir / (f"digest_sheet_{int(picked[0]['pts_ms'])}_"
                        f"{int(picked[-1]['pts_ms'])}_{len(tiles)}.jpg")
    sheet.save(target, "JPEG", quality=85)
    return str(target), keys, len(keys)


def digest(cfg: Any, video_id: str, *, max_chars: int = 6000, max_frames: int = 6,
           max_ocr: int = 80, compact: bool = False) -> dict[str, Any]:
    with Database(cfg.db_path) as db:
        video = db.get_video(video_id)
        if not video:
            raise Video2AgentError("E_NOT_FOUND", f"Video not found: {video_id}", "Run video2agent list.")
        if str(video.get("status") or "") != "ready":
            raise not_ready_error(video_id, video.get("status"), action="作为视频证据")
        duration = int(video.get("duration_ms") or 0)
        segments = db.get_segments(video_id, limit=10000)
        ocr = db.get_ocr_tracks(video_id, limit=1500)
        ocr_total = db.count_ocr_tracks(video_id)
        frames = db.get_frames(video_id, limit=1000)
        scenes = db.get_scenes(video_id)
    transcript: list[Any] = []
    chars = 0
    next_start = None
    for seg in segments:
        text = str(seg.get("text") or "")
        if transcript and chars + len(text) > max_chars:
            next_start = int(seg.get("start_ms") or 0)
            break
        if compact:
            # One "HH:MM:SS text" line instead of a five-key object per segment:
            # the same content and timecode, without ~90 JSON chars of overhead.
            transcript.append(f"{_format_ms(int(seg.get('start_ms') or 0))} {text}")
        else:
            transcript.append({
                "start_ms": int(seg.get("start_ms") or 0),
                "end_ms": int(seg.get("end_ms") or 0),
                "timecode": _format_ms(int(seg.get("start_ms") or 0)),
                "text": text,
                "source": seg.get("source"),
            })
        chars += len(text)
    ocr_rows = []
    previous_text = None
    for t in ocr[:max_ocr]:
        text = normalize_text(str(t.get("text") or ""))
        # The same line read on consecutive frames is one fact; repeating it
        # bloated digest with 80 near-identical rows on a screenshot-heavy video.
        if text and text == previous_text:
            continue
        previous_text = text
        if compact:
            ocr_rows.append(f"{_format_ms(int(t.get('start_ms') or 0))} {text}")
        else:
            ocr_rows.append({
                "start_ms": int(t.get("start_ms") or 0),
                "end_ms": int(t.get("end_ms") or 0),
                "timecode": _format_ms(int(t.get("start_ms") or 0)),
                "text": t.get("text"),
                "confidence": t.get("confidence"),
                "ocr_reliable": _reliable(t.get("confidence")),
            })
    sheet, keyframes, placed = _contact_sheet(frames, cfg.derived_dir / video_id / "frames", max_frames)
    # Scene boundaries are already stored at ingest; exposing them costs no extra
    # work and tells the model where the picture probably changed.
    cuts = _evenly(scenes[1:], MAX_SCENE_CUTS)
    source_path = str(video.get("source_path") or "")
    audio = audio_profile(source_path, max_gaps=MAX_SILENCES) if source_path and Path(source_path).exists() else None
    warnings: list[dict[str, Any]] = []
    if not segments:
        warnings.append({"code": "NO_TRANSCRIPT", "message": "没有转写；digest 只含画面/OCR。"})
    if not frames:
        warnings.append({"code": "NO_FRAMES", "message": "没有采样帧；contact sheet 为空。"})
    elif placed == 0:
        warnings.append({"code": "FRAMES_UNREADABLE", "message": "有采样帧但都读不出来；contact sheet 未生成。"})
    elif placed < min(max_frames, len(frames)):
        warnings.append({"code": "CONTACT_SHEET_PARTIAL", "message": f"contact sheet 只放下 {placed} 帧；其余帧损坏或缺失。"})
    if ocr_total > max_ocr:
        warnings.append({"code": "OCR_TRUNCATED", "message": f"OCR 共 {ocr_total} 条，digest 只含前 {max_ocr} 条。"})
    if next_start is not None:
        # A digest is a sample: say where the sample ends instead of letting the
        # model treat the first N characters as the whole video.
        warnings.append({
            "code": "DIGEST_SAMPLED",
            "message": f"转写是抽样：只含前 {chars} 字符（到 {_format_ms(next_start)}），不是全片。"
                       f"用 read --start 从 next_start_ms 继续，或先用 search 定位。",
        })
    cues = _score_cues(ocr)
    payload: dict[str, Any] = {
        "ok": True,
        "video_id": video_id,
        "title": video.get("title"),
        "duration_ms": duration,
        "duration": _format_ms(duration),
        "transcript": transcript,
        "transcript_format": "lines" if compact else "objects",
        "transcript_truncated": next_start is not None,
        "next_start_ms": next_start,
        "ocr": ocr_rows,
        "ocr_format": "lines" if compact else "objects",
        "ocr_total": ocr_total,
        "ocr_truncated": ocr_total > max_ocr,
        # Milliseconds, deliberately: 16 integers cost far fewer tokens than
        # timecode strings, and `frames --at` accepts milliseconds.
        "scene_cuts": {
            "count": max(0, len(scenes) - 1),
            "cuts_ms": [int(s.get("start_ms") or 0) for s in cuts],
            "truncated": len(scenes) - 1 > MAX_SCENE_CUTS,
        },
        # None when the media file is gone (a metadata-only record); otherwise
        # {has_audio, mean_dbfs, max_dbfs, silence_ratio, longest_silence_ms,
        #  silence_count, silences_ms[[start,end], ...]}.
        "audio": audio,
        "keyframes": keyframes,
        "contact_sheet": sheet,
        "images": [sheet] if sheet else [],
        "drilldown": {"transcript": True, "search": True, "frames": True, "crop": True},
        "warnings": warnings,
    }
    if cues:
        # Only present when the OCR text actually looks like a score; an empty
        # field would imply "no scoring in this video" on every non-sports video.
        payload["score_cues"] = cues
        payload["score_cues_truncated"] = len(cues) >= MAX_SCORE_CUES
    return payload
