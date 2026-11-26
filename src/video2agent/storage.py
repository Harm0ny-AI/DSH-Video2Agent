from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database
from .util import now_iso, pid_alive


def dir_size(path: str | Path) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    total = 0
    for child in p.rglob("*"):
        try:
            if not child.is_symlink() and child.is_file():
                total += child.stat().st_size
        except OSError:
            pass
    return total


CACHE_DEFAULTS = {
    "expire": True,
    "days": 7,
    "limit_enabled": True,
    "limit_gb": 20.0,
}


def cache_policy(cfg: Config, row_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read the settings-page cache policy; defaults are safe for a fresh home.

    `row_config` is the DSH plugin-row Config layer. The Host passes it to the
    background `gc --auto` so the effective policy is the one the settings page
    shows: ui-settings.json > row Config > built-in defaults. The file is still
    read here in one open; an unreadable or torn/corrupt file fails closed
    instead of applying a default that could free a cache the user kept.
    """
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
    # deletes a cache the user explicitly kept (the file said 关闭). The row
    # Config is ignored too: it is the layer below a working file, and a partial
    # write must never expire on a stale/unknown value.
    if corrupt:
        return {
            "expire": False, "days": CACHE_DEFAULTS["days"],
            "limit_enabled": False, "limit_gb": CACHE_DEFAULTS["limit_gb"],
            "corrupt": True,
        }
    # Whitelist the four UI keys: a malformed/hostile extra key in the argv
    # JSON must not become a policy field. File keys win, including an explicit
    # null (the existing clamp then falls back to the built-in value); missing
    # keys fall through to the row Config.
    defaults: dict[str, Any] = {}
    if isinstance(row_config, dict):
        for key in ("cacheExpire", "cacheDays", "cacheLimitEnabled", "cacheLimitGb"):
            if key in row_config:
                defaults[key] = row_config[key]
    policy = {**defaults, **raw}
    return {
        "expire": policy.get("cacheExpire", CACHE_DEFAULTS["expire"]) is not False,
        "days": clamp(policy.get("cacheDays"), CACHE_DEFAULTS["days"], 1, 365),
        "limit_enabled": policy.get("cacheLimitEnabled", CACHE_DEFAULTS["limit_enabled"]) is True,
        "limit_gb": clamp(policy.get("cacheLimitGb"), int(CACHE_DEFAULTS["limit_gb"]), 1, 20),
    }


def cached_usage(cfg: Config) -> int:
    return sum(dir_size(root) for root in _cache_roots(cfg))


def _cache_roots(cfg: Config) -> list[Path]:
    home = cfg.home.resolve()
    return [root for root in (cfg.media_dir, cfg.derived_dir)
            if root.resolve() == home / root.name]


def _video_cache_paths(cfg: Config, video: dict[str, Any]) -> list[Path]:
    video_id = str(video["id"])
    if video_id in {"", ".", ".."} or Path(video_id).name != video_id:
        return []
    local_source = video.get("source_path") if video.get("source_kind") == "local" else None
    paths = []
    for root in _cache_roots(cfg):
        target = root / video_id
        if target.resolve() != root.resolve() / video_id:
            continue
        if local_source and _within(Path(local_source), target):
            continue
        paths.append(target)
    return paths


def _active_media_ids(db: Database, video_id: str | None = None) -> set[str]:
    sql = "SELECT video_id,pid FROM jobs WHERE video_id IS NOT NULL AND kind='ingest' AND state IN ('queued','running')"
    params: list[str] = []
    if video_id is not None:
        sql += " AND video_id=?"
        params.append(video_id)
    active = set()
    for row in db.all(sql, params):
        try:
            pid = int(row["pid"] or 0)
        except (ValueError, TypeError):
            pid = 0
        # Foreground and newly started jobs may not have recorded a process ID.
        # Leave their cache alone. A known dead worker cannot keep pinning media.
        if not pid or pid_alive(pid):
            active.add(str(row["video_id"]))
    return active


def purge_video(cfg: Config, db: Database, video_id: str, *, reason: str = "expiry") -> dict[str, Any]:
    """Delete one cache entry: media, derived files, cover and all DB rows."""
    video = db.get_video(video_id) or {}
    # The plan filtered analyzing, but a direct call or a race must not delete a
    # video that started analyzing after the plan was built.
    if video.get("status") == "analyzing" or _active_media_ids(db, video_id):
        return {"video_id": video_id, "title": video.get("title"), "bytes": 0,
                "reason": reason, "error": "busy_analyzing"}
    paths = _video_cache_paths(cfg, video) if video else []
    cache_bytes = 0
    failed: list[str] = []
    for p in paths:
        size = dir_size(p)
        try:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            cache_bytes += size
        except OSError:
            cache_bytes += max(0, size - dir_size(p))
            failed.append(str(p))
    cover_bytes, cover_failed = _delete_covers(cfg, db, video, video_id)
    failed.extend(cover_failed)
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
        return {"video_id": video_id, "title": video.get("title"), "bytes": cache_bytes + cover_bytes,
                "cache_bytes": cache_bytes, "reason": reason, "error": "files_busy", "failed_paths": failed}
    db.delete_video(video_id)
    return {"video_id": video_id, "title": video.get("title"), "bytes": cache_bytes + cover_bytes,
            "cache_bytes": cache_bytes, "reason": reason}


def _media_released_warning() -> list[dict[str, Any]]:
    return [{"code": "MEDIA_RELEASED", "severity": "info",
             "message": "原片和抽帧已按缓存策略清理；转写和画面文字仍可搜索。",
             "remedy": "需要看画面时，重新提交视频链接；若原片版本一致，可继续用已有分析结果。"}]


def _frames_released_warning() -> list[dict[str, Any]]:
    return [{"code": "FRAMES_RELEASED", "severity": "info",
             "message": "抽帧缓存已按缓存策略清理；原片是你自己的文件，没有动；转写和画面文字仍可搜索。",
             "remedy": "需要证据帧时会从原片重新抽取。"}]


def release_media(cfg: Config, db: Database, video_id: str, *, reason: str = "expiry") -> dict[str, Any]:
    """Free media and frame files, keep the knowledge.

    The old automatic cache policy deleted the whole record (transcript, OCR,
    evidence and collection membership included), so letting the cache expire
    silently emptied the library. Expiry now only reclaims disk: the searchable
    rows stay, and anything that needs pixels says the media must be fetched
    again.
    """
    with db.conn:
        # A running rebuild registers its video ID before touching these cache
        # paths. Recheck while holding the writer slot so that claim and release
        # cannot cross between the status read and file deletion.
        db.conn.execute("BEGIN IMMEDIATE")
        video = db.get_video(video_id)
        if not video:
            return {"video_id": video_id, "bytes": 0, "exists": False}
        if video.get("status") == "analyzing" or _active_media_ids(db, video_id):
            return {"video_id": video_id, "title": video.get("title"), "bytes": 0,
                    "reason": reason, "error": "busy_analyzing"}
        cache_bytes = 0
        failed: list[str] = []
        for target in _video_cache_paths(cfg, video):
            if not target.is_dir():
                continue
            size = dir_size(target)
            try:
                shutil.rmtree(target)
                cache_bytes += size
            except OSError:
                cache_bytes += max(0, size - dir_size(target))
                failed.append(str(target))
        cover_bytes, cover_failed = _delete_covers(cfg, db, video, video_id)
        failed.extend(cover_failed)
        result = {"video_id": video_id, "title": video.get("title"), "bytes": cache_bytes + cover_bytes,
                  "cache_bytes": cache_bytes, "reason": reason}
        if failed:
            # Retry next gc instead of claiming the media is gone.
            return {**result, "error": "files_busy", "failed_paths": failed}
        source_path = str(video.get("source_path") or "")
        source_removed = (video.get("source_kind") == "url" and bool(source_path)
                          and _within(Path(source_path), cfg.media_dir) and not Path(source_path).exists())
        marker = now_iso() if source_removed else None
        warnings = [w for w in (video.get("warnings") or [])
                    if not isinstance(w, dict) or w.get("code") not in {"MEDIA_RELEASED", "FRAMES_RELEASED"}]
        warnings.extend(_media_released_warning() if source_removed else _frames_released_warning())
        db.set_media_released(video_id, marker, json.dumps(warnings, ensure_ascii=False))
        return {**result, "media": str(cfg.media_dir / video_id),
                "derived": str(cfg.derived_dir / video_id), "source_removed": source_removed}


def plan_cache_purge(cfg: Config, db: Database, *, older_than_days: int | None = None,
                     max_gb: float | None = None,
                     include_empty: bool = False) -> list[dict[str, Any]]:
    """Plan media releases for expiry and/or a capacity cap.

    The plan names videos whose media is old/large; the caller decides whether to
    release only the media (default) or delete the record too (--purge).
    """
    active = _active_media_ids(db)
    rows = [row for row in db.all(
        "SELECT id,title,created_at,updated_at,source_kind,source_path FROM videos "
        "WHERE status NOT IN ('new','queued','running','ingesting','analyzing') "
        "ORDER BY COALESCE(updated_at,created_at)"
    ) if row["id"] not in active]
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
        size = sum(dir_size(p) for p in _video_cache_paths(cfg, row))
        # A record whose media was already released has nothing left to free, so
        # the media plan skips it. A purge is different: it removes the knowledge
        # itself, which still exists after a release.
        if size <= 0 and not include_empty:
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
            size = sum(dir_size(p) for p in _video_cache_paths(cfg, row))
            if size <= 0:
                continue
            chosen.append({"video_id": vid, "title": row.get("title"), "bytes": size, "reason": "capacity"})
            seen.add(vid)
            current -= size
    return chosen


def _delete_covers(cfg: Config, db: Database, video: dict[str, Any],
                   video_id: str) -> tuple[int, list[str]]:
    """Delete the cover files this record owns; return (bytes, failed paths).

    Shared by the full purge and the media-only release: covers are cache, not
    knowledge, so both paths free them.
    """
    freed = 0
    failed: list[str] = []
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
            if (cover.is_symlink() or not cover.is_file()
                    or cover.resolve() != cfg.home.resolve() / cfg.covers_dir.name / cover.name):
                continue
            size = cover.stat().st_size
            cover.unlink()
            freed += size
    except OSError:
        failed.append(str(cfg.covers_dir / video_id))
    return freed, failed


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
    if video.get("status") == "analyzing" or _active_media_ids(db, video_id):
        return {"video_id": video_id, "title": video.get("title"), "bytes": 0,
                "reason": reason, "error": "busy_analyzing"}
    media = cfg.media_dir / video_id
    derived = cfg.derived_dir / video_id
    paths = _video_cache_paths(cfg, video)
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
    active = _active_media_ids(db)
    rows = [row for row in db.all(
        "SELECT id,title,created_at,source_kind,source_path FROM videos WHERE source_kind='url' "
        "AND status NOT IN ('new','queued','running','ingesting','analyzing') ORDER BY created_at"
    ) if row["id"] not in active]
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
            size = sum(dir_size(p) for p in _video_cache_paths(cfg, row))
            if size <= 0:
                continue
            plan.append({"video_id": vid, "title": row.get("title"), "bytes": size,
                         "media": str(cfg.media_dir / vid), "derived": str(cfg.derived_dir / vid),
                         "reason": "max_gb"})
            current -= size
    elif older_than_days is not None:
        for row in eligible:
            vid = row["id"]
            size = sum(dir_size(p) for p in _video_cache_paths(cfg, row))
            if size > 0:
                plan.append({"video_id": vid, "title": row.get("title"), "bytes": size,
                             "media": str(cfg.media_dir / vid), "derived": str(cfg.derived_dir / vid),
                             "reason": "retention"})
    return plan
