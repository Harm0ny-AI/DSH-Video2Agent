from __future__ import annotations

from typing import Any

from .config import Config
from .db import Database
from .pipeline import search
from .util import Video2AgentError, format_timecode, not_ready_error


def _even_indices(total: int, target: int) -> list[int]:
    """Evenly spaced indices including both ends, without duplicates."""
    if total <= 0:
        return []
    target = max(1, min(total, target))
    if target == 1:
        return [0]
    return sorted({round(i * (total - 1) / (target - 1)) for i in range(target)})


def _sample_lines(lines: list[str], budget: int) -> tuple[list[str], str]:
    """Return full lines when they fit, otherwise an end-to-end sample."""
    total = sum(len(line) + 1 for line in lines)
    if total <= budget or not lines:
        return lines, "full"
    average = total / len(lines)
    target = max(2, min(len(lines), int(budget / max(20.0, average + 1))))
    previous = None
    while True:
        picked = [lines[i] for i in _even_indices(len(lines), target)]
        used = sum(len(line) + 1 for line in picked)
        if used <= budget:
            return picked, "sampled"
        if target <= 2 or target == previous:
            # Even two lines do not fit: keep the first line that fits.
            return [line for line in lines if len(line) + 1 <= budget][:1], "sampled"
        previous = target
        target = max(2, int(target * budget / max(1, used) * 0.95))
        if target == previous:
            target -= 1


def _compact_hit(hit: dict[str, Any]) -> dict[str, Any]:
    """Keep the evidence a comparison needs, not the full search row.

    The full search row adds evidence ids, confidence, visual labels and other
    fields the comparison prompt does not use. Ten videos times five aspects made
    the tool payload exceed the Host's 60k cap and truncate mid-JSON.
    """
    return {key: hit.get(key) for key in (
        "timecode", "start_ms", "end_ms", "snippet", "source",
        "matched_terms", "why", "citation",
    ) if hit.get(key) is not None}


def compare_videos(
    cfg: Config,
    video_ids: list[str],
    *,
    aspects: list[str] | None = None,
    per_video: int = 2,
    max_chars: int = 12000,
    max_total_chars: int = 40000,
) -> dict[str, Any]:
    """Pack comparable context for 2-10 videos.

    A comparison needs both sides of the story. Global top-k search can fill
    every slot from one long video, so each video gets its own transcript
    window and aspect-specific hits with an explicit hit/no-hit value.
    """
    if len(video_ids) < 2:
        raise Video2AgentError("E_COMPARE_COUNT", "compare 至少需要两个视频。",
                                "传入 2-10 个 video_id；单个视频直接用 transcript/digest。")
    if len(video_ids) > 10:
        raise Video2AgentError("E_COMPARE_COUNT", "compare 一次最多 10 个视频。",
                                "分成多组对比，或先用 digest 缩小范围。")
    aspects = [a.strip() for a in (aspects or []) if a and a.strip()][:12]
    per_video = max(1, min(5, int(per_video)))
    max_total_chars = max(200, min(120000, int(max_total_chars)))
    max_chars = max(200, min(30000, int(max_chars)))
    per_cap = min(max_chars, max(200, max_total_chars // max(1, len(video_ids))))
    videos: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    with Database(cfg.db_path) as db:
        missing = [vid for vid in video_ids if not db.get_video(vid)]
        if missing:
            raise Video2AgentError(
                "E_NOT_FOUND",
                "找不到视频：" + ", ".join(missing),
                "先运行 video2agent list 确认 video_id。",
            )
        remaining = max_total_chars
        for video_id in video_ids:
            row = db.get_video(video_id)
            if not row:
                continue
            # The same readiness rule as every other reader: a failed/analyzing
            # record used to return its stale transcript with ok:true here, then
            # refuse in the aspect search.
            if str(row.get("status") or "") != "ready":
                raise not_ready_error(video_id, row.get("status"), action="比较")
            budget = max(0, min(per_cap, remaining))
            segments = [s for s in db.get_segments(video_id, limit=5000)
                        if str(s.get("text") or "").strip()]
            all_lines = [f"[{format_timecode(int(s.get('start_ms') or 0))}] {str(s.get('text')).strip()}"
                         for s in segments]
            lines, transcript_mode = _sample_lines(all_lines, budget)
            chars = sum(len(line) + 1 for line in lines)
            remaining = max(0, remaining - chars)
            aspect_rows: list[dict[str, Any]] = []
            for aspect in aspects:
                result = search(cfg, aspect, video_id=video_id, limit=per_video)
                hits = [r for r in (result.get("results") or [])
                        if r.get("source") != "video_meta"]
                aspect_rows.append({
                    "aspect": aspect,
                    "coverage": "hit" if hits else "no_hit",
                    "hits": [_compact_hit(hit) for hit in hits],
                    "warnings": result.get("warnings") or [],
                })
            videos.append({
                "video_id": video_id,
                "title": row.get("title"),
                "duration_ms": int(row.get("duration_ms") or 0),
                "duration": format_timecode(int(row.get("duration_ms") or 0)),
                "transcript": lines,
                "transcript_chars": chars,
                "transcript_mode": transcript_mode,
                "transcript_truncated": transcript_mode == "sampled",
                "aspects": aspect_rows,
            })
    return {
        "ok": True,
        "videos": videos,
        "aspects": aspects,
        "warnings": warnings,
        "budget_per_video_chars": per_cap,
        "budget_total_chars": max_total_chars,
    }
