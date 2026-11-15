from __future__ import annotations

import math
import statistics
import time
from typing import Any

from .config import Config
from .pipeline import evidence, overview, search
from .util import json_dumps


def _tokens(value: Any) -> int:
    return max(1, len(json_dumps(value, indent=None)) // 4)


def run_bench(cfg: Config, video_id: str, queries: list[str], *, image_budget: int = 2) -> dict[str, Any]:
    t0 = time.perf_counter()
    ov = overview(cfg, video_id)
    overview_ms = round((time.perf_counter() - t0) * 1000, 1)
    rows = []
    latencies = []
    total_tokens = _tokens(ov)
    for q in queries:
        t = time.perf_counter()
        result = search(cfg, q, video_id=video_id, limit=5)
        ms = round((time.perf_counter() - t) * 1000, 1)
        latencies.append(ms)
        total_tokens += _tokens(result)
        first = (result.get("results") or [None])[0]
        ev = None
        if first:
            t = time.perf_counter()
            ev = evidence(cfg, video_id=video_id, at_ms=first["start_ms"], image_budget=image_budget)
            ev_ms = round((time.perf_counter() - t) * 1000, 1)
            total_tokens += _tokens(ev)
        else:
            ev_ms = None
        rows.append({"query": q, "search_ms": ms, "results": len(result.get("results") or []),
                     "evidence_ms": ev_ms, "evidence_images": len((ev or {}).get("images") or [])})
    ordered = sorted(latencies)
    p50 = statistics.median(ordered) if ordered else 0.0
    p95 = ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))] if ordered else 0.0
    return {
        "ok": True,
        "video_id": video_id,
        "title": ov.get("title"),
        "queries": rows,
        "latency_ms": {"overview": overview_ms, "search_p50": p50, "search_p95": p95},
        "estimated_tokens": total_tokens,
        "counts": ov.get("counts"),
        "metrics": ov.get("metrics"),
    }
