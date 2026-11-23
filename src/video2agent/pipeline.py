from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from .config import Config
from .db import Database
from .errors import OcrFailed
from .lazy import LazyModule, lazy_call
from .links import canonical_video_url, extract_bvid, normalize_video_ref
from .net import assert_public_url
from .text import (
    count_unit_matches,
    coverage_score,
    find_sidecar,
    fts_match_query,
    has_kana,
    language_hint,
    leading_timecode,
    literal_terms,
    normalize_text,
    number_tokens,
    numeric_overlap,
    parse_subtitle_file,
    query_units,
    to_simplified,
    tokens_for_search,
    transcribe_with_faster_whisper,
    whisper_cache_state,
)
from .util import (
    Video2AgentError,
    ensure_dir,
    format_duration,
    format_timecode,
    not_ready_error,
    now_iso,
    stable_id,
)

# Read commands (search/overview/transcript/map/compare) do not need the media,
# network or OCR stacks. Import them through lazy module objects/callables so the
# CLI can start without requests/numpy/Pillow/opencv; the real import happens on
# first use and the public names remain patchable by tests.
np = LazyModule("numpy")
Image = LazyModule("PIL.Image")
cloud = LazyModule("video2agent.cloud")

verify_caption_audio = lazy_call("video2agent.caption_verify", "verify_caption_audio")
bilibili_captions = lazy_call("video2agent.captions", "bilibili_captions")
caption_content_mismatch = lazy_call("video2agent.captions", "caption_content_mismatch")
caption_track_trusted = lazy_call("video2agent.captions", "caption_track_trusted")
extract_audio = lazy_call("video2agent.media", "extract_audio")
extract_frame = lazy_call("video2agent.media", "extract_frame")
extract_frames_batch = lazy_call("video2agent.media", "extract_frames_batch")
probe = lazy_call("video2agent.media", "probe")
scene_times = lazy_call("video2agent.media", "scene_times")
bilibili_view_metadata = lazy_call("video2agent.sources", "bilibili_view_metadata")
fetch_metadata = lazy_call("video2agent.sources", "fetch_metadata")
resolve_source = lazy_call("video2agent.sources", "resolve_source")

attach_ocr = lazy_call("video2agent.visual", "attach_ocr")
build_ocr_tracks = lazy_call("video2agent.visual", "build_ocr_tracks")
ocr_available = lazy_call("video2agent.visual", "ocr_available")
ocr_image = lazy_call("video2agent.visual", "ocr_image")
ocr_state = lazy_call("video2agent.visual", "ocr_state")
ocr_summary = lazy_call("video2agent.visual", "ocr_summary")
plan_ocr_budget = lazy_call("video2agent.visual", "plan_ocr_budget")
select_ocr_frames = lazy_call("video2agent.visual", "select_ocr_frames")
text_coverage_for = lazy_call("video2agent.visual", "text_coverage_for")
visual_segments = lazy_call("video2agent.visual", "visual_segments")

Progress = Callable[[str, float, str], None]

VISUAL_WORDS = {
    "表格": "table_like", "table": "table_like",
    "图表": "chart_like", "chart": "chart_like", "graph": "chart_like", "plot": "chart_like",
    "ppt": "slide_like", "幻灯片": "slide_like", "slide": "slide_like", "课件": "slide_like",
    "代码": "screencast", "code": "screencast", "终端": "screencast", "terminal": "screencast",
    "动画": "animation", "animation": "animation", "演示": "screencast", "demo": "screencast",
}

SYNONYMS = {
    "表格": ["表"], "图表": ["图"], "幻灯片": ["slide"], "代码": ["code"],
    "录屏": ["演示"], "动画": ["animation"],
    # Small curated bilingual glossary (not a translator): enough for the
    # Chinese/English term pairs that show up in technical talks.
    "注意力": ["attention"], "准确率": ["accuracy", "precision"], "时间戳": ["timestamp"],
    "模型": ["model"], "结论": ["conclusion"], "公式": ["formula"], "证据": ["evidence"],
    # Cost and size are the two questions viewers ask most about a model talk;
    # the transcript rarely repeats the exact noun the user typed.
    "价格": ["成本", "费用", "收费", "计费", "多少钱", "贵", "便宜"],
    "成本": ["价格", "费用", "收费", "计费", "多少钱"],
    "费用": ["价格", "成本", "收费", "计费", "多少钱"],
    "计费": ["价格", "成本", "费用", "收费", "账单"],
    "收费": ["价格", "费用", "计费", "账单"],
    "定价": ["价格", "费用", "计费"],
    "账单": ["费用", "计费", "成本"],
    "付费": ["收费", "价格", "计费"],
    "多少钱": ["价格", "成本", "费用", "收费", "计费"],
    "参数": ["规模", "大小", "模型大小"],
    "小模型": ["小参数", "7B", "8B", "14B", "32B"],
    "字幕": ["subtitle", "caption"], "转录": ["transcript"],
    "attention": ["注意力"], "accuracy": ["准确率"], "precision": ["准确率"],
    "timestamp": ["时间戳"], "timestamps": ["时间戳"], "model": ["模型"],
    "conclusion": ["结论"], "formula": ["公式"], "evidence": ["证据"],
    "table": ["表格"], "chart": ["图表"], "slide": ["幻灯片"],
}

# A hit that survived only because a curated synonym matched has no BM25 or
# coverage signal left. In a two-video library FTS5 IDF is 0, so BM25 is ~0 and
# that hit used to come back at score 0.0 — "no match" for a row that was
# returned. Keep it visibly weak instead: above 0, below every measured hit
# (fuzzy fallback starts at 0.2).
SYNONYM_ONLY_FLOOR = 0.05


def _has_keyword(text: str, word: str) -> bool:
    """Match a keyword as a whole Latin word, or as a substring for CJK.

    Plain substring matching turned ``zzzznotaslideword`` into a ``slide``
    query and produced a fake visual hit; ASCII keywords must be whole words.
    """
    low = to_simplified(text or "").lower()
    w = to_simplified(word).lower()
    if not w:
        return False
    if w.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low) is not None
    return w in low


def _expand_terms(query: str) -> list[str]:
    """The curated aliases for the keys that occur in ``query``, in table order."""
    terms: list[str] = []
    for word, syns in SYNONYMS.items():
        if not _has_keyword(query, word):
            continue
        for syn in syns:
            if syn not in terms:
                terms.append(syn)
    return terms


def _expand_query(query: str) -> str:
    extra = _expand_terms(query)
    return query + (" " + " ".join(extra) if extra else "")


def _coverage_units(query: str, aliases: list[str]) -> list[str]:
    """Query units that count as evidence, aliases included, each term separate.

    Passing the expanded query to ``query_units`` joined every CJK character into
    one run, so ``计费 价格 成本`` produced cross-word trigrams (``计费价``,
    ``费价格``) that occur in no transcript. The "no unit appears anywhere" guard
    then deleted all 17 alias hits for ``计费``, while ``价格`` survived only by
    luck: its alias ``多少钱`` happened to form a real trigram.
    """
    units: list[str] = []
    for term in [query, *aliases]:
        for unit in query_units(term):
            if unit not in units:
                units.append(unit)
    return units[:64]


def _matched_terms(text: str, query: str, aliases: list[str] | None = None) -> list[str]:
    """Which query terms literally occur in ``text``, so an alias hit can say so."""
    matched: list[str] = []
    for term in (query, *(aliases or [])):
        if term and term not in matched and _has_keyword(text, term):
            matched.append(term)
    return matched


def _match_label(query: str, matched: list[str]) -> str:
    """Name how the text matched, without claiming a word that is not there."""
    if query in matched:
        return f"关键词「{query}」"
    if matched:
        return f"同义词「{matched[0]}」"
    return f"检索词元匹配（原文未含「{query}」）"


def _hit_why(modality: str, query: str, matched: list[str], extra: str = "") -> str:
    """How the hit matched; never claim the typed word occurs when it does not."""
    head = _match_label(query, matched)
    return f"{modality} 命中；{head}" + (f"；{extra}" if extra else "")


def _wanted_visual(query: str) -> list[str]:
    out = []
    for word, label in VISUAL_WORDS.items():
        if _has_keyword(query, word) and label not in out:
            out.append(label)
    return out


def _noop(stage: str, pct: float, msg: str) -> None:
    return None


def _asr_language_hint(language: str | None, resolved: dict[str, Any]) -> str | None:
    """The language handed to local ASR: an explicit choice, else a safe prior.

    With no language, faster-whisper guesses from the first 30 seconds of audio.
    A Chinese Bilibili video with loud background music came back as Japanese
    (measured 2026-11-15: 四千元台 / 五千元ちょい), which then cost the model a
    line-by-line read. A Chinese title on Bilibili is a far better prior than that
    guess; a title with kana keeps auto-detection so Japanese content is not
    forced into Chinese.
    """
    if language:
        return str(language)
    if str(resolved.get("language") or "") != "zh":
        return None
    if "bili" not in str(resolved.get("platform") or "").lower():
        return None
    if has_kana(str(resolved.get("title") or "")):
        return None
    return "zh"

def _warn(code: str, message: str, severity: str = "warn", remedy: str | None = None) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "remedy": remedy}


def _video_id_for(source: dict[str, Any]) -> str:
    return source["id"]


def _frame_thumb(gray: np.ndarray, size: int = 32) -> bytes:
    """Tiny grayscale fingerprint for duplicate detection.

    A perceptual hash is the wrong tool here: measured on six visually different
    slides, a 64-bit DCT pHash put all of them within 2-4 bits of each other (the page
    frame dominates the low band), so hash-based dedupe deleted real slides. Mean
    absolute difference on a 32x32 thumbnail separates them: different slides 0.016-
    0.022, the same slide re-encoded 0.0004-0.005.
    """
    from PIL import Image as _Image

    small = _Image.fromarray(gray).resize((size, size), _Image.Resampling.BILINEAR)
    return np.asarray(small, dtype=np.uint8).tobytes()


def _thumb_maxdiff(a: bytes, b: bytes) -> int:
    """Largest per-pixel difference between two thumbnails (0-255).

    A mean difference hides small text edits: adding one line to a slide moves the
    average by 0.0028 while the changed row differs by ~79. The maximum does not.
    """
    if not a or not b or len(a) != len(b):
        return 255
    left = np.frombuffer(a, dtype=np.uint8).astype(np.int16)
    right = np.frombuffer(b, dtype=np.uint8).astype(np.int16)
    return int(np.max(np.abs(left - right)))


