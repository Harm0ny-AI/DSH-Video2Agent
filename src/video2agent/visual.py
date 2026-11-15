from __future__ import annotations

import math
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from .errors import OcrFailed
from .text import normalize_text, tokens_for_search


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


_OCR_TRIED = False
_OCR_AVAILABLE = False
_OCR_TRIED_AT = 0.0
# A failed import is retried after this long: a user who installs the OCR package
# (or fixes a broken environment) must not need to restart the process.
_OCR_RETRY_SECONDS = 30.0
_OCR_LOCK = threading.Lock()
_OCR_LOCAL = threading.local()

_OCR_NOISE = {
    "bilibili", "biibili", "b站", "bilibili.com", "www.bilibili.com",
    "?", "？", "...", "…", "·", "•",
}


def _is_ocr_noise(text: str) -> bool:
    t = re.sub(r"\s+", "", text or "").lower()
    return t in _OCR_NOISE


def ocr_available() -> bool:
    global _OCR_TRIED, _OCR_AVAILABLE, _OCR_TRIED_AT
    now = time.monotonic()
    if _OCR_TRIED and (_OCR_AVAILABLE or now - _OCR_TRIED_AT < _OCR_RETRY_SECONDS):
        return _OCR_AVAILABLE
    with _OCR_LOCK:
        now = time.monotonic()
        if _OCR_TRIED and (_OCR_AVAILABLE or now - _OCR_TRIED_AT < _OCR_RETRY_SECONDS):
            return _OCR_AVAILABLE
        _OCR_TRIED = True
        _OCR_TRIED_AT = now
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore  # noqa: F401
            _OCR_AVAILABLE = True
        except Exception:
            _OCR_AVAILABLE = False
    return _OCR_AVAILABLE


def _engine_key(config_path: str | None) -> str:
    # The cached engine belongs to the config file's current bytes. Without the
    # stamp, regenerating the YAML (or switching to a new local model) kept the old
    # engine for the rest of the process.
    if not config_path:
        return "builtin"
    path = Path(config_path)
    try:
        stat = path.stat()
        return f"{path}::{stat.st_mtime_ns}::{stat.st_size}"
    except OSError:
        return f"{path}::missing"


def _engine_for_thread(config_path: str | None = None):
    # RapidOCR mutates detector postprocess state; one engine per worker thread
    # avoids silent empty results under concurrent OCR. Cache per config path so
    # the built-in and a user-supplied local model do not overwrite each other.
    engines = getattr(_OCR_LOCAL, "engines", None)
    if engines is None:
        engines = {}
        _OCR_LOCAL.engines = engines
    key = _engine_key(config_path)
    engine = engines.get(key)
    if engine is None:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        engine = RapidOCR(config_path=config_path) if config_path else RapidOCR()
        engines[key] = engine
    return engine


def _box_xywh(box: Any, w: int, h: int) -> list[float]:
    try:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        x1, x2 = max(0.0, min(xs)), min(float(w), max(xs))
        y1, y2 = max(0.0, min(ys)), min(float(h), max(ys))
        return [round(x1, 2), round(y1, 2), round(max(0.0, x2 - x1), 2), round(max(0.0, y2 - y1), 2)]
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]


def ocr_image(path: str | Path, config_path: str | None = None) -> list[dict[str, Any]]:
    """Read the text in one frame.

    Returns an empty list only when the frame was actually read and had no text.
    Raises OcrFailed when the read could not happen at all; callers must record
    that state instead of pretending the frame is empty.
    """
    if not ocr_available():
        raise OcrFailed("未安装 OCR（rapidocr-onnxruntime）")
    try:
        engine = _engine_for_thread(config_path)
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((1024, 1024), Image.Resampling.BILINEAR)
            w, h = im.size
            arr = np.asarray(im)
        result, _ = engine(arr)
    except Exception as exc:  # noqa: BLE001 - the reason matters, not the type
        raise OcrFailed(f"{type(exc).__name__}: {exc}") from exc
    if not result:
        return []
    out: list[dict[str, Any]] = []
    for item in result:
        try:
            box, text, score = item[0], normalize_text(str(item[1])), float(item[2])
        except Exception:
            continue
        if not text or score < 0.35 or _is_ocr_noise(text):
            continue
        xywh = _box_xywh(box, w, h)
        if xywh[2] <= 1 or xywh[3] <= 1:
            continue
        out.append({
            "text": text,
            "confidence": round(score, 4),
            "bbox": xywh,
            "bbox_norm": [
                round(xywh[0] / max(1, w), 4), round(xywh[1] / max(1, h), 4),
                round(xywh[2] / max(1, w), 4), round(xywh[3] / max(1, h), 4),
            ],
        })
    out.sort(key=lambda b: (b["bbox"][1], b["bbox"][0]))
    return out


