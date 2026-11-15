from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database


def dir_size(path: str | Path) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    total = 0
    for child in p.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            pass
    return total


CACHE_DEFAULTS = {
    "expire": True,
    "days": 7,
    "limit_enabled": False,
    "limit_gb": 20.0,
}


def cache_policy(cfg: Config) -> dict[str, Any]:
    """Read the settings-page cache policy; defaults are safe for a fresh home."""
    raw: dict[str, Any] = {}
    corrupt = False
    path = cfg.home / "ui-settings.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = None
    except (OSError, ValueError):
        # UnicodeDecodeError (UTF-16/BOM file) is a ValueError, not an OSError.
        corrupt = True
        text = None
    if text is not None:
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                raw = loaded
            else:
                corrupt = True
        except ValueError:
            corrupt = True

    def clamp(value: Any, fallback: int, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(round(float(value)))))
        except (TypeError, ValueError, OverflowError):
            # Infinity/NaN reach round() as OverflowError; treat as corrupt.
            return fallback

    # A corrupt settings file must not silently apply the 7-day default: that
    # deletes a cache the user explicitly kept (the file said 关闭).
    if corrupt:
        return {
            "expire": False, "days": CACHE_DEFAULTS["days"],
            "limit_enabled": False, "limit_gb": CACHE_DEFAULTS["limit_gb"],
            "corrupt": True,
        }
    return {
        "expire": raw.get("cacheExpire", CACHE_DEFAULTS["expire"]) is not False,
        "days": clamp(raw.get("cacheDays"), CACHE_DEFAULTS["days"], 1, 365),
        "limit_enabled": raw.get("cacheLimitEnabled", CACHE_DEFAULTS["limit_enabled"]) is True,
        "limit_gb": clamp(raw.get("cacheLimitGb"), int(CACHE_DEFAULTS["limit_gb"]), 1, 20),
    }


def cached_usage(cfg: Config) -> int:
    return dir_size(cfg.media_dir) + dir_size(cfg.derived_dir)


def purge_video(cfg: Config, db: Database, video_id: str, *, reason: str = "expiry") -> dict[str, Any]:
    """Delete one cache entry: media, derived files, cover and all DB rows."""
    video = db.get_video(video_id) or {}
    # The plan filtered analyzing, but a direct call or a race must not delete a
    # video that started analyzing after the plan was built.
    if video.get("status") == "analyzing":
        return {"video_id": video_id, "title": video.get("title"), "bytes": 0,
                "reason": reason, "error": "busy_analyzing"}
    media = cfg.media_dir / video_id
    derived = cfg.derived_dir / video_id
    paths = [p for p in (media, derived) if _within(p, cfg.home)]
    size = sum(dir_size(p) for p in paths)
    failed: list[str] = []
    for p in paths:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
        except OSError:
            failed.append(str(p))
    try:
        # Covers are named bili_<bvid>.jpg (sources/discover), not by the
        # internal vid_<hash>, so the old glob never matched anything.
        from .links import extract_bvid

        bvid = extract_bvid(str(video.get("source_uri") or "")) or ""
        names = [video_id + ".jpg"]
        # Only a Bilibili record owns bili_<bvid>.jpg: a local file whose path
        # happens to contain a BV id must not delete that video's cover.
        # The library stores the platform as the media probe reports it ("BiliBili"),
        # so an exact lowercase compare left every Bilibili cover behind.
        bili_video = str(video.get("platform") or "").strip().lower() == "bilibili"
        if bvid and bili_video:
            # Cover files are shared by every part of a multi-P video. A database
            # error here is not an OSError and used to escape with the files
            # already deleted and the row still "ready"; treat an unreadable
            # count as "shared" and leave the cover for a later gc.
            try:
                shared = db.one(
                    "SELECT COUNT(*) AS n FROM videos WHERE id<>? AND source_uri LIKE ?",
                    [video_id, "%" + bvid + "%"])
                shared_count = int((shared or {}).get("n") or 0)
            except Exception:
                shared_count = 1
            if not shared_count:
                names.append("bili_" + bvid + ".jpg")
        covers = [cfg.covers_dir / name for name in names]
        covers.extend(cfg.covers_dir.glob(video_id + "*"))
        for cover in covers:
            if not cover.is_file() or not _within(cover, cfg.home):
                continue
            size += cover.stat().st_size
            cover.unlink()
    except OSError:
        failed.append(str(cfg.covers_dir / video_id))
    if failed:
        # Keeping the record is safer than "media gone, row deleted": a retry
        # can still free the files once the handle is released. Mark it evicted
        # so overview/transcript do not promise data that is partially gone.
        try:
            db.update_video(video_id, status="evicted",
                            warnings_json=json.dumps(_evicted_warning(), ensure_ascii=False))
            # Media is partly gone, so the derived rows no longer describe
            # anything playable; leaving them made overview promise a transcript
            # that require_ready would refuse.
            db.clear_video_analysis(video_id)
        except Exception:
            pass
        return {"video_id": video_id, "title": video.get("title"), "bytes": size,
                "reason": reason, "error": "files_busy", "failed_paths": failed}
    db.delete_video(video_id)
    return {"video_id": video_id, "title": video.get("title"), "bytes": size, "reason": reason}