def _dedupe_frames(
    frames: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    *,
    threshold: int = 8,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Drop near-identical frames inside one scene, keep the sharper one.

    Scoped per scene on purpose: a global pass collapses a static slide video to a
    single frame and leaves every scene without a representative. `threshold` is the
    largest tolerated pixel change on a 32x32 thumbnail: a re-encode moves it by ~2,
    a genuinely different slide by far more.
    """
    if len(frames) <= 1:
        return frames, []

    def scene_index(pts: int) -> int:
        for i, scene in enumerate(scenes):
            if scene["start_ms"] <= pts <= scene["end_ms"]:
                return i
        return -1

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    last_by_scene: dict[int, int] = {}
    for frame in frames:
        idx = scene_index(int(frame.get("pts_ms") or 0))
        anchor = last_by_scene.get(idx)
        if anchor is not None and _thumb_maxdiff(kept[anchor].get("_thumb"), frame.get("_thumb")) <= threshold:
            dropped.append(frame)
            if float(frame.get("sharpness") or 0) > float(kept[anchor].get("sharpness") or 0):
                dropped[-1] = kept[anchor]
                kept[anchor] = frame
            continue
        last_by_scene[idx] = len(kept)
        kept.append(frame)
    kept.sort(key=lambda f: int(f["pts_ms"]))
    return kept, dropped


def _stored_caption_mismatch(db: Database, video: dict[str, Any]) -> bool:
    """Detect a caption track already stored in the DB that no longer matches its video.

    The content gate runs during a fresh ingest, but an existing ready video used
    to be returned as-is by dedupe. That kept old wrong captions alive forever.
    """
    metrics = (video.get("meta") or {}).get("analysis_metrics") or {}
    if metrics.get("transcript_source") != "caption":
        return False
    # A WBI-sourced track is trusted for identity. The old trigram gate falsely
    # rejected the correct 46s DSH captions ("deep sick" vs the title's "dsh").
    if caption_track_trusted(metrics.get("caption_track")):
        return False
    segments = db.get_segments(str(video.get("id") or ""), limit=120)
    if not segments:
        return False
    meta = video.get("meta") or {}
    return caption_content_mismatch(segments, video.get("title"), meta.get("description"), meta.get("tags"))


_CLOUD_DESCRIPTION_MARKERS = (
    "in the image", "the image shows", "this image shows", "the picture shows", "i can see",
    "图中所", "图片中", "画面中", "图中是",
)


def _looks_like_cloud_description(text: str) -> bool:
    """A picture description is not on-screen text and must not be cited as OCR.

    Measured: DeepSeek-OCR answers an interview frame with "In the image, there
    is a man …" while the frame has no text at all. A long description has no
    line structure and starts with those markers; real page text is either short
    lines or Markdown headings.
    """
    lowered = text.lower()
    # Chinese captions are denser: 40 characters is already a full description.
    minimum = 30 if re.search(r"[\u3400-\u9fff]", text) else 80
    if len(text) < minimum:
        return False
    return any(marker in lowered for marker in _CLOUD_DESCRIPTION_MARKERS)


_GROUNDING_BOX_RE = re.compile(
    r"<\|ref\|>(.*?)<\|/ref\|><\|det\|>\[\[([\d.]+),\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)\]\]<\|/det\|>",
    re.S,
)
_MAX_GUIDED_BOXES = 12


def _parse_grounding_boxes(text: str) -> list[tuple[str, float, float, float, float]]:
    """DeepSeek-OCR grounding output: text plus a 0-1000 normalized box."""
    boxes = []
    for match in _GROUNDING_BOX_RE.finditer(text or ""):
        label = normalize_text(match.group(1))
        try:
            box = tuple(float(match.group(i)) for i in range(2, 6))
        except ValueError:
            continue
        if label and box[2] > box[0] and box[3] > box[1]:
            boxes.append((label, *box))
    return boxes


def _looks_like_table_hallucination(text: str) -> bool:
    """Reject the generic table DeepSeek-OCR invents on non-document crops."""
    low = (text or "").lower()
    return (
        ("category" in low and "value" in low)
        or "top 100" in low
        or "bottom 100" in low
    )


def _crop_text_supported(label: str, text: str) -> bool:
    """A crop read must agree with the grounding label, or be numeric only.

    Cloud OCR sometimes answers a crop with a plausible document/description
    instead of the line that was located. Keeping that text is how a green wall
    became a "paper screenshot" and a clock became "福". A crop is one line, so
    requiring token overlap with the located line (or a numeric-only value such
    as a price/time) rejects prose without discarding real numbers.
    """
    label_text = normalize_text(label or "").lower()
    text_text = normalize_text(text or "").lower()
    if not text_text:
        return False
    if re.fullmatch(r"[\d\s:.,%₽$€+\-–—/]+", text_text):
        return True
    if text_text in label_text or label_text in text_text:
        return True
    label_tokens = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", label_text))
    text_tokens = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", text_text))
    return bool(label_tokens & text_tokens)


def _cloud_ocr_guided(cfg: Config, image_path: str | Path) -> list[dict[str, Any]]:
    """Two-stage pure-cloud OCR: grounding finds boxes, crops are re-read.

    The first call asks DeepSeek-OCR for text plus boxes; each box is padded,
    upscaled and sent back to cloud OCR. Unlike blind 3x3 tiles, every crop
    contains text the model itself located, so it does not invent tables for
    empty background. No local OCR is involved.
    """
    try:
        with Image.open(image_path) as im:
            source = im.convert("RGB")
    except Exception:
        return []
    width, height = source.size
    grounded = cloud.ocr(cfg, image_path, prompt="<image>\n<|grounding|>OCR this image.")
    entries = _parse_grounding_boxes(str(grounded.get("text") or ""))
    if not entries:
        return _cloud_ocr_boxes(cfg, image_path)
    lines: list[str] = []
    seen: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="v2a_cloud_guided_") as tmp:
        for index, (label, x1, y1, x2, y2) in enumerate(entries[:_MAX_GUIDED_BOXES]):
            left = max(0, int(x1 / 1000.0 * width) - 8)
            top = max(0, int(y1 / 1000.0 * height) - 8)
            right = min(width, int(x2 / 1000.0 * width) + 8)
            bottom = min(height, int(y2 / 1000.0 * height) + 8)
            if right <= left or bottom <= top:
                continue
            crop = source.crop((left, top, right, bottom))
            crop = crop.resize((max(1, crop.width * 2), max(1, crop.height * 2)), Image.Resampling.LANCZOS)
            tile_path = Path(tmp) / f"guided_{index}.jpg"
            crop.save(tile_path, "JPEG", quality=95)
            text = ""
            try:
                result = cloud.ocr(cfg, tile_path)
                text = str(result.get("text") or "")
                if _looks_like_cloud_description(text) or _looks_like_table_hallucination(text):
                    text = ""
                elif text and not _crop_text_supported(label, text):
                    text = ""
            except Video2AgentError:
                text = ""
            except Exception:
                text = ""
            for line in (text or label).splitlines():
                clean = normalize_text(line)
                if clean and clean not in seen:
                    seen.add(clean)
                    lines.append(clean)
    if not lines:
        return []
    return [{
        "bbox": [0.0, 0.0, float(width), float(height)],
        "text": "\n".join(lines),
        "confidence": 0.0,
        "cloud": True,
        "guided": True,
        "boxes": len(entries),
    }]


def _cloud_ocr_boxes(cfg: Config, image_path: str | Path, *, tiles: bool = False) -> list[dict[str, Any]]:
    """Cloud OCR without boxes, unless `tiles` asks for grounding-guided crops."""
    if tiles:
        return _cloud_ocr_guided(cfg, image_path)
    result = cloud.ocr(cfg, image_path)
    text = normalize_text(str(result.get("text") or ""))
    if not text:
        return []
    if _looks_like_cloud_description(text):
        raise Video2AgentError(
            "E_CLOUD_OCR_DESCRIPTION",
            "云端返回的是画面描述，不是可引用的画面文字。",
            "改用本地 OCR（已自动回退）；只对确实有文字的帧用云端 OCR。",
        )
    try:
        with Image.open(image_path) as im:
            width, height = im.size
    except Exception:
        width, height = 1, 1
    return [{
        "bbox": [0.0, 0.0, float(width), float(height)],
        "text": text,
        "confidence": 0.0,
        "cloud": True,
    }]


def analyze(
    cfg: Config,
    source: str,
    *,
    profile: str = "auto",
    language: str | None = None,
    collection: str | None = None,
    force: bool = False,
    job_id: str | None = None,
    progress: Progress | None = None,
    reselect_ocr: bool = False,
) -> dict[str, Any]:
    progress = progress or _noop
    warnings: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    analysis_start = time.perf_counter()
    last_tick = analysis_start

    def tick(name: str) -> None:
        nonlocal last_tick
        now = time.perf_counter()
        metrics[name] = round(now - last_tick, 3)
        last_tick = now

    last_job_write = {"at": 0.0, "stage": ""}

    def step(stage: str, pct: float, msg: str, position_ms: int | None = None) -> None:
        progress(stage, pct, msg)
        if job_id:
            # `progress` already writes the job row (cli.py). Writing it again for every
            # ASR segment doubled the writes: 461 segments meant 922 rows and 6.04s of a
            # 20-minute ingest spent on duplicate updates. A stage change writes at once;
            # inside one stage, at most once per second.
            now = time.perf_counter()
            if stage == last_job_write["stage"] and now - last_job_write["at"] < 1.0:
                return
            last_job_write["at"] = now
            last_job_write["stage"] = stage
            with Database(cfg.db_path) as db:
                fields = {"state": "running", "stage": stage, "progress": pct, "message": msg, "updated_at": now_iso()}
                if position_ms is not None:
                    fields["position_ms"] = int(max(0, position_ms))
                db.update_job(job_id, **fields)

    # A repeat ingest of the same URL used to download/resolve first and only then
    # discover the video was already indexed (5-44s wasted, minutes for a large
    # file). The id for a URL source is derived from the input string, so look it
    # up before touching the network; a miss simply falls through to the old path.
    if not force:
        # Normalise the URL before the look-up: av/BV forms, b23 short links and
        # a missing trailing slash must all hit the same record, otherwise the
        # second ingest resolves and downloads the whole video again.
        try:
            from .links import extract_ref
            ref = extract_ref(str(source))
            # b23 tokens have no BV until resolved; resolve once here so the
            # second ingest hits the stored record instead of downloading again.
            if (ref or {}).get("kind") == "shortlink" and not (ref or {}).get("bvid"):
                try:
                    from .links import _resolve_shortlink
                    ref = extract_ref(_resolve_shortlink(
                        str(source), allow_private=bool(cfg.get("allow_private_urls")),
                    )) or ref
                except Exception:
                    pass
            lookup = str((ref or {}).get("url") or source).strip()
        except Exception:
            lookup = str(source).strip()
        provisional = stable_id("vid", lookup)
        with Database(cfg.db_path) as db:
            cached = db.get_video(provisional)
            if cached and cached.get("status") == "ready":
                if _stored_caption_mismatch(db, cached):
                    warnings.append(_warn(
                        "CAPTION_CONTENT_MISMATCH",
                        "旧库中的字幕内容与视频标题/简介不匹配，已自动重新分析该视频。",
                        severity="warning",
                        remedy="B 站返回了错误的字幕轨；这次会用 ASR 重新生成转写。",
                    ))
                    force = True
                else:
                    if collection:
                        db.add_to_collection(collection, provisional)
                    return overview(cfg, provisional)

    step("resolving", 0.02, "解析来源", 0)
    resolved = resolve_source(source, cfg)
    # One language prior for the whole analysis: captions do not need it, ASR does.
    asr_language = _asr_language_hint(language, resolved)
    tick("resolve")
    vid = _video_id_for(resolved)
    info = resolved.get("probe") or probe(resolved["path"])
    duration = int(info.get("duration_ms") or 0)
    max_min = int(cfg.get("max_duration_min") or 480)
    if duration > max_min * 60_000 and profile != "source_only":
        raise Video2AgentError("E_TOO_LONG", f"Video is {format_duration(duration)}, limit is {max_min} min.", "Raise max_duration_min in config or use a shorter clip.")

    step("probing", 0.06, "读取媒体信息")
    tick("probe")
    # A platform can hand back less video than it advertises (paywalled / preview /
    # truncated download). The library must say so: otherwise a citation after the
    # real end silently resolves to the wrong place.
    meta_duration_ms = int(round(float((resolved.get("meta") or {}).get("duration") or 0) * 1000))
    if meta_duration_ms and duration and profile != "source_only" and duration < meta_duration_ms * 0.9:
        warnings.append(_warn(
            "MEDIA_TRUNCATED",
            f"媒体只有 {format_duration(duration)}，平台标称 {format_duration(meta_duration_ms)}"
            f"（{duration / meta_duration_ms:.0%}）",
            remedy="多为充电专属/试看或下载截断：确认账号权限，或换清晰度/换源后 --force 重跑。",
        ))
    with Database(cfg.db_path) as db:
        existing = db.get_video(vid)
        if existing and existing.get("status") == "ready" and not force:
            if _stored_caption_mismatch(db, existing):
                warnings.append(_warn(
                    "CAPTION_CONTENT_MISMATCH",
                    "旧库中的字幕内容与视频标题/简介不匹配，已自动重新分析该视频。",
                    severity="warning",
                    remedy="B 站返回了错误的字幕轨；这次会用 ASR 重新生成转写。",
                ))
                force = True
            else:
                if collection:
                    db.add_to_collection(collection, vid)
                if job_id:
                    # A dedupe no-op is still a successful job for this video. Without
                    # this, the job sidecar has video_id=null and the card/model cannot
                    # tell which indexed video was reused.
                    db.update_job(job_id, video_id=vid, duration_ms=existing.get("duration_ms") or duration)
                return overview(cfg, vid)
        try:
            source_stat = os.stat(str(resolved["path"]))
            source_size, source_mtime_ns = int(source_stat.st_size), int(source_stat.st_mtime_ns)
        except OSError:
            source_size, source_mtime_ns = None, None
        db.upsert_video({
            "id": vid,
            "source_kind": resolved["kind"],
            "source_uri": resolved["uri"],
            "source_path": resolved["path"],
            "sha256": resolved.get("sha256"),
            "source_size": source_size,
            "source_mtime_ns": source_mtime_ns,
            # A re-ingest restores the media, so the release marker must clear.
            "media_released_at": None,
            "title": resolved.get("title") or Path(resolved["path"]).stem,
            "duration_ms": duration,
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "language": language or resolved.get("language"),
            "platform": resolved.get("platform") or "unknown",
            "status": "analyzing",
            "analysis_version": ANALYSIS_VERSION,
            "meta_json": json.dumps(resolved.get("meta") or {}, ensure_ascii=False),
            "warnings_json": json.dumps(warnings, ensure_ascii=False),
        })
        if collection:
            db.add_to_collection(collection, vid)
        if job_id:
            db.update_job(job_id, video_id=vid, duration_ms=duration)

    if profile == "source_only":
        with Database(cfg.db_path) as db:
            db.update_video(vid, status="source_ready")
        step("done", 1.0, "源文件已就绪")
        return {"ok": True, "video_id": vid, "path": resolved["path"], "title": resolved.get("title"), "profile": profile}

    # 1) Transcript: captions first, ASR fallback.
    step("transcribing", 0.10, "读取字幕/转写")
    segments: list[dict[str, Any]] = []
    caption_paths: list[Path] = []
    for s in resolved.get("subtitles") or []:
        p = Path(s)
        if p.exists():
            caption_paths.append(p)
    if not caption_paths:
        sc = find_sidecar(resolved["path"])
        if sc:
            caption_paths.append(sc)
    for cp in caption_paths:
        try:
            if cp.suffix.lower() == ".ass" or cp.suffix.lower() == ".ssa":
                continue
            parsed = parse_subtitle_file(cp, source="caption")
            if parsed:
                segments = parsed
                break
        except Exception as e:
            warnings.append(_warn("CAPTION_PARSE", f"字幕解析失败：{cp.name}: {e}", remedy="检查字幕编码/格式"))

    # A sidecar with only a handful of cues is not a transcript. The ToS SRT
    # covered 14 cues / 31s of a 180s film (17%): it was accepted with
    # transcript=true, then search said "engine" was absent and transcript
    # 0-20s said "no speech". A partial caption is a searchable clue, not a
    # complete transcript; fall through to ASR instead of claiming completeness.
    if segments and duration:
        covered = sum(max(0, int(s.get("end_ms") or 0) - int(s.get("start_ms") or 0)) for s in segments)
        coverage = covered / duration
        if coverage < 0.35:
            warnings.append(_warn(
                "TRANSCRIPT_PARTIAL",
                f"字幕只覆盖约 {coverage:.0%} 的时长（{len(segments)} 段），不足以当作完整转写；改用语音识别。",
                severity="warning",
                remedy="保留字幕作为线索，但用 ASR 生成完整转写；若确实没有语音，可忽略此提示。",
            ))
            segments = []

    # 1b) Bilibili CC. Uploader-verified subtitles beat local ASR by a wide
    # margin, but the player API hides them from anonymous requests, so this is
    # attempted explicitly and its outcome is reported either way.
    transcript_source = "caption" if segments else None
    caption_track: dict[str, Any] | None = None
    caption_check: dict[str, Any] | None = None
    caption_ai_fallback: dict[str, Any] | None = None
    # Which subtitle tracks the video offers (lan / lan_doc / kind), for metrics.
    caption_tracks: list[dict[str, Any]] = []
    bvid = extract_bvid(str(resolved.get("uri") or "")) if str(resolved.get("platform") or "").lower() == "bilibili" else None
    if not segments and bvid:
        try:
            meta = resolved.get("meta") or {}
            try:
                page = int(parse_qs(urlparse(str(resolved.get("uri") or "")).query).get("p", ["1"])[0])
            except (TypeError, ValueError):
                page = 1
            cc = bilibili_captions(
                bvid,
                cfg,
                duration_ms=int(duration),
                page=page,
                title=resolved.get("title"),
                description=meta.get("description"),
                tags=meta.get("tags"),
            )
            if cc.get("segments"):
                segments = cc["segments"]
                transcript_source = "caption"
                caption_track = cc.get("track")
                caption_tracks = cc.get("tracks") or []
                caption_ai_fallback = cc.get("ai_fallback") or None
                kind = (caption_track or {}).get("kind")
                step("transcribing", 0.14, "读取 AI 字幕" if kind == "ai" else "读取 UP 主字幕")
            elif not cc.get("logged_in"):
                warnings.append(_warn(
                    "CAPTION_LOGIN_REQUIRED",
                    "B 站字幕（含 AI 字幕、双语）需要登录才能读取；已回退语音识别。",
                    severity="info",
                    remedy="运行 video2agent biliauth --start，用手机 B 站扫码登录，然后 --force 重新 ingest；高级用户也可导出含 SESSDATA 的 cookies 并加 --cookies <文件>。",
                ))
            else:
                caption_tracks = cc.get("tracks") or caption_tracks
                if cc.get("reason") == "mismatch":
                    warnings.append(_warn(
                        "CAPTION_TRACK_MISMATCH",
                        "字幕轨与视频时长不匹配，已丢弃该轨，改用语音识别。",
                        severity="warning",
                        remedy="B 站返回了错误的字幕轨；重新 ingest 或改用本地 ASR。",
                    ))
                elif cc.get("reason") in ("empty", "no_tracks"):
                    warnings.append(_warn(
                        "CAPTION_UNAVAILABLE",
                        "这个视频没有可读的字幕轨（或 B 站限流未返回），已用语音识别。",
                        severity="info",
                        remedy="若 B 站播放器里能看到字幕，重新 ingest 一次；仍失败请检查登录是否过期。",
                    ))
        except Video2AgentError as e:
            warnings.append(_warn(e.code, e.message, remedy=e.remedy))
    # A caption track can belong to a different video even when its timing fits
    # (observed live: a 26-minute attention lecture carried iPhone-lens captions).
    # Timing cannot catch that; the title/description/tag units can.
    if segments and transcript_source == "caption":
        meta = resolved.get("meta") or {}
        # The signed WBI endpoint is trusted for track identity: it returned the
        # correct 18-line track for a 46s video where legacy /player/v2 returned
        # another video's 160-line track. Do not apply the old trigram gate to a
        # WBI track (it false-rejected the correct track because the spoken text
        # says "deep sick", not the title's "dsh"). Local sidecars and old cached
        # captions still go through the content gate.
        trusted_wbi = caption_track_trusted(caption_track)
        if not trusted_wbi and caption_content_mismatch(segments, resolved.get("title"), meta.get("description"), meta.get("tags")):
            if caption_ai_fallback and caption_ai_fallback.get("segments"):
                segments = caption_ai_fallback["segments"]
                caption_track = caption_ai_fallback.get("track")
                warnings.append(_warn(
                    "CAPTION_CONTENT_MISMATCH",
                    "人工字幕内容与视频标题/简介不匹配，已改用同视频的 AI 字幕轨。",
                    severity="warning",
                    remedy="人工字幕可能是错轨；AI 轨由音频生成，已优先保留，未触发整段 ASR。",
                ))
            else:
                warnings.append(_warn(
                    "CAPTION_CONTENT_MISMATCH",
                    "字幕内容与视频标题/简介不匹配，已丢弃该轨，改用语音识别。",
                    severity="warning",
                    remedy="B 站返回了错误或社区上传的错误字幕；重新 ingest 或改用本地 ASR。",
                ))
                segments = []
                transcript_source = None
                caption_track = None
    # A caption track can belong to a different video (observed live: a 46s
    # video carried 548 caption lines ending at 800s). Trimming that track keeps
    # the wrong words and labels them as this video's evidence. If a large share
    # of the track overruns the media, discard it and let ASR re-listen.
    if segments:
        media_end_ms = int(duration)
        far_overrun = [s for s in segments if int(s.get("end_ms") or 0) > media_end_ms * 1.5]
        if media_end_ms and far_overrun and len(far_overrun) >= max(3, len(segments) // 10):
            if caption_ai_fallback and caption_ai_fallback.get("segments"):
                segments = caption_ai_fallback["segments"]
                caption_track = caption_ai_fallback.get("track")
                warnings.append(_warn(
                    "CAPTION_TRACK_MISMATCH",
                    f"人工字幕轨超出视频时长（{len(far_overrun)} 条超出 1.5 倍），已改用同视频的 AI 字幕轨。",
                    severity="warning",
                    remedy="AI 轨已按媒体时长校验，避免用错轨的台词做证据。",
                ))
            else:
                warnings.append(_warn(
                    "CAPTION_TRACK_MISMATCH",
                    f"字幕轨与视频时长不匹配（{len(far_overrun)} 条超出 1.5 倍时长），已丢弃该轨，改用语音识别。",
                    severity="warning",
                    remedy="B 站返回了错误的字幕轨；重新 ingest 或改用本地 ASR。",
                ))
                segments = []
                transcript_source = None
                caption_track = None
    # Duration/metadata cannot catch a same-video joke track. For non-AI,
    # non-WBI human tracks, listen to two short windows and compare with the
    # caption lines covering them. A mismatch drops the track and lets the normal
    # ASR fallback re-listen; anything inconclusive keeps the caption.
    if segments and transcript_source == "caption" and caption_track and info.get("has_audio"):
        kind = str(caption_track.get("kind") or "")
        # AI tracks are generated from the audio; a human/community track is the
        # one that can be a joke even when its endpoint is the signed WBI one.
        trusted = kind == "ai"
        if not trusted:
            step("transcribing", 0.15, "核对字幕与语音")
            check = verify_caption_audio(
                resolved["path"],
                segments,
                cfg,
                int(duration),
                caption_lang=caption_track.get("lan"),
                temp_dir=cfg.derived_dir / vid,
            )
            caption_check = check
            if check.get("verdict") == "mismatch":
                if caption_ai_fallback and caption_ai_fallback.get("segments"):
                    check["action"] = "ai_fallback"
                    segments = caption_ai_fallback["segments"]
                    caption_track = caption_ai_fallback.get("track")
                    warnings.append(_warn(
                        "CAPTION_AUDIO_MISMATCH",
                        f"抽样听到的语音与人工字幕不一致（相似度 {check.get('score')}），已改用同视频的 AI 字幕轨。",
                        severity="warning",
                        remedy="人工字幕可能是整活/错轨；AI 轨由音频生成，已优先保留，未触发整段 ASR。",
                    ))
                else:
                    fallback_model = str(
                        (cfg.get("asr_model_fast") if profile == "fast" and cfg.get("asr_model_fast")
                         else cfg.get("asr_model"))
                        or "small"
                    )
                    try:
                        fallback_ready = bool(whisper_cache_state(fallback_model).get("cached"))
                    except Exception:  # noqa: BLE001 - cache inspection must not break ingest
                        fallback_ready = False
                    if fallback_ready:
                        warnings.append(_warn(
                            "CAPTION_AUDIO_MISMATCH",
                            f"抽样听到的语音与字幕不一致（相似度 {check.get('score')}），已丢弃字幕并改用语音识别。",
                            severity="warning",
                            remedy="字幕可能是整活/错轨；已用 ASR 重听（长视频会增加一次完整 ASR 时间）。",
                        ))
                        segments = []
                        transcript_source = None
                        caption_track = None
                    else:
                        # Dropping the caption without a cached fallback would leave the
                        # video with no transcript at all (or trigger a 500MB download).
                        # Keep it, but mark it explicitly untrusted.
                        check["fallback"] = "missing"
                        warnings.append(_warn(
                            "CAPTION_AUDIO_MISMATCH",
                            f"抽样语音与字幕不一致（相似度 {check.get('score')}），但本机没有可用的 ASR 模型缓存；暂保留字幕并标记为不可信。",
                            severity="warning",
                            remedy="准备好 ASR 模型后 --force 重新 ingest，或提供正确字幕。",
                        ))
            elif check.get("verdict") == "verified":
                warnings.append(_warn(
                    "CAPTION_AUDIO_VERIFIED",
                    f"抽样语音与字幕一致（相似度 {check.get('score')}，模型 {check.get('model')}）。",
                    severity="info",
                    remedy="",
                ))
            else:
                reason = str(check.get("reason") or "")
                score = check.get("score")
                # A normal short video / a user translation is not a failed trust
                # check; do not add an UNVERIFIED warning to every such ingest.
                if reason not in {"video_too_short", "caption_too_short", "language_not_checked"}:
                    if reason == "no_cached_asr_model":
                        message = "本机没有配置的轻量语音模型缓存，未做字幕-语音核对；保留字幕。"
                    elif reason == "no_speech":
                        message = "抽样窗口没有可比较的语音/字幕文本，未做字幕-语音核对；保留字幕。"
                    elif reason == "caption_language_differs":
                        message = "字幕语言与语音不同（可能是翻译），未做字幕-语音核对；保留字幕。"
                    elif reason == "low_confidence":
                        scored = len(check.get("window_scores") or [])
                        if scored < 2:
                            message = "只够核对一个窗口（另一个没有可用语音），无法下结论；保留字幕。"
                        else:
                            message = f"语音与字幕只有部分吻合（相似度 {score}），保留字幕但标记为未核对。"
                    elif reason in ("audio_unavailable", "asr_failed"):
                        message = "字幕-语音核对未完成；保留字幕。"
                    else:
                        message = "字幕样本不足，未做字幕-语音核对；保留字幕。"
                    remedies = {
                        "no_cached_asr_model": "先运行一次本地 ASR 或预下载轻量模型，让缓存就绪；不会为了核对单独下载模型。",
                        "no_speech": "抽样片段可能是音乐/静音；若字幕可疑，请提供正确字幕或手动 ASR。",
                        "caption_language_differs": "翻译轨不与同语言语音直接比对；保留字幕。",
                        "low_confidence": "字幕可能是改写/翻译，已保留；需要逐字严格核对时改用 ASR。",
                        "audio_unavailable": "检查视频音轨；字幕保留。",
                        "asr_failed": "检查 ASR 运行环境；字幕保留。",
                        "caption_too_short": "字幕样本太短；字幕保留。",
                    }
                    warnings.append(_warn(
                        "CAPTION_AUDIO_UNVERIFIED",
                        message,
                        severity="info",
                        remedy=remedies.get(reason, "字幕保留；核对未完成。"),
                    ))
    asr_failure: Video2AgentError | None = None
    # Whether ASR actually ran, and whether it heard any speech: without this,
    # a music-only video and an unconfigured ASR looked identical (both
    # NO_TRANSCRIPT + "download a model", which is wrong for the first case).
    asr_info: dict[str, Any] | None = None
    cloud_empty = False
    if not segments and info.get("has_audio"):
        try:
            audio = cfg.derived_dir / vid / "audio.wav"
            step("transcribing", 0.16, "提取音频")
            extract_audio(resolved["path"], audio)
            cloud_done = False
            if cloud.configured(cfg) and cloud.asr_enabled(cfg):
                step("transcribing", 0.18, "云端语音识别")
                cloud_started = time.perf_counter()
                try:
                    cloud_result = cloud.transcribe(cfg, audio)
                    segments = cloud_result.get("segments") or []
                    transcript_source = "cloud_asr"
                    cloud_done = bool(segments)
                    if cloud_done:
                        asr_info = {
                            "ran": True,
                            "source": "cloud_asr",
                            "model": cloud_result.get("model"),
                            "seconds": round(time.perf_counter() - cloud_started, 1),
                            "segments": len(segments),
                            "no_speech": False,
                        }
                        warnings.append(_warn(
                            "CLOUD_ASR",
                            f"使用 SiliconFlow 云端语音识别（{cloud_result.get('model')}）。",
                            severity="info",
                        ))
                except Exception as exc:
                    # A provider timeout/JSON error is not a Video2AgentError;
                    # without wrapping it the outer generic except ends the ASR
                    # branch and the local fallback never runs.
                    if not isinstance(exc, Video2AgentError):
                        exc = Video2AgentError(
                            "E_CLOUD_ASR",
                            f"云端语音识别失败：{exc}",
                            "检查网络/服务商后重试；本次会继续尝试本地 ASR。",
                        )
                    if exc.code == "E_CLOUD_ASR_EMPTY":
                        # The provider answered 200 with no text: that is "no
                        # speech" (music, ambience), not a reason to spend a
                        # local ASR run; a music-only video would pay it forever.
                        cloud_empty = True
                        asr_info = {
                            "ran": True,
                            "source": "cloud_asr",
                            "seconds": round(time.perf_counter() - cloud_started, 1),
                            "segments": 0,
                            "no_speech": True,
                        }
                        warnings.append(_warn(
                            "CLOUD_ASR_EMPTY",
                            "云端识别没有听到人声，已跳过本地 ASR。",
                            severity="info",
                            remedy="纯音乐/环境声属于正常；确有人声时换模型或检查音轨。",
                        ))
                    else:
                        warnings.append(_warn(exc.code, exc.message, remedy=exc.remedy))
                        asr_failure = exc
            if not cloud_done and not cloud_empty:
                # The model chosen in Settings is authoritative, including fast
                # runs: a user who selected large-v3/local path should get it.
                preferred_asr = cfg.get("asr_model") or "small"
                asr_model = preferred_asr
                # If the selected model is not cached, use another cached light
                # model instead of silently downloading a large one. This matters
                # for older installs where only `small` is on disk.
                if not whisper_cache_state(str(preferred_asr)).get("cached"):
                    for candidate in ("small", "base", "tiny"):
                        if candidate != preferred_asr and whisper_cache_state(candidate).get("cached"):
                            asr_model = candidate
                            warnings.append(_warn(
                                "ASR_MODEL_FALLBACK",
                                f"配置的 {preferred_asr} 未缓存，改用已缓存的 {candidate} 做本地转写。",
                            ))
                            break
                if not whisper_cache_state(str(asr_model)).get("cached"):
                    raise Video2AgentError(
                        "E_ASR_NOT_CONFIGURED",
                        "这条视频没有字幕，本机也没有可用的语音识别模型。",
                        f"运行 video2agent models download --model {asr_model}（约 464MB），或连接云端 ASR 后重试。",
                    )
                # A working local run answers the video; the earlier cloud error is
                # no longer why the transcript is missing.
                asr_failure = None
                step("transcribing", 0.20, f"正在听语音 · {format_timecode(0, millis=False)}")

                def _asr_progress(position_ms: int) -> None:
                    ratio = min(1.0, max(0.0, position_ms / max(1, duration)))
                    step("transcribing", 0.20 + 0.08 * ratio, f"正在听语音 · {format_timecode(position_ms, millis=False)}", position_ms)

                asr_started = time.perf_counter()
                asr_segments, lang = transcribe_with_faster_whisper(
                    audio,
                    model_size=str(asr_model or "small"),
                    device=str(cfg.get("asr_device") or "auto"),
                    compute_type=str(cfg.get("asr_compute_type") or "int8"),
                    language=asr_language,
                    beam_size=int(cfg.get("asr_beam_size") or 1),
                    word_timestamps=bool(cfg.get("asr_word_timestamps")),
                    cpu_threads=int(cfg.get("asr_cpu_threads") or 0),
                    progress=_asr_progress,
                    stage=lambda msg: step("transcribing", 0.18, msg),
                )
                asr_info = {
                    "ran": True,
                    "model": str(asr_model or "small"),
                    "seconds": round(time.perf_counter() - asr_started, 1),
                    "segments": len(asr_segments),
                    "no_speech": not asr_segments,
                    # What was requested vs what the model heard; a mis-detected
                    # transcript is otherwise impossible to diagnose afterwards.
                    "language": lang or asr_language,
                    "language_hint": asr_language,
                }
                if asr_language and not language:
                    warnings.append(_warn(
                        "ASR_LANGUAGE_HINT",
                        f"按标题语言用 {asr_language} 转写（自动检测曾把中文视频判成日语）。",
                        severity="info",
                        remedy="转写语言仍不对时，重跑 ingest 并传 language 指定语言。",
                    ))
                segments = asr_segments
                transcript_source = "asr"
                if lang and not language:
                    language = lang
            # The extracted wav is 39MB for a 20-minute video and nothing reads it again
            # (measured: 83% of the derived directory). Keep it only when the transcript
            # failed, where a retry benefits from not re-extracting.
            try:
                Path(audio).unlink(missing_ok=True)
            except OSError:
                pass
        except Video2AgentError as e:
            warnings.append(_warn(e.code, e.message, remedy=e.remedy))
            asr_failure = e
        except Exception as e:
            warnings.append(_warn("ASR_FAILED", f"语音识别失败：{e}", remedy="检查音轨或安装 faster-whisper"))
            asr_failure = Video2AgentError(
                "E_ASR_FAILED",
                f"语音识别失败：{e}",
                "检查音轨或重装 faster-whisper 后重试；这次没有生成转写。",
            )
    elif not info.get("has_audio"):
        warnings.append(_warn("NO_AUDIO", "视频没有音轨，只做画面分析。", severity="info", remedy="如需语音，提供带音轨的视频或字幕。"))
    blocked = _asr_blocked_error(has_audio=bool(info.get("has_audio")), segments=segments, failure=asr_failure)
    if blocked is not None:
        # The video has speech, no captions, and the ASR run failed. Returning
        # ready + an empty transcript is the fake success this tool must not do:
        # the caller gets ok:false and a command it can actually run.
        raise blocked
    if not segments:
        transcript_source = None
        # A video with no audio track cannot be transcribed. Telling the user
        # to download an ASR model is a dead end; NO_AUDIO already explains the
        # real cause. Only mention ASR when there *is* audio but no transcript.
        if info.get("has_audio"):
            if cloud_empty:
                warnings.append(_warn(
                    "NO_SPEECH",
                    "云端识别没有听到人声（纯音乐或环境声）；只能依赖 OCR 和画面。",
                    severity="warn",
                    remedy="不需要再跑 ASR；用 digest/frames 看画面，或提供字幕文件。",
                ))
            elif asr_info and asr_info.get("no_speech"):
                warnings.append(_warn(
                    "NO_SPEECH",
                    "语音识别已运行，但没有检测到人声（纯音乐或环境声）；只能依赖 OCR 和画面。",
                    severity="warn",
                    remedy="不需要再下载模型；用 digest/frames 看画面，或提供字幕文件。",
                ))
            else:
                warnings.append(_warn("NO_TRANSCRIPT", "没有可用字幕/转写；只能依赖 OCR 和画面。", severity="warn", remedy="打开 DSH 设置 → Video2Agent，连接云端 ASR 或下载本地语音模型（约 464MB）。"))

    for s in segments:
        s["text"] = normalize_text(s.get("text") or "")
        s["tokens"] = tokens_for_search(s["text"])
    # A transcript that overruns the media is usually the wrong transcript (measured:
    # two videos sharing another video's lines, one overrunning by 1035s). Trim and
    # say so rather than present it as this video's words.
    if segments:
        media_end_ms = int(duration)
        overrun = [s for s in segments if int(s.get("end_ms") or 0) > media_end_ms * 1.05]
        if overrun and media_end_ms:
            longest_s = int(max(int(s.get("end_ms") or 0) for s in overrun) / 1000)
            warnings.append(_warn(
                "TRANSCRIPT_OUT_OF_RANGE",
                f"{len(overrun)} 条转写超出媒体长度（最长 {longest_s}s），已截断",
                severity="warning",
                remedy="字幕轨可能不属于这个视频；换字幕源或改用 ASR 后 --force 重扫。",
            ))
            segments = [s for s in segments if int(s.get("start_ms") or 0) < media_end_ms]
            for s in segments:
                s["end_ms"] = min(int(s.get("end_ms") or 0), media_end_ms)
    segments = [s for s in segments if s["text"]]
    tick("transcript")

    # 2) Scenes. Full shot detection costs ~27s of a ~90s warm ingest and only
    # decides chapter boundaries and where the sampled frames land; `fast` uses a
    # fixed 60s grid instead (chapters degrade to time buckets, frames stay spread).
    step("scenes", 0.30, "检测镜头")
    scene_seconds: list[float] = []
    if profile == "fast":
        scene_seconds = [float(t) for t in range(60, max(61, duration // 1000), 60)]
    else:
        try:
            scene_seconds = scene_times(resolved["path"], threshold=0.05)
        except Exception as e:
            warnings.append(_warn("SCENE_FAILED", f"镜头检测失败，使用均匀分段：{e}", remedy="检查 ffmpeg"))
    scenes = _build_scenes(duration, scene_seconds)
    tick("scenes")

    # 3) Adaptive sampling + frames.
    step("sampling", 0.38, "采样关键帧")
    max_frames = {"fast": 40, "standard": 120, "deep": 240}.get(profile, 120)
    times = _sample_times(duration, scenes, max_frames)
    frame_dir = ensure_dir(cfg.derived_dir / vid / "frames")
    from .media import frame_features
    tasks = [(i, t, frame_dir / f"frame_{i:05d}.jpg") for i, t in enumerate(times)]

    def _extract_one(item: tuple[int, int, Path]) -> tuple[int, int, Path, str | None]:
        i, t, out = item
        try:
            extract_frame(resolved["path"], t, out, width=1280, fmt="jpg")
            return i, t, out, None
        except Exception as e:
            return i, t, out, str(e)

    extracted: dict[int, tuple[int, Path]] = {}
    workers = min(6, max(1, (os.cpu_count() or 4)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_extract_one, item) for item in tasks]
        for done, fut in enumerate(as_completed(futures), start=1):
            i, t, out, err = fut.result()
            if err:
                warnings.append(_warn("FRAME_FAILED", f"抽帧失败 {t}ms: {err}", severity="info"))
            else:
                extracted[i] = (t, out)
            if done % 20 == 0 or done == len(tasks):
                step("sampling", 0.38 + 0.18 * (done / max(1, len(tasks))), f"抽帧 {done}/{len(tasks)} · {format_timecode(t, millis=False)}", t)

    frames: list[dict[str, Any]] = []
    prev_gray = None
    for i in sorted(extracted):
        t, out = extracted[i]
        feats, prev_gray = frame_features(out, prev_gray)
        feats.update({"pts_ms": int(t), "path": str(out), "ocr_status": "pending"})
        feats["_thumb"] = _frame_thumb(prev_gray)
        frames.append(feats)
    tick("frames")
    if not frames:
        # The row was inserted before analysis. If extraction fails, leaving it
        # as "analyzing" made digest/export/list treat a 0-second phantom as a
        # citable video forever. Mark it failed; digest/export also require ready.
        with Database(cfg.db_path) as db:
            db.update_video(vid, status="failed")
        raise Video2AgentError("E_NO_FRAMES", "No frames could be extracted.", "Check the video codec or try a shorter clip.")
    # Near-identical frames cost disk and reading time for nothing. Dedupe per scene on
    # a thumbnail difference (see _dedupe_frames); the duplicate files are removed only
    # after the database has been rewritten, so a crash cannot leave rows pointing at a
    # deleted file.
    frames, dropped_frames = _dedupe_frames(frames, scenes)
    for frame in frames:
        frame.pop("_thumb", None)
    if dropped_frames:
        warnings.append(_warn(
            "FRAMES_DEDUPED",
            f"去掉 {len(dropped_frames)} 张同场景内近似重复的帧（{len(dropped_frames) + len(frames)} → {len(frames)}）",
            severity="info",
        ))

    # 4) OCR. Spread the budget across the timeline. `fast` keeps the cheap
    # duration rate; `standard` allows a bounded scene-aware raise (cost cap
    # 20); `deep` (or an explicit --ocr-budget) may spend the full cap.
    anchor_times: list[int] = []
    step("ocr", 0.60, "识别画面文字")
    # Cloud OCR is deliberately on-demand only. Ingest never sends a batch of
    # sampled frames to a paid image model; `evidence --at` is the only caller
    # that may use the cloud provider when the user enabled it.
    ocr_ok = ocr_available()
    local_ocr_config = str(cfg.get("ocr_local_config") or "") or None

    def _ocr_boxes(path: str) -> list[dict[str, Any]]:
        return ocr_image(path, config_path=local_ocr_config)

    duration_min = max(0.1, duration / 60000.0)
    ocr_rate = {"fast": 0.5, "standard": 1, "deep": 4}.get(profile, 1)
    ocr_cap = max(6, int(cfg.get("ocr_max_frames") or 60))
    if profile == "fast":
        ocr_budget = min(ocr_cap, max(6, int(round(duration_min * ocr_rate))))
    else:
        base_budget = max(6, int(round(duration_min * ocr_rate)))
        profile_cap = 20 if profile == "standard" else ocr_cap
        adaptive_cap = min(ocr_cap, max(base_budget, profile_cap))
        ocr_budget = plan_ocr_budget(
            duration,
            rate=ocr_rate,
            cap=adaptive_cap,
            n_scenes=len(scenes),
        )
    def _ocr_progress(done: int, total: int, pts_ms: int) -> None:
        step("ocr", 0.60 + 0.18 * (done / max(1, total)), f"识别画面文字 {done}/{total} · {format_timecode(pts_ms, millis=False)}", pts_ms)

    # Re-read the same moments a previous run OCR'd, so the same question does not
    # get a different answer after a re-ingest (measured: 50 hits -> 0). Only an
    # explicit --reselect-ocr picks a fresh spread.
    anchor_times: list[int] = []
    if profile == "auto":
        # Lazy mode (the default): no bulk OCR. Text is read the first time a moment
        # is actually asked for (evidence -> on-demand OCR, which also stores the
        # anchor). This keeps ingest to captions/ASR + sampling and costs nothing for
        # frames nobody looks at.
        ocr_budget = 0
        ocr_tracks = []
        warnings.append(_warn(
            "OCR_ON_DEMAND_MODE",
            "画面文字按需识别：第一次查看某个时间点时才读那一帧。",
            severity="info",
        ))
    else:
        if not reselect_ocr:
            with Database(cfg.db_path) as adb:
                anchor_times = adb.get_ocr_anchors(vid)
        if anchor_times:
            step("ocr", 0.60, f"沿用上次画面锚点 · {len(anchor_times)} 帧")
        attach_ocr(frames, max_frames=ocr_budget, progress=_ocr_progress, times=anchor_times or None, ocr_fn=_ocr_boxes, ocr_config_path=local_ocr_config)
        if not ocr_ok:
            warnings.append(_warn("OCR_UNAVAILABLE", "未安装 OCR，画面文字不可用。", remedy="pip install \"video2agent[ocr]\""))
        ocr_tracks = build_ocr_tracks(frames)
        if not ocr_ok:
            ocr_tracks = []
        else:
            read_times = [int(f["pts_ms"]) for f in frames if f.get("ocr_status") in ("ok", "empty")]
            # Kept on the side: `clear_video_analysis` runs later in this ingest and
            # deletes the anchors table, so writing them here left zero anchors.
            anchor_times = list(read_times)
    tick("ocr")
    ocr_stats = ocr_summary(frames)
    if ocr_stats["failed"]:
        # A failed read is not "the frame has no text". Say it out loud, and keep
        # text_coverage None so no label is invented from it.
        warnings.append(_warn(
            "OCR_FAILED",
            f"{ocr_stats['failed']} 帧画面文字识别失败（不是「这一帧没有文字」）。",
            severity="warning",
            remedy="检查本机 OCR 模型/依赖后重新 ingest --force；也可先 evidence --at 重试该时刻。",
        ))

    # 5) Visual map.
    step("indexing", 0.78, "生成视觉结构图")
    vsegs = visual_segments(scenes, frames, ocr_ok=ocr_ok)
    tick("visual")
    step("indexing", 0.84, "写入索引")

    metrics.update({
        "n_frames": len(frames),
        "n_ocr_frames": ocr_stats["read"],
        "n_ocr_failed": ocr_stats["failed"],
        "ocr_state": ocr_state(ocr_stats, on_demand=(profile == "auto")),
        "ocr_budget": ocr_budget,
        "ocr_cap": ocr_cap,
        "n_ocr_tracks": len(ocr_tracks),
        "n_scenes": len(scenes),
        # Without this the library mixes 40-frame and 120-frame records with no way to
        # tell why two videos look different. It is the first thing to read when frames
        # or scenes look thin.
        "profile": profile,
        "max_frames": max_frames,
        "analysis_version": ANALYSIS_VERSION,
        # Where the transcript came from, so a caller can say "UP 主字幕" instead
        # of implying every word was machine-heard.
        "transcript_source": transcript_source or ("none" if not segments else "unknown"),
        "asr": asr_info,
        "caption_track": caption_track,
        "caption_tracks": caption_tracks,
        "caption_check": caption_check,
    })
    metrics["total_s"] = round(time.perf_counter() - analysis_start, 3)
    with Database(cfg.db_path) as db:
        db.clear_video_analysis(vid)
        db.insert_segments(vid, segments)
        db.insert_scenes(vid, scenes)
        db.insert_frames(vid, frames)
        db.insert_ocr_tracks(vid, ocr_tracks)
        if anchor_times:
            db.set_ocr_anchors(vid, anchor_times)
        db.insert_visual_segments(vid, vsegs)
        lang = language or _detect_language(segments) or info.get("language")
        meta = dict(resolved.get("meta") or {})
        meta["analysis_metrics"] = metrics
        db.update_video(vid, status="ready", language=lang, warnings_json=json.dumps(warnings, ensure_ascii=False),
                        meta_json=json.dumps(meta, ensure_ascii=False))
    # Only now, after the rows that reference frames have been rewritten, is it safe
    # to delete the duplicates.
    for frame in dropped_frames:
        try:
            Path(str(frame.get("path"))).unlink(missing_ok=True)
        except OSError:
            pass
    step("done", 1.0, "完成")
    result = overview(cfg, vid)
    result["warnings"] = warnings
    return result


def _detect_language(segments: list[dict[str, Any]]) -> str | None:
    text = " ".join(s.get("text", "") for s in segments[:50])
    return language_hint(text) if text else None


def _build_scenes(duration_ms: int, cuts: list[float]) -> list[dict[str, Any]]:
    duration_ms = max(1, int(duration_ms))
    points = [0]
    for t in cuts:
        ms = int(round(float(t) * 1000))
        if 100 < ms < duration_ms - 100:
            points.append(ms)
    points = sorted(set(points))
    scenes = []
    for i, start in enumerate(points):
        end = points[i + 1] if i + 1 < len(points) else duration_ms
        if end <= start:
            continue
        # Merge micro-scenes caused by motion/flashes; keep real slide cuts.
        if scenes and end - start < 1200:
            scenes[-1]["end_ms"] = end
            scenes[-1]["keyframe_ms"] = min(end - 1, scenes[-1]["start_ms"] + 300)
            continue
        scenes.append({
            "start_ms": start,
            "end_ms": end,
            "cut_score": None,
            "keyframe_ms": min(end - 1, start + min(300, max(0, end - start - 1))),
        })
    return scenes


def _sample_times(duration_ms: int, scenes: list[dict[str, Any]], max_frames: int) -> list[int]:
    duration_ms = max(1, int(duration_ms))
    times: list[float] = []
    for s in scenes:
        times.append(s["start_ms"] / 1000.0 + 0.25)
        mid = (s["start_ms"] + s["end_ms"]) / 2000.0
        times.append(mid)
    step = duration_ms / 1000.0 / max(1, max_frames)
    t = step / 2.0
    while t < duration_ms / 1000.0:
        times.append(t)
        t += step
    out: list[int] = []
    for t in sorted(times):
        ms = int(round(max(0.0, min(duration_ms - 1, t * 1000))))
        if not out or ms - out[-1] >= 750:
            out.append(ms)
    if len(out) > max_frames:
        # Preserve first/last and evenly thin the rest.
        idx = [round(i * (len(out) - 1) / (max_frames - 1)) for i in range(max_frames)]
        out = [out[i] for i in sorted(set(idx))]
    return out


def _asr_blocked_error(*, has_audio: bool, segments: list[dict[str, Any]],
                       failure: Video2AgentError | None) -> Video2AgentError | None:
    """The error that stops an ingest from returning an empty "ready" transcript.

    A silent video with no speech is fine: there is nothing to transcribe. A video
    with speech whose ASR never ran (missing model, cloud failure) is not fine;
    saying `ready` with zero segments is the fake success this guards against.
    """
    if segments or not has_audio or failure is None:
        return None
    return Video2AgentError(
        failure.code,
        f"没有生成转写：{failure.message}",
        failure.remedy or "运行 video2agent models download --model small，或连接云端 ASR 后重试。",
    )


def _visual_index_reason(state: str, read: int, failed: int, *,
                            total: int = 0, remaining: int | None = None) -> str:
    if state == "complete":
        return f"已建立画面索引（{read} 帧）"
    if state == "partial":
        if failed:
            return f"部分画面已索引（{read} 帧读成功，{failed} 帧读取失败）"
        if remaining:
            return f"部分画面已索引（还有 {remaining} 帧待读）"
        if total and read < total:
            return f"部分画面已索引（{read}/{total} 帧）"
        return f"部分画面已索引（按需读过 {read} 帧）"
    if state == "on_demand":
        return "默认按需识别，尚未建立全片画面索引"
    if state == "failed":
        return f"{failed} 帧画面文字读取失败，索引未建立"
    if state == "unavailable":
        return "未安装 OCR，无法建立画面索引"
    return "还没有读过任何画面文字"


def _visual_index_info(frame_counts: dict[str, int], metrics: dict[str, Any]) -> dict[str, Any]:
    """Whether on-screen text has been indexed, and why not, for UI and callers.

    Lazy `auto` (the default) reads nothing until a moment is asked for, a failed
    read is not an empty index, and an explicit `ocr-index` run is a complete pass.
    Old records have no `visual_index` metric: their frame statuses are enough.
    """
    read = int(frame_counts.get("ok", 0)) + int(frame_counts.get("empty", 0))
    failed = int(frame_counts.get("failed", 0))
    unavailable = int(frame_counts.get("unavailable", 0))
    total = sum(int(n) for n in frame_counts.values()) if frame_counts else 0
    profile = str(metrics.get("profile") or "")
    recorded = metrics.get("visual_index") if isinstance(metrics.get("visual_index"), dict) else None
    remaining = recorded.get("remaining") if recorded else None
    remaining_frames = int(remaining) if isinstance(remaining, int) else None
    # Frames that exist but were never read are still to read. Older records did
    # not store a count, and "partial" with no number reads as "we don't know how
    # much is left" when read/total already say it. The state rule below keeps
    # using the recorded value, so this only fills the reported count.
    remaining_reported = remaining_frames
    if remaining_reported is None and total:
        remaining_reported = max(0, total - read - failed - unavailable)
    if failed and not read:
        state = "failed"
    elif read and failed:
        state = "partial"
    elif read:
        # A pass that stopped at the cap, or an ingest that sampled more frames
        # than it read, is a partial index. Only a recorded pass with nothing left
        # to read (and no failures) may call itself "complete".
        if recorded is not None:
            complete = recorded.get("state") == "complete" and remaining_frames == 0
        else:
            complete = (total > 0 and read >= total
                        and profile in {"fast", "standard", "deep", "source_only"})
        state = "complete" if complete else "partial"
    elif unavailable:
        state = "unavailable"
    elif profile == "auto" or recorded:
        state = "on_demand"
    else:
        state = "unmeasured"
    reason = _visual_index_reason(state, read, failed, total=total, remaining=remaining_reported)
    return {
        "indexed": read > 0,
        "state": state,
        "reason": reason,
        "read_frames": read,
        "failed_frames": failed,
        "total_frames": total,
        "remaining_frames": remaining_reported,
    }


def overview(cfg: Config, video_id: str) -> dict[str, Any]:
    with Database(cfg.db_path) as db:
        video = db.get_video(video_id)
        if not video:
            raise Video2AgentError("E_NOT_FOUND", f"Video not found: {video_id}", "Run video2agent list.")
        counts = db.counts(video_id)
        scenes = db.get_scenes(video_id)
        visual = db.get_visual_segments(video_id, limit=500)
        # Chapters bucket the timeline by 300s; each bucket needs the transcript that
        # falls inside it. Reading only the first 50 segments left every bucket after
        # the first with no ASR text (3 of 4 chapters became "第 N 段").
        segments = db.get_segments(video_id, limit=5000)
        stored_caption_bad = _stored_caption_mismatch(db, video)
        ocr_all = db.get_ocr_tracks(video_id, limit=800)
        # Coverage and frame presence need reads after this block; do them while
        # the connection is still open. They used to run on a closed Database and
        # were silently swallowed, so transcript_coverage was always 0.0.
        coverage_segments = db.get_segments(video_id, limit=100000)
        frame_heads = db.get_frames(video_id, limit=5)
        # How the frames' text was actually read: read / empty / failed / never read.
        ocr_status_counts = db.frame_ocr_counts(video_id)
    labels: dict[str, int] = {}
    for v in visual:
        labels[v["label"]] = labels.get(v["label"], 0) + 1
    # How much of the visual map is actually known: a segment whose label is
    # `unknown` (no frame sampled, or no frame read) is not a description.
    visual_known = sum(n for label, n in labels.items() if label != "unknown")
    visual_coverage = round(visual_known / len(visual), 3) if visual else 0.0
    # Never build chapter titles from a caption track we just declared invalid.
    # Keep scene/OCR/timecode titles instead of leaking "手机镜头膜" into an
    # attention lecture's overview.
    chapters = _chapters(scenes, [] if stored_caption_bad else segments, ocr_all)
    preview_lines: list[str] = []
    preview_chars = 0
    preview_next: int | None = None
    if not stored_caption_bad:
        for seg in segments:
            text = str(seg.get("text") or "").strip()
            if not text:
                continue
            line = f"{format_timecode(int(seg.get('start_ms') or 0), millis=False)} {text}"
            if preview_lines and preview_chars + len(line) + 1 > 1600:
                preview_next = int(seg.get("start_ms") or 0)
                break
            preview_lines.append(line)
            preview_chars += len(line) + 1
    ocr_preview_lines: list[str] = []
    ocr_preview_chars = 0
    for track in ocr_all:
        text = str(track.get("text") or "").strip()
        if not text:
            continue
        line = f"{format_timecode(int(track.get('start_ms') or 0), millis=False)} {text}"
        if ocr_preview_lines and ocr_preview_chars + len(line) + 1 > 1600:
            break
        ocr_preview_lines.append(line)
        ocr_preview_chars += len(line) + 1
    if preview_lines:
        # A normal transcript is more useful than duplicated slide fragments; only
        # carry OCR preview when there is no readable speech.
        ocr_preview_lines = []
        ocr_preview_chars = 0
    # Coverage, not presence: a transcript covering the first 2% of an 18-minute video
    # is not "transcript available" (measured: zero warnings for exactly that case).
    media_ms = int(video.get("duration_ms") or 0)
    covered_ms = 0
    for seg in coverage_segments:
        start = max(0, int(seg.get("start_ms") or 0))
        end = int(seg.get("end_ms") or start)
        covered_ms += max(0, end - start)
    transcript_coverage = round(min(1.0, covered_ms / media_ms), 3) if media_ms else None
    frames_present = any(Path(str(f.get("path") or "")).exists() for f in frame_heads) if frame_heads else counts["frames"] > 0
    metrics = dict((video.get("meta") or {}).get("analysis_metrics") or {})
    ocr_read_frames = int(ocr_status_counts.get("ok", 0)) + int(ocr_status_counts.get("empty", 0))
    ocr_failed_frames = int(ocr_status_counts.get("failed", 0))
    ocr_unavailable_frames = int(ocr_status_counts.get("unavailable", 0))
    on_demand_ocr = (
        str(metrics.get("profile") or "") == "auto"
        or ("ocr_budget" in metrics and int(metrics.get("ocr_budget") or 0) == 0)
    )
    ocr_state_value = ocr_state({
        "read": ocr_read_frames,
        "failed": ocr_failed_frames,
        "unavailable": ocr_unavailable_frames,
    }, on_demand=on_demand_ocr and counts["ocr_tracks"] == 0)
    visual_index = _visual_index_info(ocr_status_counts, metrics)
    if visual_index["state"] == "partial" and ocr_state_value == "indexed":
        # `ocr: true` says some tracks exist; `indexed` claimed the whole video was
        # read. A capped ocr-index pass is partial and must say so here too.
        ocr_state_value = "partial"
    capabilities = {
        "transcript": counts["segments"] > 0 and not stored_caption_bad,
        "transcript_coverage": transcript_coverage,
        "ocr": counts["ocr_tracks"] > 0,
        # `ocr` alone says whether any track exists; `ocr_state` says why. Without
        # it, "not indexed yet", "read failed" and "no text" all looked like false.
        "ocr_state": ocr_state_value,
        "ocr_indexed": counts["ocr_tracks"] > 0,
        "ocr_read_frames": ocr_read_frames,
        "ocr_failed_frames": ocr_failed_frames,
        # One answer for "is the on-screen text indexed?" plus why not.
        "visual_indexed": visual_index["indexed"],
        "visual_index_state": visual_index["state"],
        # A map of `unknown` labels is not a map.
        "visual_map": visual_known > 0,
        "frames": frames_present,
        "media": bool(video.get("source_path") and Path(str(video["source_path"])).exists()),
        # Media was reclaimed by the cache policy; the text index is still here.
        "media_released": bool(video.get("media_released_at")),
    }
    if visual and visual_known == 0:
        visual_warning = True
    else:
        visual_warning = False
    meta = video.get("meta") or {}
    declared_duration_ms = int(round(float(meta.get("duration") or 0) * 1000)) or None
    warnings = list(video.get("warnings") or [])
    if stored_caption_bad:
        warnings.append(_warn(
            "CAPTION_CONTENT_MISMATCH",
            "现有转写来自一条与视频标题不匹配的字幕轨，已被标记为不可用。",
            severity="warning",
            remedy="运行 video2agent ingest <source> --force 重新分析；这次会拒绝错字幕并用 ASR 重建转写。",
        ))
    # The stored analysis can be older than the code that reads it: before 0.2 the
    # visual labels were wrong for every auto-profile video and frames were sampled
    # and deduped differently. Say so instead of presenting it as current.
    stored_version = str(video.get("analysis_version") or "")
    if stored_version != ANALYSIS_VERSION:
        warnings.append(_warn(
            "STALE_ANALYSIS",
            f"这条记录是旧版分析（{stored_version or '未知'}），当前版本 {ANALYSIS_VERSION}："
            "画面标签/帧采样可能与新结果不同。",
            remedy="video2agent ingest <source> --force 重扫即可更新（会重新抽帧与判定）。",
            severity="info",
        ))
    ocr_warning_codes = {str((w or {}).get("code") or "") for w in warnings}
    if ocr_state_value == "failed" and "OCR_FAILED" not in ocr_warning_codes:
        warnings.append(_warn(
            "OCR_FAILED",
            f"{ocr_failed_frames} 帧画面文字读取失败：这不是「没有文字」，也不能据此说视频里没有这些字。",
            severity="warning",
            remedy="检查本机 OCR 模型/依赖后重新 ingest --force；也可先用 evidence --at 现场重试该时刻。",
        ))
    elif ocr_state_value == "unavailable" and "OCR_UNAVAILABLE" not in ocr_warning_codes:
        warnings.append(_warn(
            "OCR_UNAVAILABLE",
            "未安装 OCR，画面文字读不出来（不是没有文字）。",
            severity="warning",
            remedy="pip install \"video2agent[ocr]\" 后重新 ingest。",
        ))
    elif ocr_state_value == "on_demand" and counts["ocr_tracks"] == 0 and "OCR_ON_DEMAND_MODE" not in ocr_warning_codes:
        warnings.append(_warn(
            "OCR_NOT_INDEXED",
            "画面文字尚未建立索引：默认按需识别，搜索画面文字前要先读取那一刻。",
            severity="info",
            remedy="先运行 video2agent ocr-index <视频 ID> --dry-run 看预计帧数和耗时，再运行 video2agent ocr-index <视频 ID>。",
        ))
    if video.get("media_released_at") and "MEDIA_RELEASED" not in {str((w or {}).get("code") or "") for w in warnings}:
        warnings.append(_warn(
            "MEDIA_RELEASED",
            "原片和抽帧已按缓存策略清理；转写和画面文字仍可搜索。",
            severity="info",
            remedy="要看原片或取帧时，重新 ingest 一次即可恢复。",
        ))
    if visual_warning:
        warnings.append(_warn(
            "VISUAL_UNMEASURED",
            "画面类型未判定：没有任何画面被识读过文字，标签一律为 unknown。",
            remedy="换 deep 档重新 ingest 才会生成整条视觉标签；evidence --at 只按需读那一帧文字，不会更新视觉地图。",
            severity="info",
        ))
    # Derive the truncation warning for records ingested before it existed, so old
    # libraries report the same honesty as new ingests.
    media_ms = int(video.get("duration_ms") or 0)
    if (declared_duration_ms and media_ms and media_ms < declared_duration_ms * 0.9
            and not any((w or {}).get("code") == "MEDIA_TRUNCATED" for w in warnings)):
        warnings.append(_warn(
            "MEDIA_TRUNCATED",
            f"媒体只有 {format_duration(media_ms)}，平台标称 {format_duration(declared_duration_ms)}"
            f"（{media_ms / declared_duration_ms:.0%}）",
            remedy="多为充电专属/试看或下载截断：确认账号权限，或换清晰度/换源后 --force 重跑。",
        ))
    if stored_caption_bad or not counts["segments"]:
        # Older records can still say "asr" while holding zero segments. Do not let
        # the card label an empty result as a successful speech transcript.
        metrics["transcript_source"] = "none"
    return {
        "ok": True,
        "schema_version": "1.0",
        "video_id": video_id,
        "title": video.get("title"),
        # The card needs these before the user asks for evidence: a direct-link row
        # backfills from overview while the job runs, and the stored platform meta
        # already carries them. Keeping them out forced every cover through a
        # separate resolve call and left the row saying "视频".
        "uploader": meta.get("uploader") or meta.get("channel"),
        "cover_url": meta.get("thumbnail") or meta.get("cover_url"),
        "source": {"kind": video.get("source_kind"), "uri": video.get("source_uri"), "platform": video.get("platform")},
        "duration_ms": video.get("duration_ms"),
        "duration": format_duration(video.get("duration_ms")),
        # What the platform claimed, so a truncated download is visible in the data
        # and not only in a warning string.
        "declared_duration_ms": declared_duration_ms,
        "declared_duration": format_duration(declared_duration_ms) if declared_duration_ms else None,
        "exclusive": bool(meta.get("is_upower_exclusive")),
        "language": video.get("language"),
        "status": video.get("status"),
        "counts": counts,
        "chapters": chapters,
        "transcript_preview": "\n".join(preview_lines),
        "transcript_preview_chars": preview_chars,
        "transcript_preview_truncated": preview_next is not None,
        "transcript_preview_next_start_ms": preview_next,
        "ocr_preview": "\n".join(ocr_preview_lines),
        "ocr_preview_chars": ocr_preview_chars,
        "visual": {
            "labels": labels,
            "segments": len(visual),
            "known": visual_known,
            "coverage": visual_coverage,
            # Where the text map stands: read / failed / never read. A bare
            # `coverage: 0.0` used to read as "this video has no text".
            "ocr": {
                "state": ocr_state_value,
                "read": ocr_read_frames,
                "failed": ocr_failed_frames,
                "unread": max(0, int(counts["frames"]) - ocr_read_frames - ocr_failed_frames),
            },
        },
        "capabilities": capabilities,
        "visual_indexed": visual_index["indexed"],
        "visual_index": visual_index,
        "metrics": metrics,
        "warnings": warnings,
        "citation": f"《{video.get('title')}》 00:00:00",
    }


def resolve_info(cfg: Config, url: str) -> dict[str, Any]:
    ref = normalize_video_ref(url, timeout=8.0, allow_private=bool(cfg.get("allow_private_urls")))
    if ref is None:
        if re.search(r"(?:^|//)(?:[\w.-]+\.)?douyin\.com/|v\.douyin\.com/", str(url)):
            raise Video2AgentError(
                "E_DOUYIN_ID",
                "抖音链接里没有可识别的视频 id",
                "使用 douyin.com/video/<数字id>、douyin.com/discover?modal_id=<id> 或 v.douyin.com 短链；用户主页请用 video2agent douyin profile。",
            )
        raise Video2AgentError(
            "E_URL",
            "resolve expects a video URL, a BV id, or an av id",
            "Paste a Bilibili URL, 'BV1xx411c7mD', an av link, a b23.tv short link, or a Douyin video URL.",
        )
    if ref.get("platform") == "douyin":
        from .douyin import get_item, is_image_post

        item = get_item(
            str(ref["aweme_id"]),
            cache_dir=cfg.home / "cache" / "douyin",
        )
        if is_image_post(item):
            raise Video2AgentError(
                "E_DOUYIN_IMAGE",
                "这是抖音图文作品（图片合集），没有可分析的视频",
                "贴视频作品的链接（douyin.com/video/<数字id> 或 v.douyin.com 短链）。",
            )
        duration_ms = item.get("duration_ms")
        author = item.get("author") or {}
        return {
            "ok": True,
            "kind": "video-link",
            "url": ref["url"],
            "platform": "douyin",
            "title": item.get("title"),
            "uploader": author.get("nickname") or author.get("unique_id"),
            "duration_ms": duration_ms,
            "duration": format_duration(duration_ms),
            "cover_url": item.get("cover_url"),
            "description": (item.get("description") or "")[:500],
            "bvid": None,
            "av_id": None,
            "douyin_id": ref["aweme_id"],
            "input_kind": ref.get("input_kind"),
        }
    target = ref["url"]
    assert_public_url(target, allow_private=bool(cfg.get("allow_private_urls")))
    meta = bilibili_view_metadata(ref, cfg) or fetch_metadata(target, cfg)
    duration_ms = int(round(float(meta.get("duration") or 0) * 1000)) or None
    cover = meta.get("thumbnail")
    if isinstance(cover, str) and cover.startswith("http://"):
        cover = "https://" + cover[len("http://"):]
    # Prefer the canonical BV URL whenever we know it, so an av link or a
    # b23.tv short link resolves to the same stable url field.
    bvid = ref.get("bvid")
    if not bvid:
        bvid = extract_bvid(str(meta.get("webpage_url") or ""))
    out_url = canonical_video_url(bvid) if bvid else (meta.get("webpage_url") or target)
    return {
        "ok": True,
        "kind": "video-link",
        "url": out_url,
        "platform": (meta.get("extractor_key") or meta.get("extractor") or "").lower() or None,
        "title": meta.get("title"),
        "uploader": meta.get("uploader") or meta.get("channel"),
        "duration_ms": duration_ms,
        "duration": format_duration(duration_ms),
        "cover_url": cover,
        "description": (meta.get("description") or "")[:500],
        "bvid": bvid,
        "av_id": ref.get("av_id"),
        "input_kind": ref.get("input_kind"),
    }


_TIMECODE_NOISE = re.compile(r"\b\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?\b|\b\d+\s*m\s*\d+\s*s\b|\b\d+\s*分\s*\d+\s*秒\b")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _clean_title(text: str, limit: int = 26) -> str:
    """Turn a raw ASR/OCR line into something usable as a chapter title."""
    clean = _TIMECODE_NOISE.sub(" ", str(text or ""))
    clean = re.sub(r"\s+", " ", clean).strip(" ，。、·-—|:：")
    return clean[:limit].strip()


def _title_quality(text: str) -> float:
    """Cheap noise score: CJK density, length, and absence of filler.

    A slide heading (short, no closing period) scores above a full spoken
    sentence, which is what a chapter list should read like.
    """
    if not text:
        return 0.0
    cjk = len(_CJK.findall(text))
    if cjk < 2:
        return 0.0
    density = cjk / max(1, len(text))
    # A heading is short: score fitting ~10 characters, not "as long as possible".
    length_fit = 1.0 - min(1.0, abs(len(text) - 10) / 20.0)
    filler = 0.15 if re.search(r"(嗯|啊|那个|就是|然后|这个)", text) else 0.0
    heading = 0.15 if len(text) <= 18 and not text.endswith(("。", "，", "？", "！", ".", ",")) else 0.0
    sentence = 0.1 if len(text) > 30 else 0.0
    return max(0.0, density * 0.6 + length_fit * 0.4 - filler - sentence + heading)


def _chapter_title(window_start: int, window_end: int, segments: list[dict[str, Any]],
                   ocr: list[dict[str, Any]], index: int) -> tuple[str, str]:
    """Prefer a slide title (OCR) over speech, then fall back to the timecode.

    ASR text made bad chapter titles (`規矩 落獎得主Hinton老爺子這是整個大的`,
    `5m06s`). OCR lines on a slide are usually the human-written heading, so they
    win when they look like a title; otherwise the cleaned transcript sentence is
    used, and a pure timecode is the last resort.
    """
    ocr_candidates = [
        _clean_title(t.get("text") or "")
        for t in ocr
        if window_start <= int(t.get("start_ms") or 0) <= window_end
    ]
    ocr_best = max(ocr_candidates, key=_title_quality, default="")
    asr_candidates = [
        _clean_title(s.get("text") or "")
        for s in segments
        if window_start <= int(s.get("start_ms") or 0) <= window_end
    ]
    asr_best = max(asr_candidates, key=_title_quality, default="")
    if _title_quality(ocr_best) >= 0.5 and len(ocr_best) >= 4:
        return ocr_best, "ocr"
    if _title_quality(asr_best) >= 0.3 and len(asr_best) >= 4:
        return asr_best, "transcript"
    return f"第 {index} 段", "timecode"


def _chapters(scenes: list[dict[str, Any]], segments: list[dict[str, Any]],
              ocr: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if not scenes:
        return []
    chapters: list[dict[str, Any]] = []
    start_ms = int(scenes[0]["start_ms"])
    last_end = int(scenes[-1]["end_ms"])
    # A real 5-minute grid, not "wait for a scene gap": sparse scenes (a 67-minute
    # lecture with 23 scenes) used to collapse into 5 chapters, one 22 minutes long.
    while start_ms < last_end and len(chapters) < 100:
        end_ms = min(start_ms + 300_000, last_end)
        title, source = _chapter_title(start_ms, end_ms, segments, ocr or [], len(chapters) + 1)
        chapters.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "timecode": format_timecode(start_ms, millis=False),
            "title": title,
            "title_source": source,
            "fallback_timecode": format_duration(start_ms),
        })
        start_ms = end_ms
    return chapters


OCR_RELIABLE_MIN = 0.5


OCR_TEXT_CLIP = 400


def _clip_ocr_text(text: Any, limit: int = OCR_TEXT_CLIP) -> tuple[str, bool]:
    """A misread overlay can emit a paragraph of repeated glyphs; the receipt is
    a pointer, not a transcript. Cap the returned text so one bad track cannot
    cost a thousand tokens. The stored track keeps its full text for search."""
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = re.sub(r"(.)\1{7,}", r"\1\1\1", value)
    if len(value) <= limit:
        return value, False
    return value[:limit] + "…", True


def _ocr_reliable(confidence: Any) -> bool | None:
    """A zero/absent OCR score is not evidence of trustworthy text."""
    if confidence is None:
        return None
    try:
        return float(confidence) >= OCR_RELIABLE_MIN
    except (TypeError, ValueError):
        return None


def _clip(text: str, needle: str = "", width: int = 160, lead: int = 32) -> str:
    """Center a snippet on the match.

    Snippets used to be `text[:500]`, which produced things like a 206-character
    hit whose keyword sat in the last 7 characters. The match is kept within the
    first `lead` characters of the window; when it sits at the very end of the
    paragraph the window simply ends there (a short, readable snippet) instead of
    padding the text back out to `width` and burying the hit again.
    """
    clean = " ".join(str(text or "").split())
    if not clean:
        return ""
    probe = str(needle or "").strip().lower()
    idx = clean.lower().find(probe) if probe else -1
    if idx < 0:
        return clean if len(clean) <= width else clean[:width] + "…"
    if idx <= lead and len(clean) <= width:
        return clean
    start = max(0, idx - lead)
    end = min(len(clean), start + width)
    return ("…" if start else "") + clean[start:end] + ("…" if end < len(clean) else "")


def _fuzzy_score(query: str, text: str) -> float:
    q = re.sub(r"\s+", "", normalize_text(query).lower())
    t = re.sub(r"\s+", "", normalize_text(text).lower())
    if not q or not t:
        return 0.0
    seq = SequenceMatcher(None, q, t).ratio()
    qg = {q[i:i + 2] for i in range(max(1, len(q) - 1))}
    tg = {t[i:i + 2] for i in range(max(1, len(t) - 1))}
    jac = len(qg & tg) / max(1, len(qg | tg))
    return round(0.6 * seq + 0.4 * jac, 4)


def _score_from_rank(rank: float | None) -> float:
    """Map an FTS5 rank (negative; more negative is better) to 0..1, monotonic."""
    if rank is None:
        return 0.0
    magnitude = abs(float(rank))
    return round(magnitude / (1.0 + magnitude), 4)


def _rerank(base: float, text: str, *, query: str, units: list[str]) -> float:
    """Blend BM25 with query-unit matches and numeric agreement.

    Chinese queries are tokenised into overlapping bigrams/trigrams and OR-ed,
    so BM25 alone liked a short line that matched one common token (and
    short-document length normalisation amplified it). The number of *distinct*
    query units a hit contains is the strongest signal; coverage (fraction) and
    BM25 break ties; numeric agreement keeps 85% / 3.5 / 百分之八十五 from
    drifting to a different number.
    """
    matched = count_unit_matches(text, units)
    cov = round(matched / len(units), 4) if units else 0.0
    count_norm = min(matched, 3) / 3.0
    if number_tokens(query):
        nums = numeric_overlap(query, text)
        return round(min(0.99, 0.25 * base + 0.15 * cov + 0.25 * count_norm + 0.35 * nums), 4)
    return round(min(0.99, 0.35 * base + 0.25 * cov + 0.40 * count_norm), 4)


def _timestamp_result(db: Database, vid: str, at_ms: int, query: str) -> list[dict[str, Any]]:
    """Resolve "00:00:12 说了什么" to the segment/OCR at that exact time."""
    video = db.get_video(vid) or {}
    duration = int(video.get("duration_ms") or 0)
    if duration and at_ms > duration:
        return []
    seg = db.get_segment_at(vid, at_ms)
    if seg:
        row = _exact_result(db, seg, query, "segment")
        row.update({
            "score": 0.99,
            "why": f"按查询里的时间戳 {format_timecode(at_ms)} 定位到该段转写",
        })
        return [row]
    ocr = [t for t in db.get_ocr_tracks(vid, max(0, at_ms - 800), at_ms + 800, limit=5)
           if t["start_ms"] <= at_ms + 800 and t["end_ms"] >= at_ms - 800]
    if ocr:
        best = min(ocr, key=lambda t: abs(int(t["start_ms"]) - at_ms))
        row = _exact_result(db, best, query, "ocr")
        row.update({
            "score": 0.95,
            "why": f"该时间点没有转写；按时间戳 {format_timecode(at_ms)} 返回画面文字",
        })
        return [row]
    near = [s for s in db.get_segments(vid, max(0, at_ms - 5000), at_ms + 5000, limit=20)
            if s["start_ms"] <= at_ms + 5000 and s["end_ms"] >= at_ms - 5000]
    if near:
        best = min(near, key=lambda s: abs(int(s["start_ms"]) - at_ms))
        row = _exact_result(db, best, query, "segment")
        row.update({
            "score": 0.6,
            "why": f"时间戳 {format_timecode(at_ms)} 附近没有精确片段；返回最近片段（±5s）",
        })
        return [row]
    return []


def _literal_all(text: str, terms: list[str]) -> bool:
    hay = to_simplified(normalize_text(text)).lower()
    for t in terms:
        if t.isascii():
            # Boundary match, not a word-set lookup: "3.5" and "85%" never appear
            # as [a-z0-9_]+ tokens, so the old set test always failed.
            # Letters keep letter boundaries ("ai" must not hit "said"); numeric
            # versions only care about digits/dots ("v3.5" matches, "3.5.1" not).
            if t[0].isalpha() and t[-1].isalpha():
                pattern = r"(?<![a-z0-9_])" + re.escape(t.lower()) + r"(?![a-z0-9_])"
            else:
                pattern = r"(?<![0-9_.])" + re.escape(t.lower()) + r"(?![0-9_.])"
            if not re.search(pattern, hay):
                return False
        elif t not in hay:
            return False
    return True


def _literal_hits(db: Database, video_ids: list[str], query: str, limit: int,
                  *, start_ms: int | None = None, end_ms: int | None = None) -> list[dict[str, Any]]:
    """Last-resort literal match for queries FTS cannot tokenise.

    Covers single CJK characters ("秩", "表") and space-separated shorthand
    ("Q K V"). Every term must be present, so a nonsense query still yields
    nothing; results are capped and marked with an honest reason.
    """
    terms = literal_terms(query)
    if not terms:
        return []
    score = 0.55 if len(terms) >= 2 else 0.45
    out: list[dict[str, Any]] = []
    for vid in video_ids:
        for seg in db.get_segments(vid, limit=3000):
            if start_ms is not None and int(seg.get("end_ms") or 0) < int(start_ms):
                continue
            if end_ms is not None and int(seg.get("start_ms") or 0) > int(end_ms):
                continue
            if _literal_all(seg.get("text") or "", terms):
                row = _exact_result(db, seg, query, "segment")
                row.update({"score": score, "why": "逐词回退匹配：按字面包含（FTS 没有对应词元）"})
                out.append(row)
        for tr in db.get_ocr_tracks(vid, limit=1500):
            if start_ms is not None and int(tr.get("end_ms") or 0) < int(start_ms):
                continue
            if end_ms is not None and int(tr.get("start_ms") or 0) > int(end_ms):
                continue
            if _literal_all(tr.get("text") or "", terms):
                row = _exact_result(db, tr, query, "ocr")
                row.update({"score": score, "why": "逐词回退匹配：按字面包含（FTS 没有对应词元）"})
                out.append(row)
    # Titles are the last resort, and only when the text did not match at all: adding
    # them unconditionally let 5 title hits (score .95) crowd out the real line.
    if not out:
        for vid in video_ids[:2]:
            video = db.get_video(vid) or {}
            title = str(video.get("title") or "")
            if title and _literal_all(title, terms):
                row = _video_result(db, {"id": vid}, query, [t.lower() for t in terms])
                row["score"] = 0.40
                out.append(row)
    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:max(1, min(limit, 5))]


_MODALITY_ALIASES = {
    "video_meta": "video", "video": "video",
    "visual_segment": "visual", "visual": "visual",
    "ocr_track": "ocr", "ocr": "ocr",
    "segment": "transcript", "caption": "transcript",
    "asr": "transcript", "transcript": "transcript",
}


def _result_modalities(row: dict[str, Any]) -> set[str]:
    """Canonical modality tags for a result, from its `modalities` and `source`."""
    tags = {str(t) for t in (row.get("modalities") or [])}
    tags |= {_MODALITY_ALIASES.get(t, t) for t in list(tags)}
    source = str(row.get("source") or "")
    if source in _MODALITY_ALIASES:
        tags.add(_MODALITY_ALIASES[source])
    return tags


def _filter_modalities(results: list[dict[str, Any]], modalities: list[str] | None) -> list[dict[str, Any]]:
    """Apply `--modalities` to *every* result path, not just the FTS query."""
    if modalities is None:
        return results
    allowed = {_MODALITY_ALIASES.get(str(m), str(m)) for m in modalities}
    return [r for r in results if _result_modalities(r) & allowed]


def _should_literal_fallback(query: str) -> bool:
    terms = literal_terms(query)
    if not terms:
        return False
    return len(terms) <= 3 and len(normalize_text(query)) <= 8


def _video_visual_index(db: Database, video_id: str) -> dict[str, Any]:
    # Always derive from the video's own stored metrics, so a library search and
    # that video's overview cannot disagree about whether the index is complete.
    video = db.get_video(video_id) or {}
    metrics = (video.get("meta") or {}).get("analysis_metrics") or {}
    return _visual_index_info(db.frame_ocr_counts(video_id), metrics)


def _visual_index_for_search(db: Database, video_id: str | None,
                             targets: list[str]) -> dict[str, Any]:
    """One visual-index answer for a search: a single video or the whole library."""
    if video_id:
        return _video_visual_index(db, video_id)
    infos = [_video_visual_index(db, vid) for vid in targets[:SEARCH_TARGET_LIMIT]]
    read = sum(int(i["read_frames"]) for i in infos)
    failed = sum(int(i["failed_frames"]) for i in infos)
    total = sum(int(i["total_frames"]) for i in infos)
    states = [i["state"] for i in infos]
    remaining_values = [i["remaining_frames"] for i in infos]
    remaining = (sum(int(v) for v in remaining_values if v is not None)
                 if remaining_values and all(v is not None for v in remaining_values) else None)
    if infos and all(s == "complete" for s in states):
        state = "complete"
    elif read:
        state = "partial"
    elif failed:
        state = "failed"
    elif any(s == "unavailable" for s in states):
        state = "unavailable"
    elif any(s == "on_demand" for s in states):
        state = "on_demand"
    else:
        state = "unmeasured"
    return {
        "indexed": read > 0,
        "state": state,
        "reason": _visual_index_reason(state, read, failed, total=total, remaining=remaining),
        "read_frames": read,
        "failed_frames": failed,
        "total_frames": total,
        "remaining_frames": remaining,
    }


def _empty_search_warnings(db: Database, targets: list[str]) -> list[dict[str, Any]]:
    """Explain a zero-hit answer instead of implying the video has nothing.

    Lazy OCR (the default), a partial index (a pass that stopped at the cap), a
    failed OCR read, and a frame that really had no text used to produce the same
    NO_MATCH. They mean very different things.
    """
    infos = [_video_visual_index(db, vid) for vid in targets]
    read = sum(int(i["read_frames"]) for i in infos)
    failed = sum(int(i["failed_frames"]) for i in infos)
    total = sum(int(i["total_frames"]) for i in infos)
    remaining_values = [i["remaining_frames"] for i in infos]
    remaining = (sum(int(v) for v in remaining_values if v is not None)
                 if remaining_values and all(v is not None for v in remaining_values) else None)
    how = "先运行 video2agent ocr-index <视频 ID> --dry-run 看预计帧数和耗时，再运行 video2agent ocr-index <视频 ID>。"
    out: list[dict[str, Any]] = []
    if failed:
        out.append({
            "code": "OCR_FAILED",
            "message": f"{failed} 帧画面文字读取失败；0 条不能说明视频里没有这些字。",
            "remedy": "检查本机 OCR 模型/依赖后重新 ingest --force，或先用 evidence --at 重试该时刻。",
        })
    if not read and not failed:
        out.append({
            "code": "OCR_NOT_INDEXED",
            "message": "画面文字尚未建立索引（默认按需识别）；0 条不代表视频里没有这些字。",
            "remedy": how,
        })
    elif read and any(i["state"] != "complete" for i in infos):
        detail = (f"（{read}/{total} 帧已读、还有 {remaining} 帧待读）" if remaining
                  else f"（{read}/{total} 帧已读）" if total else "")
        out.append({
            "code": "OCR_INDEX_PARTIAL",
            "message": f"画面文字只索引了一部分{detail}；0 条不代表视频里没有这些字。",
            "remedy": how,
        })
    return out


def search(cfg: Config, query: str, *, video_id: str | None = None, collection: str | None = None,
           limit: int = 8, start_ms: int | None = None, end_ms: int | None = None,
           modalities: list[str] | None = None, visual_types: list[str] | None = None) -> dict[str, Any]:
    if int(limit) < 1:
        raise Video2AgentError(
            "E_ARGS",
            f"--limit 必须至少为 1（收到 {limit}）",
            "传入 1 或更大的值；0 不会表示“没有匹配”，它只是关闭了结果页。",
        )
    at_ms, rest = leading_timecode(query)
    # A bare timecode is a location request, not a text query. Tokenising
    # "00:10:00" into "00"/"10" used to return unrelated segments that merely
    # contained those digits while also reporting TIMESTAMP_NOT_FOUND.
    time_only = at_ms is not None and not rest
    raw_content = rest if (at_ms is not None and rest) else ('' if time_only else query)
    content_query = to_simplified(raw_content)
    aliases = _expand_terms(content_query)
    expanded = _expand_query(content_query) if raw_content else ''
    match = fts_match_query(expanded) if raw_content else ''
    units = _coverage_units(content_query, aliases) if raw_content else set()
    # An alias hit is evidence only if the alias' own units count too; the
    # expanded string must not be tokenised as one CJK run (see _coverage_units).
    warnings: list[dict[str, Any]] = []
    empty_payload = {"ok": True, "query": query, "results": [], "empty": True, "next": {"cursor": None}}
    with Database(cfg.db_path) as db:
        if not video_id and not collection and db.video_count() == 0:
            # An empty library is not a search result. `ok:true, results: []` read
            # like "the video does not contain this", which is a false answer.
            raise Video2AgentError(
                "E_EMPTY_LIBRARY",
                "库里还没有视频，无法搜索。",
                "先运行 video2agent ingest <本地文件或链接> 建立索引，再用 video2agent list 查看 video_id。",
            )
        if (not video_id and not collection
                and not db.one("SELECT 1 FROM videos WHERE status='ready' LIMIT 1")):
            # Rows exist but none is analysable: a bare NO_MATCH would read as
            # "the video does not contain this".
            raise Video2AgentError(
                "E_NO_READY_VIDEO",
                "库里没有可搜索的视频（都不在 ready 状态）。",
                "用 video2agent jobs 查看进度，或重新 ingest 失败的记录。",
            )
        if video_id:
            target = require_ready(db.get_video(video_id), video_id)
            if _stored_caption_mismatch(db, target):
                source = target.get("source_uri") or video_id
                raise Video2AgentError(
                    "E_CAPTION_CONTENT_MISMATCH",
                    "这条视频的字幕内容与标题不匹配，搜索会命中错误词。",
                    f"运行 video2agent ingest \"{source}\" --force 重新分析后再搜索。",
                )
        video_ids: list[str] = []
        if video_id:
            video_ids = [video_id]
        elif collection:
            video_ids = [v["id"] for v in db.collection_videos(collection)
                         if str(v.get("status") or "") == "ready"]
            if not video_ids:
                return {**empty_payload, "warnings": [{
                    "code": "COLLECTION_EMPTY",
                    "message": f"收藏夹「{collection}」不存在或为空。",
                }]}
        # The target set must be computed once: several fallbacks below used to run only
        # when `--video` was given, so the same query returned different results with and
        # without the filter.
        # A library-wide search must not return a record its own reads reject:
        # failed/canceled/evicted/analyzing rows kept stale segments, so a hit
        # led straight to E_NOT_READY from evidence/transcript.
        capped: list[dict[str, Any]] = []
        # The ready filter must run in SQL, not after the limit: with 200 newer
        # non-ready rows the target set came back empty even though older ready
        # videos existed, so a real word read as NO_MATCH.
        targets = video_ids or [row["id"] for row in db.all(
            "SELECT id FROM videos WHERE status='ready' "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            [SEARCH_TARGET_LIMIT],
        )]
        if not video_ids:
            # Declare the cap: a word that exists only in an older video must not
            # read as "not in the library".
            try:
                total_ready = db.one(
                    "SELECT COUNT(*) AS n FROM videos WHERE status='ready'")["n"]
            except Exception:
                total_ready = len(targets)
            if total_ready > len(targets):
                capped.append({
                    "code": "SEARCH_TARGETS_CAPPED",
                    "message": f"只搜索了最近 {len(targets)} 个可用视频（共 {total_ready} 个）",
                    "remedy": "用 --video 指定视频，或缩小库后重试。",
                })
                # Must be in the payload: an unannounced cap made an older
                # video's word read as "not in the library".
                warnings.extend(capped)
        visual_index = _visual_index_for_search(db, video_id, targets)
        if not match and at_ms is None:
            literal = _filter_modalities(_literal_hits(
                db, targets, raw_content, max(limit, 1), start_ms=start_ms, end_ms=end_ms,
            ), modalities)
            if start_ms is not None:
                literal = [r for r in literal if r["end_ms"] >= start_ms]
            if end_ms is not None:
                literal = [r for r in literal if r["start_ms"] <= end_ms]
            literal = literal[:max(0, limit)]
            if literal:
                return {**empty_payload, "results": literal, "empty": False,
                        "warnings": list(warnings) + [{"code": "LITERAL_FALLBACK",
                                                       "message": "FTS 没有对应词元；使用逐词字面回退（全部词面命中）。"}],
                        "visual_indexed": visual_index["indexed"], "visual_index": visual_index}
            payload = dict(empty_payload)
            # Keep the earlier warnings: dropping SEARCH_TARGETS_CAPPED here made
            # a tokenizer-empty query look like a plain NO_MATCH.
            payload["warnings"] = list(warnings) + (
                [{"code": "NO_MATCH", "message": "没有匹配的转写、画面文字或视觉结构。"}]
                + _empty_search_warnings(db, targets)
                if literal_terms(raw_content)
                else [{"code": "EMPTY_QUERY", "message": "Query has no searchable tokens"}]
            )
            return payload
        results: list[dict[str, Any]] = []
        truncated = False
        if at_ms is not None:
            anchored: list[dict[str, Any]] = []
            for vid in targets:
                anchored.extend(_timestamp_result(db, vid, at_ms, query))
            if anchored:
                results.extend(anchored)
            else:
                warnings.append({"code": "TIMESTAMP_NOT_FOUND",
                                 "message": f"没有覆盖 {format_timecode(at_ms)} 的片段或画面文字。"})
        wanted = _wanted_visual(content_query)
        # Numeric/phrase queries such as 第42段 are poorly served by OR-token BM25.
        # Check exact substring matches first for a bounded set of segments/tracks.
        # `targets` is the same list used elsewhere: without it, a numeric query
        # silently searched only when `--video` was given, so the same query returned
        # different results depending on the filter.
        if any(ch.isdigit() for ch in content_query) and targets:
            needle = normalize_text(content_query).lower()
            # A number needs boundaries: "3.5" lives inside "43.5", and that hit was
            # returned first with a perfect score.
            pattern = re.compile(rf"(?<![0-9.]){re.escape(needle)}(?![0-9])") if any(ch.isdigit() for ch in needle) else None
            def _hit(value: str) -> bool:
                hay = normalize_text(value).lower()
                if not needle or not hay:
                    return False
                return bool(pattern.search(hay)) if pattern else needle in hay
            for vid in targets:
                for seg in db.get_segments(vid, limit=3000):
                    if _hit(seg.get("text") or ""):
                        results.append(_exact_result(db, seg, query, "segment"))
                for tr in db.get_ocr_tracks(vid, limit=1500):
                    if _hit(tr.get("text") or ""):
                        results.append(_exact_result(db, tr, query, "ocr"))
        if wanted and targets:
            for vid in targets:
                for v in db.get_visual_segments(vid, types=wanted, min_score=0.35, limit=10):
                    results.append(_visual_result(db, v, content_query))
        if match:
            # A fixed pool: the page size must never change the ranking (it did).
            pool = 200
            # One query for the library, then filter to the ready targets: a
            # per-video loop measured 8s on 205 videos (vs 0.06s globally) and
            # the old unfiltered scan returned rows for failed/evicted videos
            # that evidence/transcript then refused.
            target_set = None if video_ids else set(targets)
            # The ready filter must run inside SQL: filtering after LIMIT let
            # stale non-ready rows fill the pool and hid real hits.
            scoped = None if video_ids else list(targets)
            for vid in (video_ids or [None]):
                if modalities is None or "transcript" in modalities:
                    for r in db.search_segments(match, vid, limit=pool, video_ids=scoped,
                                                  start_ms=start_ms, end_ms=end_ms):
                        if target_set is not None and str(r.get("video_id") or "") not in target_set:
                            continue
                        results.append(_segment_result(db, r, content_query, "transcript", visual_types, wanted, units, aliases))
                if modalities is None or "ocr" in modalities:
                    for r in db.search_ocr(match, vid, limit=pool, video_ids=scoped,
                                               start_ms=start_ms, end_ms=end_ms):
                        if target_set is not None and str(r.get("video_id") or "") not in target_set:
                            continue
                        results.append(_ocr_result(db, r, content_query, visual_types, wanted, units, aliases))
        if match and targets and (modalities is None or "video" in modalities):
            meta_cap = min(10, max(1, limit // 3))
            for row in db.search_videos(match, limit=meta_cap * 4, video_ids=video_ids or list(targets) or None):
                if not video_ids and str(row.get("id") or "") not in set(targets):
                    continue
                if len([r for r in results if r.get("source") == "video_meta"]) >= meta_cap:
                    break
                results.append(_video_result(db, row, content_query, units, aliases))
        results = [r for r in results if r]
        if not results and targets:
            # Typo/ASR-noise fallback: character similarity over a bounded range. A
            # zero-hit query otherwise scans the whole library (measured 220ms against
            # 5ms for a normal query, growing with the library), so stop as soon as
            # there are enough candidates to rank.
            budget = max(16, limit * 2)
            # A miss scanned every video with three queries each (5-7s at 500 videos).
            deadline = time.monotonic() + 0.4
            truncated = False
            for vid in targets:
                if time.monotonic() > deadline:
                    truncated = True
                    break
                if len(results) >= budget:
                    break
                for seg in db.get_segments(vid, limit=800):
                    score = _fuzzy_score(content_query, seg.get("text") or "")
                    if score >= 0.42:
                        results.append(_fuzzy_segment_result(db, seg, content_query, score, "transcript"))
                        if len(results) >= budget:
                            break
                for tr in db.get_ocr_tracks(vid, limit=400):
                    score = _fuzzy_score(content_query, tr.get("text") or "")
                    if score >= 0.42:
                        results.append(_fuzzy_ocr_result(db, tr, content_query, score))
                        if len(results) >= budget:
                            break
            if results:
                warnings.append({"code": "FUZZY_FALLBACK", "message": "No exact FTS hit; used character-similarity fallback."})
        # A query whose units appear nowhere is not a weak match, it is a miss:
        # "量子纠缠" returned eight 量子力学 lines at 0.06 and called it a result. The
        # literal fallback below is the one that may still answer a partial query, and
        # an explicit timestamp anchor is a different modality (the user named the time).
        # A result whose text contains none of the query's content units is an
        # FTS stopword artifact, not a weak match. English questions such as
        # "what is the first line" returned "This is pretty freaky." at 0.45
        # with matched_terms=[]; "is" in the snippet was enough to pass the old
        # coverage check. Drop English function words before deciding.
        en_stop = {
            "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "did",
            "for", "from", "has", "have", "how", "i", "in", "is", "it", "its",
            "of", "on", "or", "that", "the", "their", "this", "to", "was", "were",
            "what", "when", "where", "which", "who", "why", "with", "you",
        }
        content_units = [u for u in units if str(u).lower() not in en_stop] or units
        if results and at_ms is None and content_units:
            if not any(
                coverage_score(str(r.get("snippet") or ""), content_units) > 0
                or bool(r.get("matched_terms"))
                for r in results
            ):
                results = []
        if not results and at_ms is None and _should_literal_fallback(raw_content):
            # Single CJK char ("秩"/"表") or short shorthand ("Q K V"): the
            # index has no 1-char token, so fall back to a literal all-terms match.
            literal = _literal_hits(db, targets, raw_content, limit, start_ms=start_ms, end_ms=end_ms)
            if literal:
                results = literal
                warnings.append({"code": "LITERAL_FALLBACK",
                                 "message": "FTS 没有命中；使用逐词字面回退（全部词面命中）。"})
        results = _filter_modalities(results, modalities)
        if truncated:
            warnings.append({"code": "SEARCH_TIME_BUDGET",
                             "message": "零命中回退只扫描了一部分视频（0.4s 预算）；缩小 --video/--collection 可完整扫描。"})
        if start_ms is not None:
            results = [r for r in results if r["end_ms"] >= start_ms]
        if end_ms is not None:
            results = [r for r in results if r["start_ms"] <= end_ms]
        # A title/meta hit is useful for discovery, but a 0.95 whole-video row
        # must not outrank real transcript moments for a content search. A row
        # that does not even contain the typed query (it matched a curated
        # synonym in the description) is discovery at best, so it goes below
        # every moment.
        non_meta = [r for r in results if r.get("source") != "video_meta"]
        if non_meta:
            ceiling = round(max(float(r.get("score") or 0) for r in non_meta) - 0.01, 4)
            for r in results:
                if r.get("source") != "video_meta":
                    continue
                r["score"] = round(max(0.0, float(r.get("score") or 0) - 0.3), 4)
                if content_query not in (r.get("matched_terms") or []):
                    r["score"] = round(min(r["score"], ceiling), 4)
        # Deduplicate by video + 2s bucket, keep best.
        results.sort(key=lambda r: r["score"], reverse=True)
        dedup: list[dict[str, Any]] = []
        if limit <= 0:
            results = []
        seen_text = set()
        for r in results:
            # The same line read on four consecutive frames is one answer, not four:
            # dedupe by video + normalised snippet, then by time bucket.
            text_key = (r["video_id"], normalize_text(str(r.get("snippet") or ""))[:80])
            if text_key[1] and text_key in seen_text:
                continue
            if any(
                r["video_id"] == x["video_id"]
                and r.get("source") != "video_meta"
                and x.get("source") != "video_meta"
                and abs(r["start_ms"] - x["start_ms"]) < 1000
                for x in dedup
            ):
                continue
            seen_text.add(text_key)
            dedup.append(r)
            if len(dedup) >= limit:
                break
    if not dedup:
        warnings.append({"code": "NO_MATCH", "message": "没有匹配的转写、画面文字或视觉结构。"})
        # Say why the visual text is missing: never read, failed, or genuinely absent.
        with Database(cfg.db_path) as note_db:
            warnings.extend(_empty_search_warnings(note_db, targets or []))
    return {"ok": True, "query": query, "results": dedup, "empty": not dedup,
            "next": {"cursor": None}, "warnings": warnings,
            "visual_indexed": visual_index["indexed"], "visual_index": visual_index}


def search_queries(cfg: Config, queries: list[str], *, video_id: str | None = None,
                   collection: str | None = None, limit: int = 8,
                   start_ms: int | None = None, end_ms: int | None = None,
                   modalities: list[str] | None = None) -> dict[str, Any]:
    """Run several query variants and merge hits by video/time.

    The model supplies the variants (synonyms, likely ASR spellings); this
    layer stays deterministic. Each merged hit records which variants found
    it, and each group reports its own empty/warnings state so a synonym miss
    is not hidden by another variant's hit.
    """
    queries = [str(q).strip() for q in queries if str(q or "").strip()][:8]
    if not queries:
        raise Video2AgentError("E_QUERY", "至少需要一个检索词。", "传入 query 或 queries。")
    groups: list[dict[str, Any]] = []
    merged: dict[tuple[str, int, str], dict[str, Any]] = {}
    all_warnings: list[dict[str, Any]] = []
    for query in queries:
        data = search(cfg, query, video_id=video_id, collection=collection, limit=limit,
                      start_ms=start_ms, end_ms=end_ms, modalities=modalities)
        hits = data.get("results") or []
        groups.append({"query": query, "count": len(hits), "empty": bool(data.get("empty")),
                       "warnings": data.get("warnings") or []})
        for warning in data.get("warnings") or []:
            all_warnings.append({**warning, "query": query})
        for hit in hits:
            text = normalize_text(str(hit.get("snippet") or ""))[:80]
            key = (str(hit.get("video_id") or ""), int(hit.get("start_ms") or 0) // 1000, text)
            if key in merged:
                item = merged[key]
                if query not in item["matched_queries"]:
                    item["matched_queries"].append(query)
            else:
                item = dict(hit)
                item["matched_queries"] = [query]
                merged[key] = item
    results = sorted(merged.values(), key=lambda r: float(r.get("score") or 0), reverse=True)[:limit]
    return {"ok": True, "queries": queries, "results": results, "empty": not results,
            "groups": groups, "warnings": all_warnings, "next": {"cursor": None}}

def ocr_index(cfg: Config, video_id: str, *, dry_run: bool = False,
              limit: int | None = None) -> dict[str, Any]:
    # Build the on-screen text index for one video, explicitly. `auto` ingest stays
    # lazy; this is the opt-in pass. The dry-run estimate comes from a real
    # measurement (the record's own OCR history, or one probe frame), never from a
    # hardcoded seconds-per-frame.
    with Database(cfg.db_path) as db:
        video = db.get_video(video_id)
        if not video:
            raise Video2AgentError("E_NOT_FOUND", f"Video not found: {video_id}", "Run video2agent list.")
        frames = db.get_frames(video_id, limit=5000)
        metrics = (video.get("meta") or {}).get("analysis_metrics") or {}
        frame_counts = db.frame_ocr_counts(video_id)
    if not frames:
        raise Video2AgentError(
            "E_NO_FRAMES",
            "这条记录没有抽帧，无法建立画面索引。",
            "重新 ingest（--force）以重建抽帧。",
        )
    cap = max(1, min(OCR_INDEX_MAX_FRAMES, int(limit or cfg.get("ocr_max_frames") or 120)))
    already = [f for f in frames if str(f.get("ocr_status") or "") in ("ok", "empty")]
    # A limit must spend its budget on unread frames. Selecting over all frames let
    # the sparse buckets pick already-read ones, so a 6-frame pass reported
    # "already indexed" while 56 frames were still unread.
    unread_frames = [f for f in frames if str(f.get("ocr_status") or "") not in ("ok", "empty")]
    candidates = select_ocr_frames(unread_frames, cap) if unread_frames else []
    to_read = candidates[:cap]
    current = _visual_index_info(frame_counts, metrics)

    per_frame_ms: int | None = None
    measured_by = ""
    history_frames = int(metrics.get("n_ocr_frames") or 0)
    history_seconds = float(metrics.get("ocr") or 0)
    if history_frames > 0 and history_seconds > 0:
        per_frame_ms = max(1, int(round(history_seconds * 1000 / history_frames)))
        measured_by = "history"
    elif dry_run and to_read:
        # Only a dry run probes: a real run measures itself and must not pay for
        # one extra frame (or fail before reading anything).
        if not ocr_available():
            raise Video2AgentError(
                "E_OCR_UNAVAILABLE",
                "未安装 OCR，无法建立画面索引。",
                "pip install \"video2agent[ocr]\" 后重试（本地 OCR 需要 Python 3.11/3.12）。",
            )
        probe = to_read[0]
        started = time.perf_counter()
        try:
            ocr_image(str(probe["path"]), config_path=str(cfg.get("ocr_local_config") or "") or None)
        except OcrFailed as exc:
            raise Video2AgentError(
                "E_OCR_FAILED",
                f"试读一帧失败：{exc}",
                "检查本机 OCR 模型/依赖（设置页可换模型）后重试。",
            ) from exc
        per_frame_ms = max(1, int(round((time.perf_counter() - started) * 1000)))
        measured_by = "probe"

    if dry_run:
        return {
            "ok": True,
            "video_id": video_id,
            "dry_run": True,
            "visual_indexed": current["indexed"],
            "visual_index": current,
            "limit": cap,
            "total_frames": len(frames),
            "already_read": len(already),
            "candidates": len(candidates),
            "to_read": len(to_read),
            "per_frame_ms": per_frame_ms,
            "measured_by": measured_by or "none",
            "estimated_ms": per_frame_ms * len(to_read) if per_frame_ms else None,
            "command": f"video2agent ocr-index {video_id}",
        }
    if not to_read:
        return {
            "ok": True,
            "video_id": video_id,
            "dry_run": False,
            "indexed": 0,
            "empty": 0,
            "failed": 0,
            "tracks": 0,
            "seconds": 0.0,
            "visual_indexed": current["indexed"],
            "visual_index": current,
            "message": "没有需要补读的帧（画面文字已经索引过）。",
        }
    if not ocr_available():
        raise Video2AgentError(
            "E_OCR_UNAVAILABLE",
            "未安装 OCR，无法建立画面索引。",
            "pip install \"video2agent[ocr]\" 后重试（本地 OCR 需要 Python 3.11/3.12）。",
        )

    local_config = str(cfg.get("ocr_local_config") or "") or None
    started = time.perf_counter()
    indexed = empty = failed = 0
    tracks: list[dict[str, Any]] = []
    reads: list[dict[str, Any]] = []
    with Database(cfg.db_path) as db:
        anchors = {int(a) for a in db.get_ocr_anchors(video_id)}
        for frame in to_read:
            pts = int(frame.get("pts_ms") or 0)
            try:
                boxes = ocr_image(str(frame["path"]), config_path=local_config)
            except OcrFailed:
                failed += 1
                reads.append({"pts_ms": pts, "ocr_status": "failed",
                              "text_coverage": None, "has_text": None, "tracks": []})
                continue
            status = "ok" if boxes else "empty"
            coverage = text_coverage_for(str(frame["path"]), boxes)
            frame_tracks = build_ocr_tracks([{"pts_ms": pts, "ocr": boxes}]) if boxes else []
            reads.append({"pts_ms": pts, "ocr_status": status,
                          "text_coverage": coverage, "has_text": bool(boxes),
                          "tracks": frame_tracks})
            if boxes:
                indexed += 1
                tracks.extend(frame_tracks)
            else:
                empty += 1
            anchors.add(pts)
        if reads:
            # Frame status and OCR rows commit together. If this fails, every
            # frame stays unread and a retry can safely redo the pass.
            db.apply_ocr_reads(video_id, reads)
        if anchors:
            db.set_ocr_anchors(video_id, sorted(anchors))
        elapsed = time.perf_counter() - started
        # How much the index still has to read after this pass. Without it a run
        # that stopped at the cap reported itself as "complete" (reproduced: 1 of 3
        # frames read, state complete).
        after = db.get_frames(video_id, limit=5000)
        still_unread = [f for f in after if str(f.get("ocr_status") or "") not in ("ok", "empty")]
        leftover = select_ocr_frames(still_unread, max(1, len(still_unread))) if still_unread else []
        remaining = len(leftover)
        meta = dict(video.get("meta") or {})
        analysis = dict(meta.get("analysis_metrics") or {})
        analysis["visual_index"] = {
            "state": ("failed" if (indexed == 0 and empty == 0)
                      else ("complete" if (remaining == 0 and failed == 0) else "partial")),
            "frames": indexed,
            "empty": empty,
            "failed": failed,
            "remaining": remaining,
            "seconds": round(elapsed, 1),
            "at": now_iso(),
        }
        meta["analysis_metrics"] = analysis
        db.update_video(video_id, meta_json=json.dumps(meta, ensure_ascii=False))
        info = _visual_index_info(db.frame_ocr_counts(video_id), analysis)
    return {
        "ok": True,
        "video_id": video_id,
        "dry_run": False,
        "indexed": indexed,
        "empty": empty,
        "failed": failed,
        "remaining": remaining,
        "tracks": len(tracks),
        "seconds": round(elapsed, 1),
        "visual_indexed": info["indexed"],
        "visual_index": info,
    }


def _video_result(db: Database, row: dict[str, Any], query: str, units: list[str],
                  aliases: list[str] | None = None) -> dict[str, Any]:
    """A hit on the video itself (title / platform description / uploader)."""
    video = db.get_video(row["id"]) or {}
    meta = video.get("meta") if isinstance(video.get("meta"), dict) else {}
    title = str(video.get("title") or "")
    description = str(meta.get("description") or meta.get("desc") or "")
    uploader = str(meta.get("uploader") or meta.get("owner") or "")
    duration = int(video.get("duration_ms") or 0)
    cover = coverage_score(f"{title} {description} {uploader}", units)
    score = round(min(0.95, 0.62 + 0.33 * cover), 4)
    matched = _matched_terms(f"{title} {description} {uploader}", query, aliases)
    return {
        "evidence_id": stable_id("ev", row["id"], 0, duration, "video"),
        "video_id": row["id"],
        "title": title,
        "start_ms": 0,
        "end_ms": duration,
        "timecode": None,
        "score": score,
        "modalities": ["video"],
        "snippet": title,
        "source": "video_meta",
        "kind": "video_meta",
        "is_whole_video": True,
        "confidence": None,
        "matched_terms": matched,
        "why": "标题/简介匹配：这是视频本身，不是某一段；" + _match_label(query, matched),
        # A whole-video hit has no moment. `00:00:00` here read as a citation
        # for a 66-minute segment; omit the timecode instead.
        "citation": f"《{title}》",
    }


def _visual_result(db: Database, v: dict[str, Any], query: str) -> dict[str, Any]:
    video = db.get_video(v["video_id"]) or {}
    seg = db.get_segment_at(v["video_id"], v["start_ms"])
    ocr = db.get_ocr_tracks(v["video_id"], v["start_ms"], v["end_ms"], limit=5)
    text = ""
    if seg:
        text = seg.get("text") or ""
    if not text and ocr:
        text = " / ".join(o["text"] for o in ocr[:4])
    score = min(1.0, 0.30 + 0.25 * float(v.get("score") or 0))
    return {
        "evidence_id": stable_id("ev", v["video_id"], v["start_ms"], v["end_ms"], "visual"),
        "video_id": v["video_id"],
        "title": video.get("title"),
        "start_ms": int(v["start_ms"]),
        "end_ms": int(v["end_ms"]),
        "timecode": format_timecode(v["start_ms"]),
        "score": round(score, 4),
        "modalities": ["visual"],
        "snippet": _clip(text, query) or f"视觉结构：{v.get('label')}",
        "source": "visual_segment",
        "confidence": v.get("score"),
        "visual_types": [v.get("label")],
        "why": f"视觉结构匹配：{v.get('label')}（查询点名了该视觉类型「{query}」）",
        "citation": f"《{video.get('title')}》 {format_timecode(v['start_ms'])}",
    }


def _exact_result(db: Database, row: dict[str, Any], query: str, kind: str) -> dict[str, Any]:
    video = db.get_video(row["video_id"]) or {}
    is_ocr = kind == "ocr"
    return {
        "evidence_id": stable_id("ev", row["video_id"], row["start_ms"], row["end_ms"], "exact"),
        "video_id": row["video_id"],
        "title": video.get("title"),
        "start_ms": int(row["start_ms"]),
        "end_ms": int(row["end_ms"]),
        "timecode": format_timecode(row["start_ms"]),
        "score": 1.0,
        "modalities": ["ocr" if is_ocr else "transcript"],
        "snippet": _clip(row.get("text") or "", query),
        "source": "ocr_track" if is_ocr else row.get("source"),
        "confidence": row.get("confidence"),
        **({"ocr_reliable": _ocr_reliable(row.get("confidence"))} if is_ocr else {}),
        "visual_types": [],
        "why": f"精确文本命中；关键词「{query}」",
        "citation": f"《{video.get('title')}》 {format_timecode(row['start_ms'])}",
    }


def _fuzzy_segment_result(db: Database, seg: dict[str, Any], query: str, score: float, modality: str) -> dict[str, Any]:
    video = db.get_video(seg["video_id"]) or {}
    return {
        "evidence_id": stable_id("ev", seg["video_id"], seg["start_ms"], seg["end_ms"], "fuzzy"),
        "video_id": seg["video_id"],
        "title": video.get("title"),
        "start_ms": int(seg["start_ms"]),
        "end_ms": int(seg["end_ms"]),
        "timecode": format_timecode(seg["start_ms"]),
        "score": round(min(0.65, 0.2 + score * 0.5), 4),
        "modalities": [modality],
        "snippet": _clip(seg.get("text") or "", query),
        "source": seg.get("source"),
        "confidence": seg.get("confidence"),
        "visual_types": [],
        "why": f"模糊匹配；无精确命中；相似度 {score:.2f}",
        "citation": f"《{video.get('title')}》 {format_timecode(seg['start_ms'])}",
    }


def _fuzzy_ocr_result(db: Database, tr: dict[str, Any], query: str, score: float) -> dict[str, Any]:
    video = db.get_video(tr["video_id"]) or {}
    return {
        "evidence_id": stable_id("ev", tr["video_id"], tr["start_ms"], tr["end_ms"], "fuzzy_ocr"),
        "video_id": tr["video_id"],
        "title": video.get("title"),
        "start_ms": int(tr["start_ms"]),
        "end_ms": int(tr["end_ms"]),
        "timecode": format_timecode(tr["start_ms"]),
        "score": round(min(0.65, 0.2 + score * 0.5), 4),
        "modalities": ["ocr"],
        "snippet": _clip(tr.get("text") or "", query),
        "source": "ocr_track",
        "confidence": tr.get("confidence"),
        "ocr_reliable": _ocr_reliable(tr.get("confidence")),
        "visual_types": [],
        "why": f"画面 OCR 模糊匹配；相似度 {score:.2f}",
        "citation": f"《{video.get('title')}》 {format_timecode(tr['start_ms'])}",
    }


def _matches_visual(db: Database, video_id: str, start_ms: int, end_ms: int, visual_types: list[str] | None) -> bool:
    if not visual_types:
        return True
    segs = db.get_visual_segments(video_id, start_ms, end_ms, types=visual_types, limit=5)
    return bool(segs)


def _segment_result(db: Database, r: dict[str, Any], query: str, modality: str,
                    visual_types: list[str] | None, wanted: list[str] | None = None,
                    units: list[str] | None = None,
                    aliases: list[str] | None = None) -> dict[str, Any] | None:
    if not _matches_visual(db, r["video_id"], r["start_ms"], r["end_ms"], visual_types):
        return None
    video = db.get_video(r["video_id"]) or {}
    text = r.get("text") or ""
    matched = _matched_terms(text, query, aliases)
    score = _score_from_rank(r.get("rank"))
    if normalize_text(query).lower() in normalize_text(text).lower():
        score = min(1.0, score + 0.15)
    labels = sorted({v["label"] for v in db.get_visual_segments(r["video_id"], r["start_ms"], r["end_ms"], limit=5)})
    if wanted and any(x in wanted for x in labels):
        score = min(1.0, score + 0.12)
        why_extra = "视觉结构匹配"
    else:
        why_extra = ""
    score = _rerank(score, text, query=query, units=units or [])
    if not score and query not in matched:
        # Only a curated synonym matched: report weak evidence, not "no match".
        score = SYNONYM_ONLY_FLOOR
    eid = stable_id("ev", r["video_id"], r["start_ms"], r["end_ms"], modality)
    # Center the snippet on what actually matched: an alias hit must show its term.
    needle = query if query in matched else (matched[0] if matched else query)
    return {
        "evidence_id": eid,
        "video_id": r["video_id"],
        "title": video.get("title"),
        "start_ms": int(r["start_ms"]),
        "end_ms": int(r["end_ms"]),
        "timecode": format_timecode(r["start_ms"]),
        "score": round(score, 4),
        "modalities": [modality],
        "snippet": _clip(text, needle),
        "source": r.get("source"),
        "confidence": r.get("confidence"),
        "visual_types": labels,
        "matched_terms": matched,
        "why": _hit_why(modality, query, matched, why_extra),
        "citation": f"《{video.get('title')}》 {format_timecode(r['start_ms'])}",
    }


def _ocr_result(db: Database, r: dict[str, Any], query: str,
                visual_types: list[str] | None, wanted: list[str] | None = None,
                units: list[str] | None = None,
                aliases: list[str] | None = None) -> dict[str, Any] | None:
    if not _matches_visual(db, r["video_id"], r["start_ms"], r["end_ms"], visual_types):
        return None
    video = db.get_video(r["video_id"]) or {}
    text = r.get("text") or ""
    matched = _matched_terms(text, query, aliases)
    score = _score_from_rank(r.get("rank"))
    if normalize_text(query).lower() in normalize_text(text).lower():
        score = min(1.0, score + 0.15)
    labels = sorted({v["label"] for v in db.get_visual_segments(r["video_id"], r["start_ms"], r["end_ms"], limit=5)})
    why_extra = ""
    if wanted and any(x in wanted for x in labels):
        score = min(1.0, score + 0.12)
        why_extra = "视觉结构匹配"
    score = _rerank(score, text, query=query, units=units or [])
    if not score and query not in matched:
        # Only a curated synonym matched: report weak evidence, not "no match".
        score = SYNONYM_ONLY_FLOOR
    eid = stable_id("ev", r["video_id"], r["start_ms"], r["end_ms"], "ocr")
    needle = query if query in matched else (matched[0] if matched else query)
    return {
        "evidence_id": eid,
        "video_id": r["video_id"],
        "title": video.get("title"),
        "start_ms": int(r["start_ms"]),
        "end_ms": int(r["end_ms"]),
        "timecode": format_timecode(r["start_ms"]),
        "score": round(score, 4),
        "modalities": ["ocr"],
        "snippet": _clip(text, needle),
        "source": "ocr_track",
        "confidence": r.get("confidence"),
        "ocr_reliable": _ocr_reliable(r.get("confidence")),
        "visual_types": labels,
        "matched_terms": matched,
        "why": _hit_why("画面 OCR", query, matched, why_extra),
        "citation": f"《{video.get('title')}》 {format_timecode(r['start_ms'])}",
    }


def _media_end(video: dict[str, Any]) -> int:
    return int(video.get("duration_ms") or 0)


def _fit_request_times(video: dict[str, Any], *, at_ms: int | None = None, start_ms: int | None = None,
                        end_ms: int | None = None) -> dict[str, Any]:
    """Fit a request to what the media can answer, instead of failing on rounding.

    Two real calls from 2026-11-15 cost a round trip each and returned nothing:
    `read --start 18:50 --end 22:14` on a 22:13.100 video (0.9s over), and
    `read --start 940000 --end 1130000` where the numbers were milliseconds.
    An end within a small tolerance of the media end is clamped (reading "to the
    end" is legitimate); a bare number whose millisecond reading is inside the
    media is a unit slip, not an out-of-range request. A request that is genuinely
    far outside still raises in _require_in_range.
    """
    media_end = _media_end(video)
    fitted: dict[str, Any] = {
        "at_ms": at_ms, "start_ms": start_ms, "end_ms": end_ms,
        "unit_fixed": False, "clamped_end": False, "clamped_at": False, "clamped_ms": None,
    }
    if not media_end:
        return fitted
    # Only a wildly-out-of-range number is a unit slip: 940000 (seconds) is 705x a
    # 22-minute video, while a 20s request on a 10s clip is just over the end and
    # must stay an error.
    slip_floor = max(media_end * 20, 60 * 60 * 1000)
    for key in ("at_ms", "start_ms", "end_ms"):
        value = fitted[key]
        if value is not None and value > slip_floor and value // 1000 <= media_end:
            fitted[key] = int(value // 1000)
            fitted["unit_fixed"] = True
            fitted["clamped_ms"] = int(value // 1000)
    tolerance = max(2_000, media_end // 100)
    if fitted["end_ms"] is not None and media_end < fitted["end_ms"] <= media_end + tolerance:
        fitted["end_ms"] = media_end
        fitted["clamped_end"] = True
    if fitted["at_ms"] is not None and media_end <= fitted["at_ms"] <= media_end + tolerance:
        fitted["at_ms"] = max(0, media_end - 1)
        fitted["clamped_at"] = True
    return fitted





# How far a stored OCR anchor may be from the asked moment and still answer it.
# Beyond this the answer belongs to another moment: read the requested frame instead.
OCR_FALLBACK_MAX_MS = 5000
# A sampled frame further than this from the asked moment is not "that moment" — pull
# an exact frame instead (one seek, and then the text really belongs to the time).
OCR_FRAME_FAR_MS = 1000
# Text shipped next to a picture must come from that picture's frame. A track from
# another frame is another moment's text (reproduced: image 1.5s + text 2.275s).
OCR_SAME_FRAME_MS = 250
# Bumped whenever the meaning of the stored analysis changes (0.2: lazy OCR, tri-state
# visual labels, pixel-difference dedupe, exponential sharpness). Older records are
# reported as stale instead of being silently presented as current.
ANALYSIS_VERSION = "0.2"
# How many videos a library-wide fallback scans. The literal fallback is a Python
# scan (measured 5x slower at 120 videos than at 50), so it needs a bound that is
# larger than the old 50 but not unbounded.
SEARCH_TARGET_LIMIT = 200
# An explicit `ocr-index` run is bounded like the ingest OCR budget: 240 frames is
# the same ceiling `--ocr-budget` accepts, so one command cannot read a whole hour.
OCR_INDEX_MAX_FRAMES = 240


def _nearest_frame(frames: list[dict[str, Any]], at_ms: int) -> tuple[str, int] | None:
    """The sampled frame closest to `at_ms`, as (path, pts_ms)."""
    best: tuple[str, int] | None = None
    best_delta: int | None = None
    for frame in frames or []:
        path = frame.get("path")
        if not path:
            continue
        pts = int(frame.get("pts_ms") or 0)
        delta = abs(pts - int(at_ms))
        if best_delta is None or delta < best_delta:
            best, best_delta = (str(path), pts), delta
    return best


def _nearest_frame_path(frames: list[dict[str, Any]], at_ms: int) -> str | None:
    picked = _nearest_frame(frames, at_ms)
    return picked[0] if picked else None


def _extract_evidence_frame(cfg: Config, video: dict[str, Any], video_id: str,
                            at_ms: int) -> tuple[str | None, str | None]:
    # Pull one exact frame for an evidence bundle. The error is returned instead of
    # swallowed: an extraction failure is why the bundle falls back to a sampled
    # frame, and the caller has to say so.
    try:
        out = ensure_dir(cfg.derived_dir / video_id / "frames") / f"evidence_{int(at_ms)}.jpg"
        extract_frame(video["source_path"], int(at_ms), out, width=1600, fmt="jpg")
        return str(out), None
    except Exception as exc:  # noqa: BLE001 - the caller reports it
        return None, f"{type(exc).__name__}: {exc}"


def _evidence_warnings(db: Database, video: dict[str, Any], extra: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Warnings an evidence bundle must carry, not just `overview`.

    A citation from an analysis written by an older version, or from a record whose
    rows were emptied, used to come back with an empty warning list — an empty success.
    """
    warnings = list(video.get("warnings") or []) + list(extra)
    version = str(video.get("analysis_version") or "")
    if version != ANALYSIS_VERSION:
        warnings.append(_warn(
            "STALE_ANALYSIS",
            f"这条记录是旧版分析（{version or '未知'}），当前版本 {ANALYSIS_VERSION}",
            remedy="video2agent ingest <source> --force 重扫可更新标签与抽帧。",
            severity="info",
        ))
    video_id = str(video.get("id") or "")
    try:
        has_rows = db.has_analysis(video_id)
    except Exception:
        # A DB error is not evidence of an empty analysis.
        has_rows = True
    if not has_rows:
        warnings.append(_warn(
            "EMPTY_ANALYSIS",
            "这条记录状态是 ready，但没有任何转写或抽帧",
            remedy="重新 ingest（--force）；若仍为空，检查源文件或日志。",
            severity="warning",
        ))
    return warnings


CANDIDATE_WINDOW_MS = 15000


def _candidate_shots(scenes: list[dict[str, Any]], duration_ms: int) -> list[dict[str, Any]]:
    """Scene shots, or fixed windows when the record has no scene cuts."""
    shots: list[dict[str, Any]] = []
    for scene in scenes:
        start = max(0, int(scene.get("start_ms") or 0))
        end = int(scene.get("end_ms") or 0)
        if end > start:
            shots.append({"start_ms": start, "end_ms": min(end, duration_ms or end)})
    if shots:
        return shots
    total = max(0, duration_ms)
    start = 0
    while start < total:
        shots.append({"start_ms": start, "end_ms": min(total, start + CANDIDATE_WINDOW_MS)})
        start += CANDIDATE_WINDOW_MS
    return shots


def _evenly_pick(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not items:
        return []
    if len(items) <= count:
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]
    idx = sorted({round(i * (len(items) - 1) / (count - 1)) for i in range(count)})
    return [items[i] for i in idx]


SHEET_TILE = (320, 180)


def _sheet_layout(count: int, max_cols: int = 4) -> tuple[int, int]:
    """Columns/rows for `count` tiles with the fewest empty cells.

    The sheet must never show blank cells: the caller may have fewer candidates
    than nine (fewer shots, missing keyframes), and a fixed 3-column layout then
    leaves holes. Ties prefer a wider sheet, which reads better than a tall one.
    """
    if count <= 1:
        return 1, 1
    if count == 2:
        return 2, 1
    best = None
    for cols in range(2, min(max_cols, count) + 1):
        rows = (count + cols - 1) // cols
        empty = cols * rows - count
        width = cols * SHEET_TILE[0]
        height = rows * (SHEET_TILE[1] + 22)
        # Log distance keeps 4x2 (wide) ahead of 2x4 (tall) for seven tiles,
        # instead of letting the absolute ratio favour the tall layout.
        key = (empty, abs(math.log((width / height) / (16 / 9))), -cols)
        if best is None or key < best[0]:
            best = (key, cols, rows)
    return best[1], best[2]


def _montage(cfg: Config, video_id: str, tiles: list[dict[str, Any]], *,
             filename: str = "montage_sheet.jpg",
             max_tiles: int = 9) -> tuple[str | None, list[dict[str, Any]]]:
    """Tile picture paths into one labelled image, re-flowing to the real count.

    One image with nine tiles replaces nine `frames --at` calls when the question
    is "which of these looks like X". Tiles are 320x180, so small text still
    needs `frames --crop --scale`; the layout has no blank cells (except a
    seven-tile sheet, which no practical rectangle fills).
    """
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont

    chosen: list[tuple[Any, dict[str, Any]]] = []
    for tile in tiles[:max_tiles]:
        path = str(tile.get("path") or "")
        if not path or not Path(path).exists():
            continue
        try:
            with PILImage.open(path) as img:
                thumb = img.convert("RGB")
                ratio = max(SHEET_TILE[0] / thumb.width, SHEET_TILE[1] / thumb.height)
                thumb = thumb.resize((max(1, int(thumb.width * ratio)), max(1, int(thumb.height * ratio))),
                                     PILImage.Resampling.LANCZOS)
                left = max(0, (thumb.width - SHEET_TILE[0]) // 2)
                top = max(0, (thumb.height - SHEET_TILE[1]) // 2)
                thumb = thumb.crop((left, top, left + SHEET_TILE[0], top + SHEET_TILE[1]))
        except Exception:
            continue
        chosen.append((thumb, tile))
    if not chosen:
        return None, []
    cols, rows = _sheet_layout(len(chosen))
    label_h = 22
    sheet = PILImage.new("RGB", (SHEET_TILE[0] * cols, (SHEET_TILE[1] + label_h) * rows), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    meta: list[dict[str, Any]] = []
    for position, (thumb, tile) in enumerate(chosen):
        x = (position % cols) * SHEET_TILE[0]
        y = (position // cols) * (SHEET_TILE[1] + label_h)
        sheet.paste(thumb, (x, y))
        draw.rectangle((x, y + SHEET_TILE[1], x + SHEET_TILE[0], y + SHEET_TILE[1] + label_h), fill=(14, 14, 14))
        label = str(tile.get("label") or "")
        draw.text((x + 6, y + SHEET_TILE[1] + 5), label, fill=(235, 235, 235), font=font)
        item = {"timecode": label, "tile": position}
        if tile.get("t_ms") is not None:
            item["t_ms"] = int(tile["t_ms"])
        if tile.get("index") is not None:
            item["index"] = int(tile["index"])
        meta.append(item)
    target = ensure_dir(cfg.derived_dir / video_id / "frames") / filename
    sheet.save(target, "JPEG", quality=85)
    return str(target), meta


def _candidate_sheet(cfg: Config, video_id: str, picks: list[dict[str, Any]],
                     frames: list[dict[str, Any]], *,
                     max_tiles: int = 9) -> tuple[str | None, list[dict[str, Any]]]:
    """Montage of the candidate keyframes (up to 9, one and the same image)."""
    path_by_ms = {int(f["pts_ms"]): str(f["path"]) for f in frames if f.get("path")}
    tiles = []
    for shot in picks[:max_tiles]:
        path = path_by_ms.get(int(shot["keyframe_ms"]))
        if not path:
            continue
        tiles.append({"path": path, "label": format_timecode(int(shot["keyframe_ms"])),
                      "t_ms": int(shot["keyframe_ms"]), "index": int(shot["_i"])})
    if not tiles:
        return None, []
    return _montage(cfg, video_id, tiles,
                    filename=f"candidates_sheet_{len(tiles)}_{int(tiles[0]['t_ms'])}_{int(tiles[-1]['t_ms'])}.jpg",
                    max_tiles=max_tiles)


def candidates(cfg: Config, video_id: str, *, query: str | None = None,
               limit: int = 8, images: bool = False) -> dict[str, Any]:
    """Candidate shots for a question: timecodes and keyframes, no images.

    The answer to "which segment shows X" can sit in one of dozens of 10s clips
    where lexical search finds nothing; this lists shots (scene cuts, or 15s
    windows without scenes) with their overlapping transcript/OCR text, so the
    model can inspect a few timecodes instead of scanning the whole video. When
    no shot matches the query, it says so and spreads the candidates in time.
    """
    limit = max(1, min(30, int(limit or 8)))
    with Database(cfg.db_path) as db:
        video = require_ready(db.get_video(video_id), video_id)
        duration_ms = int(video.get("duration_ms") or 0)
        shots = _candidate_shots(db.get_scenes(video_id), duration_ms)
        segments = db.get_segments(video_id, limit=10000)
        ocr = db.get_ocr_tracks(video_id, limit=2000)
        frames = sorted((f for f in db.get_frames(video_id, limit=1000) if f.get("path")),
                        key=lambda f: int(f["pts_ms"] or 0))
    for number, shot in enumerate(shots):
        shot["_i"] = number
        parts = [str(s.get("text") or "") for s in segments
                 if int(s.get("end_ms") or 0) > shot["start_ms"]
                 and int(s.get("start_ms") or 0) < shot["end_ms"]]
        parts += [str(t.get("text") or "") for t in ocr
                  if int(t.get("end_ms") or 0) > shot["start_ms"]
                  and int(t.get("start_ms") or 0) < shot["end_ms"]]
        shot["text"] = normalize_text(" ".join(p for p in parts if p))
        # The nearest sampled frame is enough: `frames --at` extracts the exact
        # picture, and candidates costs no image by itself.
        shot["keyframe_ms"] = shot["start_ms"]
        if frames:
            middle = (shot["start_ms"] + shot["end_ms"]) // 2
            nearest = min(frames, key=lambda f: abs(int(f["pts_ms"] or 0) - middle))
            shot["keyframe_ms"] = int(nearest["pts_ms"] or 0)
    units = query_units(to_simplified(normalize_text(query or ""))) if query else []
    for shot in shots:
        shot["matched"] = count_unit_matches(shot["text"], units) if units else 0
    warnings: list[dict[str, Any]] = []
    if units:
        if max((s["matched"] for s in shots), default=0) == 0:
            picks = _evenly_pick(shots, limit)
            warnings.append({
                "code": "NO_TEXT_MATCH",
                "message": "所有候选片段都没匹配到查询词；按时间均匀给出，请直接看关键帧（frames --at）。",
            })
        else:
            picks = sorted(shots, key=lambda s: (-s["matched"], s["start_ms"]))[:limit]
    else:
        picks = _evenly_pick(shots, limit)
    sheet, sheet_tiles = _candidate_sheet(cfg, video_id, picks, frames) if images else (None, [])
    payload: dict[str, Any] = {
        "ok": True,
        "video_id": video_id,
        "query": query,
        "shots": len(shots),
        "returned": len(picks),
        "candidates": [{
            "index": int(shot["_i"]),
            "start_ms": shot["start_ms"],
            "end_ms": shot["end_ms"],
            "timecode": format_timecode(shot["start_ms"]),
            "keyframe_ms": shot["keyframe_ms"],
            "keyframe_timecode": format_timecode(shot["keyframe_ms"]),
            "matched_units": shot["matched"],
            "text": shot["text"][:160],
        } for shot in picks],
        "warnings": warnings,
    }
    if sheet:
        # One montage instead of one image per candidate; `frames --at` + `--crop`
        # is still the way to read small text on a tile.
        payload["sheet"] = sheet
        payload["sheet_tiles"] = sheet_tiles
        payload["images"] = [sheet]
    return payload


def _require_in_range(video: dict[str, Any], *, at_ms: int | None = None,
                      start_ms: int | None = None, end_ms: int | None = None) -> int:
    """One boundary rule for evidence/transcript/frames.

    Past-the-end requests used to be silently accepted: evidence returned an
    inverted range, transcript returned an empty success, frames raised a bare
    E_FRAME. A citation that cannot exist must be an error with a remedy.
    """
    media_end = _media_end(video)
    if not media_end:
        raise Video2AgentError(
            "E_NO_DURATION",
            "这条记录没有可用的时长，无法定位时刻",
            "重新 ingest 该视频（媒体探测失败或记录被手工改过）。",
        )
    declared = int(round(float((video.get("meta") or {}).get("duration") or 0) * 1000))
    claim = f"，平台标称 {format_duration(declared)}" if declared and declared > media_end else ""
    # A caller that read a rounded duration ("04:24" for 4:23.918) should be able
    # to fix the call without another round-trip.
    usable = (f"最后可引用时刻 {format_timecode(media_end - 1)}（media_end_ms={media_end}）。"
              "参数里的纯数字按秒解析；毫秒请写 1234ms 或 HH:MM:SS.mmm。")
    # A model that has the millisecond number in hand (548000 for 9:08) used to
    # get "152 小时" with no hint; say which value was probably a unit slip.
    # The value arrives in ms (a bare number is read as seconds). If reading that
    # number as milliseconds would have been inside the media, the caller slipped
    # a unit: say which number to pass instead (548000 -> 548 seconds / 548000ms).
    slipped = [v for v in (at_ms, start_ms, end_ms)
               if v is not None and media_end and v > media_end and v // 1_000 <= media_end]
    if slipped:
        original = slipped[0] // 1000
        usable += (f" 参数 {original} 看起来是把毫秒当成了秒（等于 {format_duration(slipped[0])}），"
                   f"应传 {original // 1000}（秒）或 {original}ms。")
    if declared and declared > media_end + 1_000:
        remedy = (
            f"媒体实际只有 {format_timecode(media_end)}{claim}。{usable}"
            "可能是充电专属/试看或下载截断；用范围内的时刻，或带登录/换清晰度后 --force 重跑。"
        )
    else:
        remedy = (
            f"媒体结尾是 {format_timecode(media_end)}；把 --at/--end 改到该时刻以内。{usable}"
            "记录里的平台时长与媒体一致，没有检测到下载截断。"
        )
    if at_ms is not None and at_ms >= media_end:
        raise Video2AgentError(
            "E_OUT_OF_RANGE",
            f"请求 {format_timecode(at_ms)} 超出可引用范围（媒体 {format_timecode(media_end)}）",
            remedy,
        )
    if start_ms is not None and start_ms >= media_end:
        raise Video2AgentError(
            "E_OUT_OF_RANGE",
            f"时间范围起点 {format_timecode(start_ms)} 已超出媒体结尾（{format_timecode(media_end)}）",
            remedy,
        )
    if end_ms is not None and end_ms > media_end:
        raise Video2AgentError(
            "E_OUT_OF_RANGE",
            f"时间范围结尾 {format_timecode(end_ms)} 超出媒体结尾（{format_timecode(media_end)}）",
            remedy,
        )
    if start_ms is not None and end_ms is not None and end_ms <= start_ms:
        raise Video2AgentError(
            "E_OUT_OF_RANGE",
            f"时间范围为空：起点 {format_timecode(start_ms)} 不早于结尾 {format_timecode(end_ms)}",
            "把 --start 放到 --end 之前。",
        )
    return media_end


def require_ready(video: dict[str, Any] | None, video_id: str) -> dict[str, Any]:
    """One readiness rule for every read: a missing or unfinished video is an error.

    search/map/transcript used to answer `ok:true` with empty results for these,
    which reads as "the video does not contain it" (the worst possible answer).
    """
    if not video:
        raise Video2AgentError("E_NOT_FOUND", f"Video not found: {video_id}", "Run video2agent list.")
    if str(video.get("status") or "") != "ready":
        raise not_ready_error(video_id, video.get("status"))
    return video


def _evenly_spaced(frames: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Pick frames across a range instead of clustering at its start."""
    ordered = sorted(frames, key=lambda f: int(f.get("pts_ms") or 0))
    if count <= 0 or not ordered:
        return []
    if len(ordered) <= count:
        return ordered
    if count == 1:
        return [ordered[0]]
    idxs = [round(i * (len(ordered) - 1) / (count - 1)) for i in range(count)]
    return [ordered[i] for i in idxs]


def _ocr_tiled(image_path: str | Path, *, config_path: str | None = None,
               tiles: int = 3, overlap: float = 0.12) -> list[dict[str, Any]]:
    """Read one frame as overlapping tiles, so small text keeps its pixels.

    A full 1280px frame downsamples a phone screen or a scoreboard to a few
    pixels per glyph. Tiling at native resolution raises OCR recall; duplicate
    lines across overlaps are collapsed by normalized text.
    """
    source = Path(str(image_path))
    boxes: list[dict[str, Any]] = []
    with Image.open(source) as img:
        width, height = img.size
        tile_w, tile_h = max(1, width // tiles), max(1, height // tiles)
        pad = int(tile_w * overlap)
        for row in range(tiles):
            for col in range(tiles):
                left = max(0, col * tile_w - pad)
                top = max(0, row * tile_h - pad)
                right = min(width, (col + 1) * tile_w + pad)
                bottom = min(height, (row + 1) * tile_h + pad)
                tile_path = source.with_name(f"{source.stem}_t{row}{col}{source.suffix}")
                try:
                    img.crop((left, top, right, bottom)).save(tile_path, quality=92)
                    for box in ocr_image(tile_path, config_path=config_path):
                        bbox = box.get("bbox")
                        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                            bbox = [float(bbox[0]) + left, float(bbox[1]) + top,
                                    float(bbox[2]) + left, float(bbox[3]) + top]
                        boxes.append({**box, "bbox": bbox, "tile": [row, col]})
                finally:
                    try:
                        tile_path.unlink(missing_ok=True)
                    except OSError:
                        pass
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for box in boxes:
        key = normalize_text(str(box.get("text") or "")).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(box)
    return unique


def _local_ocr_boxes(image_path: str | Path, config_path: str | None, tiled: bool) -> list[dict[str, Any]]:
    if not tiled:
        return ocr_image(image_path, config_path=config_path)
    return _ocr_tiled(image_path, config_path=config_path)


OCR_WINDOW_MAX_FRAMES = 15
# Two workers beat four on a CPU laptop (measured 17.5 s vs 29.3 s for 15
# frames): each worker owns a RapidOCR engine, and more engines only fight for
# the same cores.
OCR_WINDOW_WORKERS = 2


def _frame_signature(path: str | Path) -> list[int] | None:
    try:
        with Image.open(str(path)) as img:
            return list(img.convert("L").resize((32, 32)).getdata())
    except Exception:
        return None


def _signature_diff(a: list[int] | None, b: list[int] | None) -> int:
    if not a or not b or len(a) != len(b):
        return 255
    return max(abs(x - y) for x, y in zip(a, b))


def _ocr_window_cache_path(cfg: Config, video: dict[str, Any], *, start: int, end: int,
                           fps: int, max_frames: int, tiles: bool) -> Path:
    """Key on the source + OCR config, so a re-ingest or new config misses."""
    source = str(video.get("source_path") or "")
    try:
        stat = os.stat(source)
        source_mtime, source_size = int(stat.st_mtime), int(stat.st_size)
    except OSError:
        source_mtime, source_size = 0, 0
    config = str(cfg.get("ocr_local_config") or "")
    try:
        config_mtime = int(os.stat(config).st_mtime) if config else 0
    except OSError:
        config_mtime = 0
    payload = {
        "v": 2,
        "video_id": video.get("id"),
        "start": int(start), "end": int(end), "fps": int(fps),
        "max_frames": int(max_frames), "tiles": bool(tiles),
        "source": [source_mtime, source_size], "config": [config, config_mtime],
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return ensure_dir(cfg.derived_dir / str(video.get("id")) / "cache") / f"ocrwin_{digest}.json"


def ocr_window(cfg: Config, video_id: str, *, start_ms: int, end_ms: int,
               fps: int = 2, tiles: bool = False,
               max_frames: int = OCR_WINDOW_MAX_FRAMES) -> dict[str, Any]:
    """OCR every frame of a short window, so text that changes over time is seen.

    A phone screen can show one line at 0:59 and a different line at 1:02; a
    single `evidence --at` frame only ever returns one of them. Lines are
    deduplicated only when consecutive, so a change is never hidden.
    """
    with Database(cfg.db_path) as db:
        video = require_ready(db.get_video(video_id), video_id)
        _require_media(video)
        fitted = _fit_request_times(video, start_ms=int(start_ms), end_ms=int(end_ms))
        start = int(fitted["start_ms"] or 0)
        end = int(fitted["end_ms"] or 0)
        _require_in_range(video, start_ms=start, end_ms=end)
    if end <= start:
        raise Video2AgentError("E_ARGS", "区间为空：--end 必须晚于 --start", "把 --end 放到 --start 之后。")
    cache_path = _ocr_window_cache_path(
        cfg, video, start=start, end=end, fps=int(fps or 2),
        max_frames=int(max_frames or OCR_WINDOW_MAX_FRAMES), tiles=bool(tiles))
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("ok"):
                cached["cached"] = True
                return cached
        except (OSError, ValueError):
            pass
    step = max(125, int(1000 / max(1, min(4, int(fps or 2)))))
    times = list(range(start, end + 1, step))
    planned = len(times)
    cap = max(1, min(OCR_WINDOW_MAX_FRAMES, int(max_frames or OCR_WINDOW_MAX_FRAMES)))
    sampled = planned > cap
    if sampled:
        if cap == 1:
            times = [times[(planned - 1) // 2]]
        else:
            times = sorted({times[round(i * (planned - 1) / (cap - 1))] for i in range(cap)})
    out_dir = ensure_dir(cfg.derived_dir / video_id / "frames")
    config_path = str(cfg.get("ocr_local_config") or "") or None
    lines: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if sampled:
        warnings.append(_warn(
            "OCR_WINDOW_SAMPLED",
            f"窗口需要 {planned} 帧，只读了 {len(times)} 帧；两次取样之间的短暂文字可能看不到。",
            severity="warn",
            remedy="缩小 --start/--end，或提高 --fps / --max 到覆盖整个窗口。",
        ))
    scanned = 0
    skipped = 0
    missing = 0
    failed_reads = 0
    last_signature: list[int] | None = None
    created: list[Path] = []
    batch = extract_frames_batch(video["source_path"], times, out_dir, width=1280,
                                 prefix=f"ocrwin_batch_{int(time.time() * 1000)}")
    created.extend(batch.values())
    to_read: list[tuple[int, Path]] = []
    for t in times:
        frame = batch.get(t)
        if frame is None:
            frame = out_dir / f"ocrwin_{int(time.time() * 1000)}_{t}.jpg"
            try:
                extract_frame(video["source_path"], t, frame, width=1280)
            except Exception:
                missing += 1
                continue
            created.append(frame)
        signature = _frame_signature(frame)
        # Only an unchanged picture is skipped. A small text change on a static
        # screen can stay under a large pixel threshold, so the old <=8 rule
        # could miss a line; <=2 keeps the static-banner win without that risk.
        if last_signature is not None and _signature_diff(last_signature, signature) <= 2:
            skipped += 1
            continue
        last_signature = signature
        to_read.append((t, frame))

    def _read(item: tuple[int, Path]) -> tuple[int, list[dict[str, Any]], Exception | None]:
        t, frame = item
        try:
            return t, _local_ocr_boxes(frame, config_path, tiles), None
        except Exception as exc:  # noqa: BLE001 - one unreadable frame must not kill the window
            return t, [], exc

    # OCR is the expensive part (measured ~2.4 s/frame); reading four frames at
    # once keeps the order by resolving the futures in submission order.
    results: list[tuple[int, list[dict[str, Any]], Exception | None]] = []
    if to_read:
        # Warm the availability probe in the main thread: concurrent first calls
        # raced and reported "OCR not installed" for every worker but one.
        try:
            ocr_available()
        except Exception:
            pass
        with ThreadPoolExecutor(max_workers=min(OCR_WINDOW_WORKERS, len(to_read))) as pool:
            futures = [pool.submit(_read, item) for item in to_read]
            for future in futures:
                results.append(future.result())
    for t, boxes, error in results:
        if error is not None:
            failed_reads += 1
            warnings.append(_warn("OCR_FRAME_SKIPPED", f"{format_timecode(t)} 读字失败，已跳过：{error}",
                                  severity="warning", remedy="换更小的窗口或单帧 --at 重试。"))
            continue
        scanned += 1
        text = normalize_text(" ".join(str(b.get("text") or "") for b in boxes))
        if text and (not lines or lines[-1]["text"] != text):
            lines.append({"t_ms": t, "timecode": format_timecode(t), "text": text})
    for frame in created:
        try:
            frame.unlink(missing_ok=True)
        except OSError:
            pass
    # Older versions left `ocrwin_*` behind; sweep anything an hour old so a
    # crashed call does not accumulate frames forever.
    for stale in out_dir.glob("ocrwin_*.jpg"):
        try:
            if time.time() - stale.stat().st_mtime > 3600:
                stale.unlink(missing_ok=True)
        except OSError:
            pass
    if missing:
        warnings.append(_warn(
            "OCR_WINDOW_GAPS",
            f"有 {missing} 帧取不出来，窗口覆盖不完整。",
            severity="warning",
            remedy="检查源文件是否被截断；必要时缩小窗口重试。",
        ))
    if not lines and not (planned > 0 and scanned == 0):
        warnings.append(_warn("OCR_EMPTY", "这个窗口里没有读到文字。", severity="info",
                              remedy="确认画面有字；必要时缩小窗口或对单帧用 --ocr-tiles。"))
    # A window where every planned frame failed is not an empty success: say the
    # read could not happen so the caller does not answer "there is no text".
    # Also when every planned frame could not be extracted (missing): the read
    # never happened, so this is not "the window has no text".
    attempted = len(times)
    all_failed = attempted > 0 and scanned == 0 and (failed_reads > 0 or missing >= attempted)
    payload = {
        "ok": not all_failed,
        "video_id": video_id,
        "start_ms": start,
        "end_ms": end,
        "frames_planned": planned,
        "sampled": sampled,
        "frames_scanned": scanned,
        "frames_skipped": skipped,
        "frames_missing": missing,
        "frames_failed": failed_reads,
        "lines": lines,
        "line_count": len(lines),
        "warnings": warnings,
        "cached": False,
    }
    if all_failed:
        payload["error"] = {
            "code": "E_OCR_UNAVAILABLE",
            "message": "这个窗口的每一帧 OCR 都失败，不能当作“没有文字”。",
            "remedy": "检查 OCR 安装/模型（video2agent doctor），或缩小窗口重试。",
        }
    # Cache a complete read only: a partial result (missing frames or failed OCR
    # reads) must not become permanent just because one frame succeeded.
    if missing == 0 and failed_reads == 0 and scanned > 0:
        try:
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(cache_path)
        except OSError:
            pass
    return payload


def _evidence_snapshot_id(video: dict[str, Any], video_id: str, *, at_ms: int | None,
                           start: int, end: int, payload: dict[str, Any]) -> str:
    """Content-addressed bundle id, so a citation is a snapshot and not a slot.

    The id used to be video + range only, written with INSERT OR REPLACE: asking
    the same range again (after a re-ingest or a new OCR read) silently replaced
    yesterday's evidence, and an old citation then resolved to new content. The
    id now includes the source version and the evidence itself, so identical
    answers collapse and changed answers coexist.
    """
    basis = {
        "video": video_id,
        "at_ms": None if at_ms is None else int(at_ms),
        "start": int(start),
        "end": int(end),
        "source": [video.get("sha256"), video.get("source_size"), video.get("source_mtime_ns")],
        "frames": [int(x) for x in (payload.get("image_frame_ms") or [])],
        "ocr": [[int(r.get("start_ms") or 0), str(r.get("text") or "")[:160]]
                for r in (payload.get("ocr") or [])],
        "transcript": [[int(t.get("start_ms") or 0), str(t.get("text") or "")[:120]]
                       for t in (payload.get("transcript") or [])],
        "visual": [[int(v.get("start_ms") or 0), str(v.get("label") or "")]
                   for v in (payload.get("visual") or [])],
    }
    return stable_id("ev", json.dumps(basis, sort_keys=True, ensure_ascii=False), length=20)


def evidence(cfg: Config, *, video_id: str, at_ms: int | None = None, start_ms: int | None = None,
             end_ms: int | None = None, evidence_id: str | None = None, image_budget: int = 2,
             detail: str = "read", ocr_tiles: bool = False) -> dict[str, Any]:
    with Database(cfg.db_path) as db:
        video = require_ready(db.get_video(video_id), video_id)
        if evidence_id:
            # The video id is part of the lookup: asking for B with A's bundle id used
            # to return A's payload.
            row = db.one("SELECT * FROM evidence WHERE id=? AND video_id=?", [evidence_id, video_id])
            if not row:
                raise Video2AgentError(
                    "E_NOT_FOUND",
                    f"Evidence bundle not found: {evidence_id}",
                    "The id comes from a previous evidence call; ids from search results are not bundles.",
                )
            payload = json.loads(row.get("payload_json") or "{}")
            stored = payload.get("images") or []
            existing = _existing_images(stored)
            payload["images"] = existing
            warnings = list(payload.get("warnings") or [])
            if len(existing) != len(stored):
                warnings.append(_warn(
                    "FRAME_MISSING",
                    f"重放时 {len(stored) - len(existing)} 张帧文件已不存在，已从结果中去掉",
                    severity="warning",
                    remedy="重新 ingest 该视频（--force）以重建抽帧。",
                ))
                # Keep frames in lockstep with the surviving images; a dropped
                # file must not leave a timecode pointing at a picture the caller
                # never receives.
                survivors = {str(p) for p in existing}
                if isinstance(payload.get("frames"), list):
                    payload["frames"] = [f for f in payload["frames"] if str((f or {}).get("path") or "") in survivors]
                if isinstance(payload.get("image_frame_ms"), list):
                    kept_ms = {int((f or {}).get("t_ms") or 0) for f in (payload.get("frames") or [])}
                    payload["image_frame_ms"] = [
                        ms for ms in payload["image_frame_ms"] if int(ms or 0) in kept_ms
                    ]
                # The citation must name a picture the caller actually receives.
                if existing:
                    # Map the surviving path back to its own t_ms; a filename like
                    # frame_00003.jpg is a sampled index, not 3 milliseconds.
                    by_path = {}
                    for item in (payload.get("frames") or []):
                        if isinstance(item, dict) and item.get("path") is not None:
                            by_path[str(item["path"])] = int(item.get("t_ms") or 0)
                    first = str(existing[0])
                    stamp = by_path.get(first)
                    if stamp is None:
                        for path_key, t_ms in by_path.items():
                            if os.path.basename(path_key) == os.path.basename(first):
                                stamp = t_ms
                                break
                    if stamp is not None:
                        payload["frame_ms"] = stamp
                        payload["frame_timecode"] = format_timecode(stamp)
                        payload["frame_citation"] = payload["frame_timecode"]
                        payload["citation"] = payload["frame_timecode"]
                else:
                    payload["frame_ms"] = None
                    payload["frame_timecode"] = None
                    payload["frame_citation"] = None
                    payload["citation"] = payload.get("ocr_citation") or format_timecode(
                        int(payload.get("range", {}).get("start_ms") or 0))
                    # No picture and no text means the replay lost its evidence.
                    # Visual labels still count: a slide-only moment has evidence.
                    known_visual = [
                        v for v in (payload.get("visual") or [])
                        if isinstance(v, dict) and str(v.get("label") or "") != "unknown"
                    ]
                    if not payload.get("transcript") and not payload.get("ocr") and not known_visual:
                        payload["empty"] = True
                        payload["citation"] = None
                        # Stale anchors must not survive an empty replay.
                        payload["transcript_citation"] = None
                        payload["ocr_citation"] = None
                        warnings.append(_warn(
                            "NO_EVIDENCE_AT_MOMENT",
                            "重放时图片和文字都已不可用。",
                            severity="warning",
                            remedy="重新 ingest 该视频，或重新调用 evidence。",
                        ))
            payload["warnings"] = _evidence_warnings(db, video, warnings)
            return payload
        range_only = at_ms is None and start_ms is not None and end_ms is not None
        if at_ms is None and start_ms is not None:
            at_ms = start_ms
        if at_ms is not None and int(at_ms) < 0:
            raise Video2AgentError(
                "E_OUT_OF_RANGE",
                f"时间点不能是负数：{at_ms} ms",
                "时间从 0 开始；要引用开头，用 --at 0。",
            )
        at_ms = int(at_ms or 0)
        requested_at = at_ms
        fitted = _fit_request_times(video, at_ms=at_ms, start_ms=start_ms, end_ms=end_ms)
        at_ms, start_ms, end_ms = fitted["at_ms"], fitted["start_ms"], fitted["end_ms"]
        media_end = _require_in_range(video, at_ms=at_ms, start_ms=start_ms, end_ms=end_ms)
        seg = db.get_segment_at(video_id, at_ms) if (start_ms is None and end_ms is None) else None
        if seg:
            start = int(seg["start_ms"])
            end = int(seg["end_ms"])
        else:
            start = int(start_ms if start_ms is not None else max(0, at_ms - 3000))
            end = int(end_ms if end_ms is not None else min(int(video.get("duration_ms") or at_ms + 3000), at_ms + 3000))
        range_start = max(0, start - 1500)
        range_end = min(int(video.get("duration_ms") or end + 1500), end + 1500)
        # Prefer actual transcript overlap, then OCR.
        segs = [s for s in db.get_segments(video_id, range_start, range_end, limit=20)
                if s["end_ms"] > start and s["start_ms"] < end]
        ocr = db.get_ocr_tracks(video_id, start, end, limit=40)
        ocr_warnings: list[dict[str, Any]] = []
        nearest_ocr_ms: int | None = None
        if ocr and at_ms is not None:
            closest = min(ocr, key=lambda r: abs(int(r["start_ms"]) - int(at_ms)))
            gap = abs(int(closest["start_ms"]) - int(at_ms))
            if gap > OCR_FRAME_FAR_MS:
                # The only text in this window belongs to another moment. Do not present
                # it as this one: drop it so the on-demand read below runs.
                nearest_ocr_ms = int(closest["start_ms"])
                ocr_warnings.append(_warn(
                    "OCR_WINDOW_STALE",
                    f"{format_timecode(at_ms)} 附近最近的画面文字在 {format_timecode(nearest_ocr_ms)}"
                    f"（相差 {gap / 1000:.1f} 秒），不是这一刻。",
                    severity="info",
                    remedy="按 nearest_ocr_ms 引用，或加 --images 1 现场读这一帧。",
                ))
                ocr = []
        if not ocr and at_ms is not None and image_budget == 0:
            # Text-only query (no picture to contradict): a nearby anchor may answer,
            # labelled with its own time. When a picture is requested the text has to
            # come from that picture's frame, so no anchor fallback runs there.
            anchors = db.get_ocr_anchors(video_id)
            if anchors:
                nearest = int(min(anchors, key=lambda a: abs(int(a) - at_ms)))
                distance = abs(nearest - int(at_ms))
                if distance <= OCR_FALLBACK_MAX_MS:
                    nearest_ocr_ms = nearest
                    ocr = db.get_ocr_tracks(video_id, nearest_ocr_ms - 1500, nearest_ocr_ms + 1500, limit=40)
                    if ocr:
                        ocr_warnings.append(_warn(
                            "OCR_WINDOW_EMPTY",
                            f"{format_timecode(at_ms)} 这一小段没有 OCR 帧，已回退到 "
                            f"{format_timecode(nearest_ocr_ms)}（相差 {distance / 1000:.1f} 秒）",
                            severity="info",
                            remedy="按 nearest_ocr_ms 引用；要读提问时刻本身，先用 --images 1 让它现场读取那一帧。",
                        ))
        vis = db.get_visual_segments(video_id, start, end, limit=20)
        frames = db.get_frames(video_id, limit=1000)
        if range_only and image_budget > 0:
            in_range = [f for f in frames if start <= int(f.get("pts_ms") or 0) <= end]
            if not in_range:
                # Never substitute a frame outside the requested window: a citation
                # for 10-20s must not point at 0.25s or 45s.
                ocr_warnings.append(_warn(
                    "EVIDENCE_RANGE_EMPTY",
                    f"{format_timecode(start)}–{format_timecode(end)} 范围内没有采样帧。",
                    severity="warning",
                    remedy="换一个更长的时间窗，或用 --at 指向具体时刻现场抽帧。",
                ))
            near = _evenly_spaced(in_range, max(1, image_budget))
        else:
            near = sorted(frames, key=lambda f: abs(int(f["pts_ms"]) - at_ms))[:max(1, image_budget)]
        exact_path: str | None = None
        if not range_only and image_budget > 0 and at_ms is not None and (not near or abs(int(near[0]["pts_ms"]) - at_ms) > 200):
            # Sampled keyframes can be a few hundred ms away. Pull one exact-ish
            # frame for the requested moment; keep the sampled frame as context.
            exact_path, exact_error = _extract_evidence_frame(cfg, video, video_id, int(at_ms))
            if exact_path:
                exact = {"pts_ms": int(at_ms), "path": exact_path, "width": 1600, "height": None,
                         "text_coverage": None, "ocr_status": "exact", "timing_origin": "seek_target"}
                near = [exact, *near]
            elif exact_error:
                ocr_warnings.append(_warn(
                    "FRAME_EXTRACT_FAILED",
                    f"无法为 {format_timecode(at_ms)} 抽取精确帧：{exact_error}",
                    severity="warning",
                    remedy="检查源文件/ffmpeg 后重试；本次只能用最近的采样帧。",
                ))
        # Read the moment on demand. An ingest no longer has to pre-OCR a grid of
        # frames for this window to answer: if it was never read, read a frame and
        # remember it, exactly like a cited anchor.
        #
        # The text is stamped with the time of the frame that was actually read, not
        # with the requested time. With --images 0 there is no exact frame, so the
        # nearest sample can be many seconds away; labelling its text as "at the
        # requested moment" writes wrong timecodes into anchors and the search index.
        image_ms: int | None = None
        ocr_frame_ms: int | None = None
        ocr_read_failed = False
        # The bundle will show a picture of this moment; its text must come from that
        # same frame. Text from another frame (window read or anchor fallback) used
        # to ship with the picture silently (reproduced: image 1.5s + text 2.275s).
        image_frame_ms: int | None = None
        if image_budget > 0:
            if exact_path:
                image_frame_ms = int(at_ms)
            elif near:
                image_frame_ms = int(near[0]["pts_ms"])
        need_read = not ocr
        if image_frame_ms is not None and ocr:
            same_frame = [r for r in ocr if abs(int(r["start_ms"]) - image_frame_ms) <= OCR_SAME_FRAME_MS]
            if same_frame:
                ocr = same_frame
            else:
                # Do not ship another frame's text next to this picture.
                ocr = []
                need_read = True
        if at_ms is not None and need_read and (ocr_available() or (cloud.configured(cfg) and cloud.ocr_enabled(cfg))):
            if exact_path:
                target_path, target_ms = exact_path, int(at_ms)
            else:
                picked = _nearest_frame(near, at_ms)
                target_path, target_ms = (picked if picked else (None, int(at_ms)))
                # A sampled frame can sit many seconds away (measured up to 18s on the
                # library). Reading it would answer a different moment, so pull an exact
                # frame for the asked time instead — one seek, no ambiguity.
                if target_path and abs(int(target_ms) - int(at_ms)) > OCR_FRAME_FAR_MS:
                    exact_path, exact_error = _extract_evidence_frame(cfg, video, video_id, int(at_ms))
                    if exact_path:
                        target_path, target_ms = exact_path, int(at_ms)
                    elif exact_error:
                        ocr_warnings.append(_warn(
                            "FRAME_EXTRACT_FAILED",
                            f"无法为 {format_timecode(at_ms)} 抽取精确帧：{exact_error}",
                            severity="warning",
                            remedy="检查源文件/ffmpeg 后重试；本次读的是最近的采样帧。",
                        ))
            if target_path and not Path(str(target_path)).exists():
                ocr_warnings.append(_warn(
                    "FRAME_MISSING",
                    f"{format_timecode(target_ms)} 的抽帧文件不存在，无法现场识别文字",
                    severity="warning",
                    remedy="重新 ingest 该视频（--force）以重建抽帧。",
                ))
                target_path = None
            if target_path:
                drift = abs(int(target_ms) - int(at_ms))
                # Already read: an earlier call (or ingest) left an anchor here. Only the
                # OCR run is skipped — the tracks must still be read back, otherwise the
                # second question about the same moment returns nothing at all. An
                # anchor is trustworthy because clearing an analysis deletes anchors and
                # rows together; an empty read keeps its anchor on purpose, so it is not
                # re-OCR'd on every question.
                already_read = int(target_ms) in {int(a) for a in db.get_ocr_anchors(video_id)}
                if not already_read:
                    local_ocr_config = str(cfg.get("ocr_local_config") or "") or None
                    try:
                        if cloud.configured(cfg) and cloud.ocr_enabled(cfg):
                            try:
                                boxes = _cloud_ocr_boxes(cfg, target_path, tiles=ocr_tiles)
                            except Video2AgentError as exc:
                                if exc.code == "E_CLOUD_OCR_DESCRIPTION":
                                    ocr_warnings.append(_warn(exc.code, exc.message, severity="info", remedy=exc.remedy))
                                else:
                                    ocr_warnings.append(_warn(exc.code, f"云端画面文字失败，改用本地 OCR：{exc.message}", remedy=exc.remedy))
                                boxes = _local_ocr_boxes(target_path, local_ocr_config, ocr_tiles)
                        else:
                            boxes = _local_ocr_boxes(target_path, local_ocr_config, ocr_tiles)
                        # Reuse the ingest-side track builder so an on-demand read
                        # produces the same records as a pre-read one.
                        fresh = build_ocr_tracks([{"pts_ms": int(target_ms), "ocr": boxes}]) if boxes else []
                        # Record the read even when it found nothing: otherwise every
                        # later call re-runs OCR on the same empty frame.
                        db.set_ocr_anchors(video_id, sorted({*db.get_ocr_anchors(video_id), int(target_ms)}))
                        if fresh:
                            db.insert_ocr_tracks(video_id, fresh)
                            ocr_warnings.append(_warn(
                                "OCR_ON_DEMAND",
                                f"{format_timecode(target_ms)} 这一帧是现场识别的（之前没读过）。"
                                + (f"你问的是 {format_timecode(at_ms)}，实际读的是 {format_timecode(target_ms)}（差 {drift / 1000:.1f} 秒）。"
                                   if drift > 200 else ""),
                                severity="info",
                                remedy="要精确到提问时刻，加 --images 1。",
                            ))
                        else:
                            ocr_warnings.append(_warn(
                                "OCR_EMPTY_FRAME",
                                f"{format_timecode(target_ms)} 这一帧没有识别到文字。"
                                + (f"（你问的是 {format_timecode(at_ms)}，差 {drift / 1000:.1f} 秒）" if drift > 200 else ""),
                                severity="info",
                            ))
                    except OcrFailed as exc:
                        # A failed read is not an empty frame: do not remember it as a
                        # read anchor, and say that the text could not be read.
                        ocr_read_failed = True
                        ocr_warnings.append(_warn(
                            "OCR_FAILED",
                            f"{format_timecode(target_ms)} 的画面文字读取失败：{exc}",
                            severity="warning",
                            remedy="检查本机 OCR 模型/依赖后重试；这次不是「没有文字」。",
                        ))
                    except Exception as exc:  # noqa: BLE001 - surface it, never fake empty
                        ocr_read_failed = True
                        ocr_warnings.append(_warn(
                            "OCR_FAILED",
                            f"{format_timecode(target_ms)} 的画面文字读取失败：{type(exc).__name__}: {exc}",
                            severity="warning",
                            remedy="检查本机 OCR 模型/依赖后重试。",
                        ))
                # Read back around the frame that was actually read, always: with
                # --images 0 it can sit outside the requested window, and querying only
                # the window would return nothing even though the text exists.
                around = db.get_ocr_tracks(
                    video_id,
                    min(int(start), int(target_ms) - 1500),
                    max(int(end), int(target_ms) + 1500),
                    limit=40,
                )
                # Only the frame that was actually read belongs in this bundle.
                ocr = [r for r in around if abs(int(r["start_ms"]) - int(target_ms)) <= OCR_SAME_FRAME_MS]
                ocr_frame_ms = int(target_ms)
        present = [f for f in near if Path(str(f.get("path") or "")).exists()]
        extracted_on_demand = False
        if image_budget > 0 and not present and at_ms is not None:
            # The frame cache can be gone while the media is still here (a local
            # source survives a cache release, and a partial gc can drop files).
            # Cut the requested moment from the media instead of answering a
            # picture request with no picture.
            extracted, extract_error = _extract_evidence_frame(cfg, video, video_id, int(at_ms))
            if extracted:
                present = [{"path": extracted, "pts_ms": int(at_ms)}]
                extracted_on_demand = True
                ocr_warnings.append(_warn(
                    "FRAME_EXTRACTED_ON_DEMAND",
                    f"{format_timecode(at_ms)} 的抽帧缓存不在，已按请求时刻从原片重新抽取。",
                    severity="info",
                ))
            elif extract_error:
                ocr_warnings.append(_warn(
                    "FRAME_EXTRACT_FAILED",
                    f"无法为 {format_timecode(at_ms)} 抽取画面：{extract_error}",
                    severity="warning",
                    remedy="检查源文件是否可读；缓存清理过的视频可重新 ingest 恢复。",
                ))
        if len(present) != len(near) and not extracted_on_demand:
            ocr_warnings.append(_warn(
                "FRAME_MISSING",
                f"{len(near) - len(present)} 张抽帧文件已不存在，已从结果中去掉（未用其他时刻顶替）",
                severity="warning",
                remedy="重新 ingest 该视频（--force）以重建抽帧。",
            ))
        if ocr and ocr_frame_ms is None:
            # The window already had text: name the frame it belongs to instead of
            # falling back to the window start (citation said 17s for text at 20s).
            ocr_frame_ms = int(ocr[0].get("start_ms") or 0) or None
        if ocr and any(_ocr_reliable(o.get("confidence")) is False for o in ocr):
            ocr_warnings.append(_warn(
                "OCR_LOW_CONFIDENCE",
                "这一帧有低置信度画面文字；只作搜索线索，不要逐字引用。",
                severity="info",
                remedy="需要精确文字时放大该区域或换用更清晰的一帧。",
            ))
        if at_ms is not None and not ocr and not ocr_available():
            ocr_warnings.append(_warn(
                "OCR_UNAVAILABLE",
                "OCR 组件不可用，这一帧的文字无法读取",
                severity="warning",
                remedy="pip install \"video2agent[ocr]\" 后重试（本地 OCR 需要 Python 3.11/3.12）。",
            ))
        images = [f["path"] for f in present][:max(0, image_budget)]
        if images:
            image_ms = int(present[0]["pts_ms"])
        image_drift_ms = abs(int(image_ms) - int(at_ms)) if (image_ms is not None and at_ms is not None) else None
        ocr_rows = []
        for row in ocr[:8]:
            text, truncated = _clip_ocr_text(row.get("text"))
            ocr_rows.append({
                "text": text, "text_truncated": truncated,
                "start_ms": row["start_ms"], "end_ms": row["end_ms"],
                "confidence": row.get("confidence"),
                "ocr_reliable": _ocr_reliable(row.get("confidence")),
                "bbox": row.get("bbox"),
            })
        payload = {
            "ok": True,
            "schema_version": "1.0",
            "video_id": video_id,
            "title": video.get("title"),
            # Filled in once the rest of the bundle is known (content-addressed).
            "evidence_id": None,
            "range": {"start_ms": start, "end_ms": end, "timecode": format_timecode(start)},
            # Say what was asked for versus what the media can actually give, so a
            # snapped citation is visible instead of looking exact.
            "requested_ms": None if range_only else (requested_at if requested_at is not None else None),
            "range_requested": bool(range_only),
            "media_end_ms": media_end,
            "requested_timecode": format_timecode(requested_at) if requested_at is not None else None,
            # True only when the requested moment itself was moved (clamped to the
            # media); a transcript segment starting earlier is not a snap.
            "snapped": bool(fitted["clamped_at"] or fitted["clamped_end"]
                            or (at_ms is not None and image_ms is not None and abs(image_ms - at_ms) > 1500)),
            # What the picture actually is, so a citation never pretends to be exact:
            # frame_ms is the moment of images[0] (null when no image is returned), and
            # ocr_frame_ms is the frame the returned text was read from — with
            # --images 0 those are different moments, and the OCR warning names both.
            "frame_ms": image_ms,
            "frame_timecode": format_timecode(image_ms) if image_ms is not None else None,
            "image_drift_ms": image_drift_ms,
            "ocr_frame_ms": ocr_frame_ms,
            # read / failed / unread: a 0-hit answer must not imply "no text".
            "ocr_state": (
                "failed" if ocr_read_failed
                else "read" if ocr_frame_ms is not None
                else "unread"
            ),
            "ocr_frame_timecode": format_timecode(ocr_frame_ms) if ocr_frame_ms is not None else None,
            # Which OCR moment the text really came from when the window was empty.
            "nearest_ocr_ms": nearest_ocr_ms,
            "citation": (
                format_timecode(image_ms) if image_ms is not None
                else format_timecode(ocr_frame_ms) if ocr_frame_ms is not None
                else format_timecode(start)
            ),
            # One citation per modality: copying the generic line for a picture claim is
            # how a wrong timecode reaches a note.
            "frame_citation": format_timecode(image_ms) if image_ms is not None else None,
            "ocr_citation": format_timecode(ocr_frame_ms) if ocr_frame_ms is not None else None,
            "transcript_citation": format_timecode(start),
            "transcript": [
                {"start_ms": s["start_ms"], "end_ms": s["end_ms"], "text": s["text"], "source": s["source"], "confidence": s.get("confidence")}
                for s in segs
            ],
            "ocr": ocr_rows,
            "visual": [
                {"label": v["label"], "score": v["score"], "start_ms": v["start_ms"], "end_ms": v["end_ms"], "signals": v.get("signals")}
                for v in vis
            ],
            # frames and images must describe the same list: frames used to keep a
            # missing frame, so frames[i] and image_urls[i] could name different
            # moments (2000, 25, 4525 vs 2000, 2275, 25, 4525).
            "frames": [
                {"t_ms": f["pts_ms"], "path": f["path"], "width": f.get("width"), "height": f.get("height"),
                 "text_coverage": f.get("text_coverage"), "ocr_status": f.get("ocr_status"),
                 "timing_origin": f.get("timing_origin", "sampled")}
                for f in present[:max(0, image_budget)]
            ],
            "images": images[:max(0, image_budget)],
            "image_frame_ms": [int(f["pts_ms"]) for f in present[:max(0, image_budget)]],
            "detail": detail,
            "warnings": _evidence_warnings(db, video, ocr_warnings),
        }
        payload["evidence_id"] = _evidence_snapshot_id(
            video, video_id, at_ms=at_ms, start=start, end=end, payload=payload)
        # "ok:true" with no text, no picture and no visual segment is not evidence.
        # It used to carry a citation to the range start, so a caller could quote a
        # moment that returned nothing.
        known_visual = [v for v in payload["visual"] if str(v.get("label") or "") != "unknown"]
        has_evidence = bool(payload["transcript"] or payload["ocr"] or payload["images"] or known_visual)
        payload["empty"] = not has_evidence
        if not has_evidence:
            payload["citation"] = None
            payload["transcript_citation"] = None
            payload["warnings"].append(_warn(
                "NO_EVIDENCE_AT_MOMENT",
                f"{format_timecode(at_ms)} 没有可引用的转写、画面文字、视觉片段或图片。",
                severity="info",
                remedy="换一个时间点，或加 --images 1 读取这一帧；不要把这个空结果当作“视频没有内容”。",
            ))
        try:
            db.conn.execute(
                "INSERT OR REPLACE INTO evidence (id,video_id,start_ms,end_ms,modalities,score,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)",
                [payload["evidence_id"], video_id, start, end, "transcript,ocr,visual", 1.0,
                 json.dumps(payload, ensure_ascii=False), now_iso()],
            )
            db.conn.commit()
        except Exception as save_error:
            # A read-only library can still answer; it just cannot cache the bundle.
            payload.setdefault("warnings", []).append(_warn(
                "EVIDENCE_NOT_SAVED",
                f"这次证据没有存进库（{str(save_error)[:80]}）",
                severity="warning",
                remedy="库可能是只读的；换成可写库或检查权限。",
            ))
        return payload


def _require_media(video: dict[str, Any]) -> None:
    """A record can be ready while its media file (and every frame) is gone.

    Saying "move --at inside the range" then sends the user the wrong way; the only
    fix is to ingest the source again. The check also refuses a source that was
    replaced after indexing: old transcript/OCR rows describe the old file, and
    slicing a frame out of a different file would cite a picture the analysis
    never saw.
    """
    source = str(video.get("source_path") or "")
    if not source or source.startswith("http"):
        return
    path = Path(source)
    if not path.exists():
        if video.get("media_released_at"):
            raise Video2AgentError(
                "E_MEDIA_MISSING",
                f"原片已按缓存策略清理：{source}",
                "转写和画面文字仍可搜索；要看原片或取帧，重新 ingest 一次即可恢复。",
            )
        raise Video2AgentError(
            "E_MEDIA_MISSING",
            f"源文件不在了：{source}",
            "重新 ingest 这个视频（--force）；只剩库文件时无法再取帧。",
        )
    try:
        stat = path.stat()
    except OSError:
        return
    stored_size = video.get("source_size")
    stored_mtime = video.get("source_mtime_ns")
    changed = stored_size is not None and int(stat.st_size) != int(stored_size)
    if not changed and stored_mtime is not None and int(stat.st_mtime_ns) != int(stored_mtime):
        # Same size but a new mtime is usually a touch/rewrite: only the content
        # hash can tell. Hashing happens only on that rare path.
        stored_hash = str(video.get("sha256") or "")
        if stored_hash:
            from .util import sha256_file

            try:
                changed = sha256_file(path) != stored_hash
            except OSError:
                changed = False
    if changed:
        raise Video2AgentError(
            "E_SOURCE_CHANGED",
            "源文件在入库后被替换了，旧索引对不上现在的画面",
            "重新 ingest 这个视频（--force），用新文件重建索引；旧时间码的帧不能再引用。",
        )


def _existing_images(paths: list[str]) -> list[str]:
    return [p for p in paths if p and Path(p).exists()]


def _crop_image(path: Path, crop: tuple[float, float, float, float] | None, scale: float) -> tuple[Path, dict[str, Any] | None]:
    """Crop normalized x,y,w,h from a frame and optionally upscale it."""
    if not crop:
        return path, None
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        x, y, cw, ch = crop
        left = max(0, min(w - 1, int(round(x * w))))
        top = max(0, min(h - 1, int(round(y * h))))
        right = max(left + 1, min(w, int(round((x + cw) * w))))
        bottom = max(top + 1, min(h, int(round((y + ch) * h))))
        box = (left, top, right, bottom)
        out = im.crop(box)
        factor = max(1.0, min(3.0, float(scale or 1.0)))
        if factor > 1.0:
            out = out.resize((max(1, int(out.width * factor)), max(1, int(out.height * factor))), Image.Resampling.LANCZOS)
        target = path.with_name(path.stem + "_crop" + path.suffix)
        out.save(target, quality=92)
    return target, {"crop": {"x": x, "y": y, "w": cw, "h": ch}, "scale": factor, "box_px": list(box),
                     "width": out.width, "height": out.height}


DENSE_WINDOW_MAX_MS = 5000
DENSE_FRAME_MAX = 15
DENSE_CANDIDATE_MAX = 30


def _validate_change_budget(mode: str, max_frames: int) -> None:
    if mode == "change" and int(max_frames if max_frames is not None else 12) < 3:
        raise Video2AgentError("E_ARGS", "mode=change 至少需要 3 帧（首、变化点、尾）", "把 --max 设为 3 到 15，或改用 mode=uniform。")


def _dense_times(start_ms: int, end_ms: int, fps: int, max_frames: int,
                 candidate_cap: int | None = None) -> tuple[list[int], list[dict[str, Any]], int]:
    """Sample the whole requested window with a bounded frame count."""
    warnings: list[dict[str, Any]] = []
    if int(start_ms) < 0 or int(end_ms) < 0:
        raise Video2AgentError("E_BAD_TIME", "dense 窗口不能使用负数时间")
    start = int(start_ms)
    end = max(start + 1, int(end_ms))
    if end - start > DENSE_WINDOW_MAX_MS:
        end = start + DENSE_WINDOW_MAX_MS
        warnings.append(_warn("DENSE_WINDOW_CLAMPED", "dense 窗口最多 5 秒，已截到前 5 秒。", severity="info"))
    fps = max(1, min(8, int(fps or 5)))
    cap = max(1, min(DENSE_FRAME_MAX, int(max_frames if max_frames is not None else 12)))
    if candidate_cap is not None:
        cap = max(cap, min(DENSE_CANDIDATE_MAX, int(candidate_cap)))
    step = max(125, int(round(1000 / fps)))
    span = end - start
    if cap == 1:
        return [end], warnings, end
    if span <= step:
        return [start, end], warnings, end
    needed = span / step
    if needed > cap - 1:
        step = max(step, int(round(span / (cap - 1))))
        warnings.append(_warn("DENSE_REDISTRIBUTED", "dense 窗口按帧数重新分配采样点，覆盖整个区间。", severity="info"))
    times = [start]
    t = start + step
    while t < end and len(times) < cap - 1:
        times.append(int(t))
        t += step
    if times[-1] != end:
        times.append(end)
    return times[:cap], warnings, end


def _change_scores(images: list[dict[str, Any]]) -> list[float]:
    """Mean absolute grayscale difference from the previous frame."""
    from PIL import ImageChops, ImageStat
    scores: list[float] = []
    prev = None
    for item in images:
        try:
            with Image.open(str(item["path"])) as img:
                gray = img.convert("L")
                if prev is None:
                    scores.append(0.0)
                else:
                    scores.append(round(ImageStat.Stat(ImageChops.difference(prev, gray)).mean[0], 2))
                prev = gray.copy()
        except Exception:
            scores.append(0.0)
    return scores


WINDOWS_MAX = 9
WINDOWS_COARSE_MS = 10 * 60 * 1000


def frames(cfg: Config, video_id: str, *, at_ms: int | None = None, count: int = 1,
           width: int = 1280, fmt: str = "jpg", crop: tuple[float, float, float, float] | None = None,
           scale: float = 1.0, start_ms: int | None = None, end_ms: int | None = None,
           fps: int = 5, max_frames: int = 12, mode: str = "uniform",
           sheet: bool = False, windows: int | None = None) -> dict[str, Any]:
    if windows is not None and (start_ms is None or end_ms is None):
        raise Video2AgentError(
            "E_ARGS",
            "--windows 需要同时给 --start 和 --end",
            "例如 frames ID --start 00:04:00 --end 00:09:00 --windows 6。",
        )
    with Database(cfg.db_path) as db:
        video = db.get_video(video_id)
        if not video:
            raise Video2AgentError("E_NOT_FOUND", f"Video not found: {video_id}", "Run video2agent list.")
        _require_media(video)
        windowed = start_ms is not None or end_ms is not None
        dense_meta: dict[str, Any] = {}
        warnings: list[dict[str, Any]] = []
        windows_meta: list[dict[str, Any]] = []
        coverage: dict[str, Any] = {}
        if windows is not None:
            fitted = _fit_request_times(video, start_ms=int(start_ms or 0), end_ms=int(end_ms or 0))
            start = int(fitted["start_ms"] or 0)
            end = int(fitted["end_ms"] or 0)
            _require_in_range(video, start_ms=start, end_ms=end)
            span = end - start
            if span <= 0:
                raise Video2AgentError("E_ARGS", "区间为空：--end 必须晚于 --start", "把 --end 放到 --start 之后。")
            n = max(2, min(WINDOWS_MAX, int(windows)))
            if span / n > WINDOWS_COARSE_MS:
                warnings.append(_warn(
                    "WINDOWS_COARSE",
                    f"每窗约 {max(1, span // n // 60000)} 分钟，只取 1 帧，可能漏掉短事件。",
                    severity="info",
                    remedy="缩小 --start/--end 或减少 --windows；可疑处再用 --sheet 看细节。",
                ))
            # Midpoints, not edges: an edge frame often lands on a transition.
            times = [start + int((i + 0.5) * span / n) for i in range(n)]
            windows_meta = [{
                "index": i,
                "start_ms": start + int(i * span / n),
                "end_ms": start + int((i + 1) * span / n),
                "at_ms": times[i],
            } for i in range(n)]
            coverage = {"covered_ms": span, "total_ms": span, "missing_ms": 0, "window_count": n}
            dense_warnings: list[dict[str, Any]] = []
        elif windowed:
            _validate_change_budget(mode, max_frames)
            start = int(start_ms if start_ms is not None else (at_ms or 0))
            end = int(end_ms if end_ms is not None else start + 1000)
            fitted = _fit_request_times(video, start_ms=start, end_ms=end)
            start = int(fitted["start_ms"] or 0)
            end = int(fitted["end_ms"] or 0)
            _require_in_range(video, start_ms=start, end_ms=end)
            candidate_cap = min(DENSE_CANDIDATE_MAX, max(1, int(max_frames or 12)) * 2) if mode == "change" else None
            times, dense_warnings, effective_end = _dense_times(start, end, fps, max_frames, candidate_cap=candidate_cap)
            dense_meta = {"start_ms": start, "end_ms": effective_end, "fps": max(1, min(8, int(fps or 5))),
                          "mode": mode if mode in ("uniform", "change") else "uniform",
                          "requested_end_ms": end, "covered_end_ms": effective_end,
                          "truncated": effective_end < end, "requested_max": int(max_frames or 12)}
            if effective_end < end:
                dense_warnings.append(_warn(
                    "DENSE_WINDOW_TRUNCATED",
                    f"请求窗口到 {format_timecode(end)}，实际只覆盖到 {format_timecode(effective_end)}（5 秒上限）。",
                    severity="info",
                ))
        else:
            if at_ms is None:
                at_ms = 0
            fitted = _fit_request_times(video, at_ms=int(at_ms))
            at_ms = int(fitted["at_ms"] or 0)
            _require_in_range(video, at_ms=at_ms)
            times = [int(at_ms) + i * 1000 for i in range(max(1, min(count, 8)))]
            dense_warnings = []
        media_end = _media_end(video)
        out_dir = ensure_dir(cfg.derived_dir / video_id / "frames")
        warnings.extend(dense_warnings)
        images = []
        # 200ms of headroom: a seek at (end-1) fails on some containers, which made
        # `--at` near the end return E_FRAME instead of the last frame.
        last_ms = max(0, media_end - 200) if media_end else None
        seen: set[int] = set()
        batch: dict[int, Path] = {}
        planned: list[int] = []
        for t in times:
            tt = last_ms if last_ms is not None and t > last_ms else t
            if tt not in planned:
                planned.append(tt)
        if len(planned) > 1:
            batch = extract_frames_batch(
                video["source_path"], planned, out_dir,
                width=0 if crop else width, fmt=fmt,
                prefix=f"evidence_batch_{int(time.time() * 1000)}")
        for i, t in enumerate(times):
            # A window or `--count 8` can walk past the last addressable frame.
            # Clamp it and drop duplicates instead of returning the same frame twice.
            if last_ms is not None and t > last_ms:
                t = last_ms
            if t in seen:
                continue
            seen.add(t)
            out = batch.get(t)
            if out is not None:
                try:
                    final_path, crop_meta = _crop_image(out, crop, scale)
                    images.append({"t_ms": t, "path": str(final_path), "timecode": format_timecode(t),
                                   **({"crop": crop_meta} if crop_meta else {})})
                    continue
                except Exception:
                    pass
            out = out_dir / f"evidence_{t}_{i}.{fmt}"
            # A crop is a detail request: decode at source width, not the
            # thumbnail width used for the full-frame default.
            extract_width = 0 if crop else width
            try:
                extract_frame(video["source_path"], t, out, width=extract_width, fmt=fmt)
                final_path, crop_meta = _crop_image(out, crop, scale)
                images.append({"t_ms": t, "path": str(final_path), "timecode": format_timecode(t),
                               **({"crop": crop_meta} if crop_meta else {})})
            except Exception as first_error:
                # A seek within the last second can fail on some containers; clamp to
                # the last addressable moment and try once, rather than failing a
                # `--count 8` request at frame two (reproduced in review).
                if last_ms is not None and t != last_ms and last_ms not in seen:
                    try:
                        retry_out = out_dir / f"evidence_{last_ms}_{i}.{fmt}"
                        extract_frame(video["source_path"], last_ms, retry_out, width=extract_width, fmt=fmt)
                        retry_path, retry_meta = _crop_image(retry_out, crop, scale)
                        seen.add(last_ms)
                        images.append({"t_ms": last_ms, "path": str(retry_path),
                                       "timecode": format_timecode(last_ms),
                                       **({"crop": retry_meta} if retry_meta else {})})
                        continue
                    except Exception:
                        pass
                if images:
                    warnings.append(_warn(
                        "FRAME_SKIPPED",
                        f"{format_timecode(t)} 取帧失败，已跳过",
                        severity="warning",
                        remedy="检查源文件是否被截断；必要时 --force 重扫。",
                    ))
                    continue
                e = first_error
                return {
                    "ok": False,
                    "error": {
                        "code": "E_FRAME",
                        "message": f"{format_timecode(t)} 取帧失败：{e}",
                        "remedy": f"媒体实际时长 {format_timecode(int(video.get('duration_ms') or 0))}；"
                                  "把 --at 改到范围内，或确认源文件未被截断。",
                    },
                    "images": images,
                }
    if dense_meta.get("mode") == "change" and len(images) > 2:
        scores = _change_scores(images)
        for item, score in zip(images, scores):
            item["change_score"] = score
        keep_n = max(1, min(DENSE_FRAME_MAX, int(max_frames or 12)))
        # Keep the strongest change points plus the endpoints for context.
        ranked = sorted(range(len(images)), key=lambda i: scores[i], reverse=True)
        keep = set(ranked[:max(1, keep_n - 2)])
        keep.add(0)
        keep.add(len(images) - 1)
        selected = [item for i, item in enumerate(images) if i in keep][:keep_n]
        selected.sort(key=lambda item: int(item["t_ms"]))
        for item in images:
            if item not in selected:
                try:
                    Path(str(item.get("path") or "")).unlink(missing_ok=True)
                except OSError:
                    pass
        images = selected
        warnings.append(_warn("DENSE_CHANGE_POINTS", "dense 窗口按画面变化选了关键帧。", severity="info"))
    if dense_meta:
        # Coverage is what was actually returned, not the requested window. A
        # failed last frame must not be reported as covered.
        covered = int(images[-1]["t_ms"]) if images else int(dense_meta.get("start_ms") or 0)
        dense_meta["covered_end_ms"] = covered
        requested_end = dense_meta.get("requested_end_ms")
        if requested_end is not None and covered < int(requested_end):
            dense_meta["truncated"] = True
        dense_meta["frame_count"] = len(images)
        if covered < int(effective_end):
            # The first warning was emitted before frame extraction and named
            # the 5s-clamped window; replace it with the real last good frame.
            warnings[:] = [w for w in warnings if w.get("code") != "DENSE_WINDOW_TRUNCATED"]
            warnings.append(_warn(
                "DENSE_WINDOW_TRUNCATED",
                f"请求窗口到 {format_timecode(requested_end if requested_end is not None else effective_end)}，"
                f"实际最后成功帧 {format_timecode(covered)}。",
                severity="info",
            ))
    result = {"ok": True, "video_id": video_id, "images": images, "warnings": warnings}
    if dense_meta:
        result.update({"window": dense_meta, "mode": dense_meta.get("mode"),
                       "frame_count": len(images)})
    if windows is not None:
        tiles = [{"path": str(im["path"]), "label": str(im["timecode"]),
                  "t_ms": int(im["t_ms"])} for im in images]
        sheet_path, sheet_tiles = _montage(
            cfg, video_id, tiles,
            filename=f"coverage_sheet_{int(times[0])}_{int(times[-1])}_{len(tiles)}.jpg")
        result.update({"windows": windows_meta, **coverage, "frame_count": len(images)})
        if sheet_path:
            result.update({
                "sheet": sheet_path,
                "sheet_tiles": sheet_tiles,
                # The one image is the whole point: without it the caller would
                # receive N paths and read N images for a coarse scan.
                "images": [sheet_path],
                "frames": [{"t_ms": int(im["t_ms"]), "timecode": im["timecode"]} for im in images],
            })
        return result
    if sheet and len(images) >= 2:
        tiles = [{"path": str(im["path"]), "label": str(im["timecode"]),
                  "t_ms": int(im["t_ms"])} for im in images]
        if len(tiles) > 9:
            idx = sorted({round(i * (len(tiles) - 1) / 8) for i in range(9)})
            tiles = [tiles[i] for i in idx]
            warnings.append(_warn(
                "SHEET_SAMPLED",
                f"窗口内 {len(images)} 帧，拼图均匀取 {len(tiles)} 帧。",
                severity="info",
                remedy="要看全部帧就缩小窗口或对具体时刻用 --at。",
            ))
        sheet_path, sheet_tiles = _montage(
            cfg, video_id, tiles,
            filename=f"window_sheet_{int(times[0])}_{int(times[-1])}_{len(tiles)}.jpg")
        if sheet_path:
            result.update({
                "sheet": sheet_path,
                "sheet_tiles": sheet_tiles,
                "images": [sheet_path],
                "image_count": len(images),
                "frames": [{"t_ms": int(im["t_ms"]), "timecode": im["timecode"]} for im in images],
            })
    return result


def visual_map(cfg: Config, video_id: str, *, types: list[str] | None = None, min_score: float = 0.0,
               start_ms: int | None = None, end_ms: int | None = None, limit: int = 50) -> dict[str, Any]:
    limit = max(1, int(limit))
    with Database(cfg.db_path) as db:
        video = require_ready(db.get_video(video_id), video_id)
        total = int(db.counts(video_id).get("visual_segments") or 0)
        rows = db.get_visual_segments(video_id, start_ms, end_ms, types=types, min_score=min_score, limit=limit + 1)
    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]
    next_start_ms = int(rows[-1].get("end_ms") or 0) + 1 if truncated and rows else None
    return {
        "ok": True,
        "video_id": video_id,
        "title": (video or {}).get("title"),
        "segments": rows,
        "returned": len(rows),
        # `total` is the unfiltered visual-segment count; a type/score filter can
        # return fewer. The explicit truncation contract prevents a 50-row default
        # from looking complete on a one-hour video.
        "total": total,
        "truncated": truncated,
        "next_start_ms": next_start_ms,
        "next": {"start_ms": next_start_ms} if next_start_ms is not None else None,
    }


def list_videos(cfg: Config, limit: int = 50) -> dict[str, Any]:
    if int(limit) < 1:
        raise Video2AgentError(
            "E_ARGS",
            f"--limit 必须至少为 1（收到 {limit}）",
            "传入 1 或更大的值；要列出全部，请使用足够大的 limit 或分页读取。",
        )
    with Database(cfg.db_path) as db:
        total = db.video_count()
        rows = db.list_videos(limit=int(limit))
    return {"ok": True, "videos": rows, "total": total,
            "returned": len(rows), "truncated": len(rows) < total}