def _ocr_signal_score(f: dict[str, Any]) -> float:
    # Measured on synthetic 640x360 slides: a text slide scores 0.017-0.018,
    # a blank one 0.000. The old 0.04 cut filtered every text frame, so the
    # fallback (every Nth frame) decided what got OCR'd — blank-first decks read
    # only blanks. 0.004 sits between the two measured populations.
    #
    # Cheap pre-OCR signal: line/edge structure is a better clue than raw
    # brightness, and it avoids spending OCR on talking-head/blank frames.
    return (float(f.get("line_score") or 0) * 0.50
            + float(f.get("edge_density") or 0) * 0.30
            + float(f.get("sharpness") or 0) * 0.15
            + min(0.05, float(f.get("motion") or 0) * 0.05))


def select_ocr_frames(frames: list[dict[str, Any]], max_frames: int, *,
                      min_score: float = 0.004) -> list[dict[str, Any]]:
    """Pick a sparse, timeline-spread set of frames worth OCR.

    This is a filter, not image understanding: the host VLM still reads the
    returned evidence frames. One best-scoring frame per time bucket keeps
    coverage; low-information buckets are skipped rather than wasting OCR.
    """
    if not frames or max_frames <= 0:
        return []
    if len(frames) <= max_frames:
        return [f for f in frames if _ocr_signal_score(f) >= min_score] or frames
    chosen: list[dict[str, Any]] = []
    n = len(frames)
    for b in range(max_frames):
        start = int(b * n / max_frames)
        end = max(start + 1, int((b + 1) * n / max_frames))
        bucket = frames[start:end]
        if not bucket:
            continue
        best = max(bucket, key=_ocr_signal_score)
        if _ocr_signal_score(best) >= min_score:
            chosen.append(best)
    if not chosen:
        step = max(1, n // max_frames)
        chosen = frames[::step][:max_frames]
    return chosen


def plan_ocr_budget(duration_ms: int, *, rate: float = 1.0, cap: int = 60,
                    n_scenes: int = 0) -> int:
    """Choose how many frames to OCR.

    A pure duration rate (1/min) under-served slide-heavy videos: a 12-minute
    deck got 12 OCR frames and read only ~1/6 of the slides. Raise the budget
    towards one frame per scene, but never above ``cap`` (a hard ceiling;
    callers that must not shrink the old budget pass ``max(base, cap)``).
    """
    cap = max(6, int(cap))
    minutes = max(0.1, float(duration_ms) / 60000.0)
    base = max(6, int(round(minutes * float(rate))))
    scene_ceiling = max(0, int(n_scenes))
    if scene_ceiling <= 0:
        return min(cap, base)
    target = max(base, min(scene_ceiling, cap))
    return max(6, min(cap, target))


def _frames_at_times(frames: list[dict[str, Any]], times: list[int], tolerance_ms: int = 1500) -> list[dict[str, Any]]:
    """Frames nearest to the stored anchors, so a re-ingest reads the same moments."""
    pool = sorted(frames, key=lambda f: int(f["pts_ms"]))
    chosen: list[dict[str, Any]] = []
    seen: set[int] = set()
    for target in times:
        best = min(pool, key=lambda f: abs(int(f["pts_ms"]) - int(target)))
        if abs(int(best["pts_ms"]) - int(target)) > tolerance_ms or id(best) in seen:
            continue
        seen.add(id(best))
        chosen.append(best)
    return chosen


def attach_ocr(
    frames: list[dict[str, Any]],
    *,
    max_frames: int = 120,
    progress: Callable[[int, int, int], None] | None = None,
    times: list[int] | None = None,
    ocr_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    ocr_config_path: str | None = None,
) -> list[dict[str, Any]]:
    if not frames:
        return frames
    if ocr_fn is None and not ocr_available():
        for f in frames:
            # Not read: unknown, never 0.0. A missing OCR install must not turn
            # every frame into a confirmed "no text".
            f["ocr_status"] = "unavailable"
            f["text_coverage"] = None
            f.setdefault("ocr_error", "未安装 OCR（rapidocr-onnxruntime）")
        return frames
    # Sparse, timeline-spread OCR. Frames without enough visual structure are
    # skipped; the host VLM can still inspect the sampled evidence frames.
    # `times` pins the selection to saved anchors so answers stay reproducible.
    chosen = _frames_at_times(frames, times) if times else select_ocr_frames(frames, max_frames)
    chosen_ids = {id(f) for f in chosen}
    if len(chosen) < len(frames):
        for f in frames:
            if id(f) not in chosen_ids:
                # Not read: text_coverage stays unmeasured (None), never 0.0.
                f["ocr_status"] = "skipped"
    # RapidOCR is not safe to call concurrently: parallel runs silently
    # returned empty results on some frames. Keep OCR sequential; the cheap
    # prefilter above is what reduces the workload.
    results: list[tuple[list[dict[str, Any]] | None, str | None]] = []
    for done, f in enumerate(chosen, start=1):
        try:
            boxes = ocr_fn(f["path"]) if ocr_fn is not None else ocr_image(f["path"], config_path=ocr_config_path)
            results.append((boxes, None))
        except OcrFailed as exc:
            results.append((None, str(exc)))
        except Exception as exc:  # noqa: BLE001 - a crash is a failed read, not an empty frame
            results.append((None, f"{type(exc).__name__}: {exc}"))
        if progress is not None:
            progress(done, len(chosen), int(f["pts_ms"]))
    for f, (boxes, err) in zip(chosen, results):
        if err is not None:
            f["ocr"] = []
            f["ocr_status"] = "failed"
            f["text_coverage"] = None
            f["ocr_error"] = err[:300]
            continue
        f["ocr"] = boxes
        f["ocr_status"] = "ok" if boxes else "empty"
        f["text_coverage"] = text_coverage_for(f["path"], boxes)
    return frames


def ocr_summary(frames: list[dict[str, Any]]) -> dict[str, int]:
    """Count what actually happened to each frame's text, for honest reporting.

    read = really read (with or without text); failed = the read never completed;
    unread = never attempted (lazy/on-demand mode, skipped, or no OCR installed).
    """
    out = {"total": len(frames), "read": 0, "empty": 0, "failed": 0,
           "skipped": 0, "unavailable": 0, "unmeasured": 0}
    for f in frames:
        status = str(f.get("ocr_status") or "unmeasured")
        if status == "ok":
            out["read"] += 1
        elif status == "empty":
            out["read"] += 1
            out["empty"] += 1
        elif status == "failed":
            out["failed"] += 1
        elif status == "skipped":
            out["skipped"] += 1
        elif status == "unavailable":
            out["unavailable"] += 1
        else:
            out["unmeasured"] += 1
    return out


def ocr_state(summary: dict[str, int], *, on_demand: bool = False) -> str:
    """One word for the whole video: indexed / partial / failed / on_demand / unavailable / unmeasured."""
    read = int(summary.get("read") or 0)
    failed = int(summary.get("failed") or 0)
    unavailable = int(summary.get("unavailable") or 0)
    if failed and not read:
        return "failed"
    if failed and read:
        return "partial"
    if read:
        return "indexed"
    if unavailable:
        return "unavailable"
    if on_demand:
        return "on_demand"
    return "unmeasured"


def text_coverage_for(path: str | Path, boxes: list[dict[str, Any]]) -> float | None:
    """How much of the frame the OCR boxes cover; 0.0 only when the read happened."""
    if not boxes:
        return 0.0
    if any(b.get("cloud") for b in boxes):
        # Cloud OCR returns text, not reliable boxes: do not claim coverage.
        return None
    area = sum(b["bbox"][2] * b["bbox"][3] for b in boxes)
    with Image.open(path) as im:
        width, height = im.size
    # Boxes are in the OCR thumbnail's coordinates (max 1024px on the long side).
    # Comparing them with the original size under-counts 1280x720 by (1024/1280)^2
    # = 0.64 and pushes text slides below the slide/table thresholds.
    scale = min(1.0, 1024.0 / max(1, width, height))
    return round(min(1.0, area / max(1.0, (width * scale) * (height * scale))), 4)


def _collapse_repeated_text(text: str) -> str:
    """Collapse one OCR line repeated by an engine into one occurrence."""
    clean = normalize_text(text or "")
    parts = clean.split()
    if len(parts) >= 4:
        common, count = Counter(parts).most_common(1)[0]
        if count >= max(3, int(len(parts) * 0.6)):
            return common
    return clean


def _unique_ocr_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate OCR detections of the same line at the same row.

    OCR engines often return the same subtitle 50-100 times; joining every
    box made one evidence row 3.6k characters of the same sentence. Keep
    identical text only when it sits on a different row (a real table cell).
    """
    seen: set[tuple[str, int]] = set()
    out: list[dict[str, Any]] = []
    for box in boxes:
        text = _collapse_repeated_text(box.get("text") or "")
        if not text:
            continue
        bbox = box.get("bbox") or []
        row = round(float(bbox[1]) / 8.0) if len(bbox) >= 2 else 0
        key = (re.sub(r"\s+", "", text).lower(), row)
        if key in seen:
            continue
        seen.add(key)
        out.append({**box, "text": text})
    return out


def _frame_text_track(f: dict[str, Any], boxes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One retrievable document per OCR'd frame, in reading order.

    Line-level tracks fragment tables and slides: "准确率" and "85%" end up in
    different documents, so a question that spans a table matched neither well.
    Joining the boxes of one frame keeps the table (and slide title + body)
    together as one searchable unit. Only for 3+ boxes to limit noise.
    """
    boxes = _unique_ocr_boxes(boxes)
    if len(boxes) < 3:
        return None
    ordered = sorted(
        boxes,
        key=lambda b: (round(float(b["bbox"][1]) / 12.0), float(b["bbox"][0])),
    )
    text = normalize_text(" | ".join(b["text"] for b in ordered))
    if len(text) < 8:
        return None
    xs = [b["bbox"][0] for b in ordered]
    ys = [b["bbox"][1] for b in ordered]
    x2 = max(b["bbox"][0] + b["bbox"][2] for b in ordered)
    y2 = max(b["bbox"][1] + b["bbox"][3] for b in ordered)
    return {
        "key": "frame:" + re.sub(r"\s+", "", text).lower(),
        "text": text,
        "start_ms": int(f["pts_ms"]),
        "end_ms": int(f["pts_ms"]),
        "bbox": [min(xs), min(ys), round(x2 - min(xs), 2), round(y2 - min(ys), 2)],
        "confidence": round(sum(float(b.get("confidence") or 0) for b in ordered) / len(ordered), 4),
        "change_type": "frame_text",
    }


def build_ocr_tracks(frames: list[dict[str, Any]], *, max_gap_ms: int = 3500) -> list[dict[str, Any]]:
    tracks: list[dict[str, Any]] = []
    for f in sorted(frames, key=lambda x: x["pts_ms"]):
        boxes = _unique_ocr_boxes([b for b in (f.get("ocr") or []) if normalize_text(b.get("text") or "")])
        frame_track = _frame_text_track(f, boxes)
        if frame_track:
            tracks.append(frame_track)
        for box in boxes:
            text = normalize_text(box.get("text") or "")
            if not text:
                continue
            key = re.sub(r"\s+", "", text).lower()
            found = None
            for t in reversed(tracks[-40:]):
                if t["key"] == key and f["pts_ms"] - t["end_ms"] <= max_gap_ms:
                    found = t
                    break
            if found:
                found["end_ms"] = int(f["pts_ms"])
                found["confidence"] = round((found["confidence"] + float(box.get("confidence") or 0)) / 2, 4)
                found["last_bbox"] = box.get("bbox")
            else:
                tracks.append({
                    "key": key,
                    "text": text,
                    "start_ms": int(f["pts_ms"]),
                    "end_ms": int(f["pts_ms"]),
                    "bbox": box.get("bbox"),
                    "confidence": float(box.get("confidence") or 0),
                                "change_type": "appear",
                })
    for t in tracks:
        t["tokens"] = tokens_for_search(t["text"])
        t.pop("key", None)
        t.pop("last_bbox", None)
    # Merge duplicate/near-identical text tracks that overlap heavily.
    merged: list[dict[str, Any]] = []
    for t in sorted(tracks, key=lambda x: x["start_ms"]):
        dup = None
        for m in reversed(merged[-10:]):
            if m["text"] == t["text"] and abs(m["start_ms"] - t["start_ms"]) < 1500:
                dup = m
                break
        if dup:
            dup["end_ms"] = max(dup["end_ms"], t["end_ms"])
        else:
            merged.append(t)
    return merged


def _grid_score(frames: list[dict[str, Any]]) -> float:
    boxes = []
    for f in frames:
        for b in f.get("ocr", []) or []:
            bb = b.get("bbox") or []
            if len(bb) == 4:
                # Left/top edges reveal table columns and rows; centers over-count long lines.
                boxes.append((bb[0], bb[1]))
    if len(boxes) < 6:
        return 0.0
    def clusters(vals: list[float], tol: float = 24.0) -> list[float]:
        out: list[float] = []
        for v in sorted(vals):
            if not out or abs(v - out[-1]) > tol:
                out.append(v)
            else:
                out[-1] = (out[-1] + v) / 2
        return out
    rows = len(clusters([y for _, y in boxes]))
    cols = len(clusters([x for x, _ in boxes]))
    if rows < 3 or cols < 2:
        return 0.0
    return round(min(1.0, (rows * cols) / 12.0), 4)


def _aggregate(frames: list[dict[str, Any]]) -> dict[str, float]:
    if not frames:
        return {"motion": 0.0, "text_coverage": None, "edge_density": 0.0, "line_score": 0.0,
                "sharpness": 0.0, "color_entropy": 0.0, "static_ratio": 0.0, "grid_score": 0.0}
    def avg(key: str) -> float:
        vals = [float(f.get(key)) for f in frames if f.get(key) is not None]
        return sum(vals) / len(vals) if vals else 0.0
    motion = avg("motion")
    static = 1.0 - min(1.0, motion / 0.12)
    # Text coverage is only known for frames that were actually OCR'd. Averaging the
    # rest in as 0.0 is how every slide ended up labelled `animation`; including the
    # `skipped` frames' explicit 0.0 dilutes it just as badly (measured: one read frame
    # at 0.19 plus five skipped became 0.0317, which flips slide_like to talking_head).
    read = [f for f in frames if f.get("ocr_status") in ("ok", "empty")]
    text_values = [float(f["text_coverage"]) for f in read if f.get("text_coverage") is not None]
    text_coverage = round(sum(text_values) / len(text_values), 4) if text_values else None
    return {
        "motion": round(motion, 4),
        "text_coverage": text_coverage,
        "edge_density": round(avg("edge_density"), 4),
        "line_score": round(avg("line_score"), 4),
        "sharpness": round(avg("sharpness"), 4),
        "color_entropy": round(avg("color_entropy"), 4),
        "static_ratio": round(static, 4),
        "grid_score": _grid_score(frames),
    }


def label_scores(signals: dict[str, float], *, ocr_ok: bool = True) -> dict[str, float]:
    motion = signals.get("motion", 0.0)
    text = signals.get("text_coverage")
    if text is None:
        # No frame in this segment was read, so no semantic label is justified. The
        # old code substituted 0.0 here, which made `slide_like` unreachable and sent
        # 91% of segments to `animation`.
        return {}
    edge = signals.get("edge_density", 0.0)
    line = signals.get("line_score", 0.0)
    color = signals.get("color_entropy", 0.0)
    static = signals.get("static_ratio", 0.0)
    grid = signals.get("grid_score", 0.0)
    table_raw = _sigmoid(2.4 * line + 2.6 * grid + 4.0 * text + 1.0 * static - 3.2)
    # A table needs lines/structure AND a stable, text-bearing page.
    # Scattered animation text must not become table_like just because OCR boxes form rows.
    table_gate = 1.0 if (line >= 0.04 and text >= 0.06 and static >= 0.85 and grid >= 0.5) else 0.30
    table = table_raw * table_gate
    chart = _sigmoid(2.0 * edge + 1.3 * color + 0.8 * static - 1.2 * text - 3.4)
    slide = _sigmoid(2.2 * static + 10.0 * text + 0.6 * edge - 2.4)
    screencast = _sigmoid(1.6 * edge + 8.0 * text + 0.8 * (1.0 - static) - 3.7)
    talking = _sigmoid(1.5 * static + 1.4 * (1.0 - text) - 2.6)
    animation = _sigmoid(2.5 * motion + 1.5 * (1.0 - text) + 0.8 * color - 3.4)
    static_low = _sigmoid(2.0 * static + 2.0 * (1.0 - text) + 0.5 * (1.0 - edge) - 4.5)
    # Colorful, low-text, moving frames are usually animation/B-roll, even when
    # the average 1 fps motion is small. Gate on color so plain slides stay slides.
    if color > 0.14 and text < 0.12 and edge > 0.04:
        animation = max(animation, _sigmoid(5.0 * (color - 0.12) + 2.0 * (1.0 - text) + 2.0 * motion - 0.8))
    scores = {
        "table_like": table,
        "chart_like": chart,
        "slide_like": slide,
        "screencast": screencast,
        "talking_head": talking,
        "animation": animation,
        "static_low_info": static_low,
    }
    if not ocr_ok:
        # Without OCR, text-based labels are weaker.
        for k in ("table_like", "slide_like", "screencast"):
            scores[k] *= 0.55
    return {k: round(v, 4) for k, v in scores.items()}


def visual_segments(scenes: list[dict[str, Any]], frames: list[dict[str, Any]], *, ocr_ok: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sc in scenes:
        start, end = int(sc["start_ms"]), int(sc["end_ms"])
        inside = [f for f in frames if start <= f["pts_ms"] <= end]
        if not inside:
            # A scene without a sampled frame used to be dropped silently, so the
            # visual map looked complete while a quarter of the scenes were missing.
            out.append({
                "start_ms": start,
                "end_ms": end,
                "label": "unknown",
                "score": 0.0,
                "signals": {},
                "scores": {},
                "keyframe_ms": sc.get("keyframe_ms") or start,
                "reason": "no_frame",
            })
            continue
        sig = _aggregate(inside)
        scores = label_scores(sig, ocr_ok=ocr_ok)
        if not scores:
            out.append({
                "start_ms": start,
                "end_ms": end,
                "label": "unknown",
                "score": 0.0,
                "signals": sig,
                "scores": {},
                "keyframe_ms": sc.get("keyframe_ms") or start,
                "reason": "text_unmeasured",
            })
            continue
        label, score = max(scores.items(), key=lambda kv: kv[1])
        if score < 0.35:
            label, score = "unknown", round(score, 4)
        out.append({
            "start_ms": start,
            "end_ms": end,
            "label": label,
            "score": round(float(score), 4),
            "signals": sig,
            "scores": scores,
            "keyframe_ms": sc.get("keyframe_ms") or start,
        })
    return out


def best_frame(frames: list[dict[str, Any]], *, prefer_text: bool = True) -> dict[str, Any] | None:
    if not frames:
        return None
    def key(f: dict[str, Any]) -> float:
        return (float(f.get("sharpness") or 0) * 0.6 + float(f.get("text_coverage") or 0) * 0.4
                if prefer_text else float(f.get("sharpness") or 0))
    return max(frames, key=key)