def plan_cache_purge(cfg: Config, db: Database, *, older_than_days: int | None = None,
                     max_gb: float | None = None) -> list[dict[str, Any]]:
    """Plan whole-entry cache deletions for expiry and/or a capacity cap."""
    rows = db.all(
        "SELECT id,title,created_at,updated_at FROM videos "
        "WHERE status NOT IN ('new','queued','running','ingesting','analyzing') "
        "ORDER BY COALESCE(updated_at,created_at)"
    )
    if not rows:
        return []
    expired: list[dict[str, Any]] = []
    if older_than_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, older_than_days))).isoformat(timespec="seconds")
        expired = [r for r in rows if str(r.get("updated_at") or r.get("created_at") or "") < cutoff]

    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in expired:
        vid = row["id"]
        size = dir_size(cfg.media_dir / vid) + dir_size(cfg.derived_dir / vid)
        if size <= 0:
            continue
        chosen.append({"video_id": vid, "title": row.get("title"), "bytes": size, "reason": "expiry"})
        seen.add(vid)

    if max_gb is not None:
        budget = int(max(0.0, min(20, float(max_gb))) * 1024 ** 3)
        current = cached_usage(cfg) - sum(int(item["bytes"]) for item in chosen)
        for row in rows:
            if current <= budget:
                break
            vid = row["id"]
            if vid in seen:
                continue
            size = dir_size(cfg.media_dir / vid) + dir_size(cfg.derived_dir / vid)
            if size <= 0:
                continue
            chosen.append({"video_id": vid, "title": row.get("title"), "bytes": size, "reason": "capacity"})
            seen.add(vid)
            current -= size
    return chosen


def _within(path: Path, root: Path) -> bool:
    try:
        rp = path.resolve()
        rr = root.resolve()
        return rp == rr or rr in rp.parents
    except OSError:
        return False


def _evicted_warning() -> list[dict[str, Any]]:
    return [{"code": "EVICTED", "severity": "info",
             "message": "Cached source/derived data was evicted by video2agent gc.",
             "remedy": "Re-ingest the URL to rebuild evidence."}]


def evict_video(cfg: Config, db: Database, video_id: str, *, dry_run: bool = False,
                reason: str = "retention") -> dict[str, Any]:
    video = db.get_video(video_id)
    if not video:
        return {"video_id": video_id, "bytes": 0, "exists": False}
    if video.get("status") == "analyzing":
        return {"video_id": video_id, "title": video.get("title"), "bytes": 0,
                "reason": reason, "error": "busy_analyzing"}
    media = cfg.media_dir / video_id
    derived = cfg.derived_dir / video_id
    paths = [p for p in (media, derived) if _within(p, cfg.home)]
    size = sum(dir_size(p) for p in paths)
    if not dry_run:
        failed: list[str] = []
        for p in paths:
            if p.exists():
                try:
                    shutil.rmtree(p)
                except OSError:
                    failed.append(str(p))
        if failed:
            # Partially deleted media cannot back the old ready rows: mark it so
            # overview/transcript do not promise data that is gone.
            try:
                db.update_video(video_id, status="evicted",
                                warnings_json=json.dumps(_evicted_warning(), ensure_ascii=False))
                db.clear_video_analysis(video_id)
            except Exception:
                pass
            return {"video_id": video_id, "title": video.get("title"), "bytes": size,
                    "media": str(media), "derived": str(derived), "reason": reason,
                    "error": "files_busy", "failed_paths": failed}
        db.clear_video_analysis(video_id)
        db.update_video(video_id, status="evicted",
                        warnings_json=json.dumps(_evicted_warning(), ensure_ascii=False))
    return {"video_id": video_id, "title": video.get("title"), "bytes": size,
            "media": str(media), "derived": str(derived), "reason": reason}


def plan_evictions(cfg: Config, db: Database, *, older_than_days: int | None = None,
                  max_gb: float | None = None) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT id,title,created_at FROM videos WHERE source_kind='url' "
        "AND status NOT IN ('new','queued','running','ingesting','analyzing') ORDER BY created_at"
    )
    if not rows:
        return []
    eligible = rows
    if older_than_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, older_than_days))).isoformat(timespec="seconds")
        eligible = [r for r in rows if (r.get("created_at") or "") < cutoff]
    plan: list[dict[str, Any]] = []
    if max_gb is not None:
        # Budget includes existing cache; evict oldest URL entries until under budget.
        budget = int(max_gb * 1024 ** 3)
        current = cached_usage(cfg)
        for row in eligible:
            if current <= budget:
                break
            vid = row["id"]
            size = dir_size(cfg.media_dir / vid) + dir_size(cfg.derived_dir / vid)
            if size <= 0:
                continue
            plan.append({"video_id": vid, "title": row.get("title"), "bytes": size,
                         "media": str(cfg.media_dir / vid), "derived": str(cfg.derived_dir / vid),
                         "reason": "max_gb"})
            current -= size
    elif older_than_days is not None:
        for row in eligible:
            vid = row["id"]
            size = dir_size(cfg.media_dir / vid) + dir_size(cfg.derived_dir / vid)
            if size > 0:
                plan.append({"video_id": vid, "title": row.get("title"), "bytes": size,
                             "media": str(cfg.media_dir / vid), "derived": str(cfg.derived_dir / vid),
                             "reason": "retention"})
    return plan
