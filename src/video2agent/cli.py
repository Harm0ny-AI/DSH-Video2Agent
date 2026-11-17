from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import secrets
import shutil
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from pathlib import Path
from typing import Any

from . import __version__
from .config import doctor, load_config, save_config
from .links import extract_bvid, extract_ref
from .util import (
    Video2AgentError,
    format_duration,
    format_timecode,
    human_bytes,
    json_dumps,
    parse_time_ms,
    spawn_detached,
)

# Video work needs numpy/Pillow/opencv and the ASR/OCR stack. Importing it at module
# scope made `video2agent --version` and `video2agent doctor` die with ModuleNotFoundError
# before they could report anything — a diagnostic command that cannot diagnose a
# missing dependency. Those two commands must work with nothing installed.
_DEP_ERROR: Exception | None = None
try:
    from .compare import compare_videos
    from .db import Database
    from .export import export_html, export_json, export_knowledge, export_markdown
    from .pipeline import (
        _fit_request_times,
        _require_in_range,
        _stored_caption_mismatch,
        analyze,
        candidates,
        evidence,
        frames,
        list_videos,
        ocr_index,
        ocr_window,
        overview,
        require_ready,
        resolve_info,
        search,
        search_queries,
        visual_map,
    )
    from .storage import (
        cache_policy,
        cached_usage,
        evict_video,
        plan_cache_purge,
        plan_evictions,
        purge_video,
    )
except Exception as _exc:  # pragma: no cover - exercised by the missing-dep test
    _DEP_ERROR = _exc
    compare_videos = None  # type: ignore[assignment]
    Database = None  # type: ignore[assignment]
    export_html = export_json = export_knowledge = export_markdown = None  # type: ignore[assignment]
    _fit_request_times = None  # type: ignore[assignment]
    _require_in_range = None  # type: ignore[assignment]
    analyze = evidence = frames = list_videos = overview = None  # type: ignore[assignment]
    candidates = None  # type: ignore[assignment]
    ocr_index = None  # type: ignore[assignment]
    ocr_window = None  # type: ignore[assignment]
    resolve_info = search = search_queries = visual_map = None  # type: ignore[assignment]
    cache_policy = cached_usage = evict_video = plan_cache_purge = plan_evictions = purge_video = None  # type: ignore[assignment]


def _require_deps() -> None:
    """Refuse a video command with a real remedy when the install is incomplete."""
    if not _DEP_ERROR:
        return
    raise Video2AgentError(
        "E_MISSING_DEPS",
        f"依赖不完整：{type(_DEP_ERROR).__name__}: {_DEP_ERROR}",
        'pip install "video2agent" （或重新安装构建产物）后重试；--version 与 doctor 不需要这些依赖。',
    )


def _offered_path(cfg: Any) -> Path:
    return Path(cfg.home) / "discovery" / "offered.json"


class _OfferedLock:
    """Serialize read-modify-write of offered.json across CLI processes.

    The first version of the decision guard used a plain read/merge/write. Parallel
    discovers (the plugin can be called from a run_code loop) raced: each process
    read the old file, wrote its own ids, and the last writer dropped the others.
    A candidate that had been offered then looked unoffered to ingest. This is a
    security boundary, so contention fails closed after a short retry window rather
    than silently losing ids.
    """

    def __init__(self, cfg: Any) -> None:
        self.path = _offered_path(cfg).with_name("offered.lock")
        self.fd: int | None = None

    def __enter__(self) -> "_OfferedLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + 10.0
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except (FileExistsError, PermissionError):
                # Windows reports a sharing violation against a lock held by
                # another thread/process as PermissionError (EACCES), not
                # FileExistsError. It is contention, not a bad path.
                # A crashed process must not block discovery forever.
                try:
                    if time.time() - self.path.stat().st_mtime > 10:
                        self.path.unlink()
                except OSError:
                    pass
                if time.monotonic() > deadline:
                    raise Video2AgentError(
                        "E_OFFERED_LOCK",
                        "候选确认记录正在被另一个搜索写入",
                        "稍等一秒后重试 discover；不要并发启动多个 discover。",
                    )
                time.sleep(0.02)

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        try:
            self.path.unlink()
        except OSError:
            pass


def _write_offered(cfg: Any, merged: list[str]) -> None:
    target = _offered_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"offered.json.tmp-{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(json.dumps({"video_ids": merged, "updated_ms": int(time.time() * 1000)}),
                   encoding="utf-8")
    os.replace(tmp, target)


def remember_offered(cfg: Any, candidates: list[dict[str, Any]]) -> None:
    """Record the video ids a discover just offered (union, newest last).

    The point is to make "index the top hit without asking" impossible for every
    caller — the plugin tool, the CLI, a shell command. A discover does not need to
    know whether a UI is listening.
    """
    ids = [str(c.get("video_id") or "") for c in candidates if c.get("video_id")]
    if not ids:
        return
    with _OfferedLock(cfg):
        target = _offered_path(cfg)
        merged: list[str] = []
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and isinstance(existing.get("video_ids"), list):
                merged = [str(v) for v in existing["video_ids"] if v]
        except Exception:
            merged = []
        for vid in ids:
            if vid not in merged:
                merged.append(vid)
        merged = merged[-24:]
        _write_offered(cfg, merged)


def _source_identity(source: str) -> set[str]:
    """Every identity a source can be addressed by.

    A BV id and its `av` number are the same video, so comparing raw substrings
    (the first version did) let `av<id>` walk past a guard that stored `BV...` —
    reproduced in review. Local paths and unknown strings fall back to themselves.
    """
    text = str(source or "")
    # A local file is not a Bilibili reference even when its name contains "BV…":
    # treating it as one blocked ingesting a downloaded file (review false positive).
    looks_local = ("://" not in text) and (
        any(sep in text for sep in ("\\", "/"))
        or text.lower().endswith((".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3", ".wav", ".flv", ".ts"))
    )
    if looks_local:
        return {text.strip().lower()}
    ids: set[str] = set()
    bvid = extract_bvid(text)
    if bvid:
        ids.add(bvid.upper())
    ref = extract_ref(text)
    if ref:
        if ref.get("bvid"):
            ids.add(str(ref["bvid"]).upper())
        if ref.get("av_id"):
            ids.add(f"av{ref['av_id']}")
    if not ids:
        ids.add(text.strip().lower())
    return {v for v in ids if v}


def unconfirmed_offer(cfg: Any, source: str, *, ttl_s: int = 600) -> str | None:
    """The offered video id this source matches, when it was never confirmed."""
    target = _offered_path(cfg)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("video_ids"), list):
        return None
    try:
        updated_ms = int(data.get("updated_ms") or 0)
    except (TypeError, ValueError):
        return None
    now = time.time() * 1000
    # A clock-skewed future timestamp is not a reason to block forever.
    if not updated_ms or (now - updated_ms) > ttl_s * 1000 or updated_ms > now + 300_000:
        return None
    wanted = {v.upper() for v in _source_identity(source)}
    for vid in data["video_ids"]:
        vid = str(vid or "")
        if not vid:
            continue
        if vid.upper() in wanted:
            return vid
    return None


def clear_offers(cfg: Any, video_ids: list[str] | None = None) -> None:
    """Drop offers; with an id list only those are dropped."""
    with _OfferedLock(cfg):
        target = _offered_path(cfg)
        if not video_ids:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            return
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict) or not isinstance(data.get("video_ids"), list):
            return
        keep = [v for v in data["video_ids"] if str(v) not in set(video_ids)]
        try:
            data["video_ids"] = keep
            _write_offered(cfg, [str(v) for v in keep])
        except OSError:
            pass


def _confirm_path(cfg: Any) -> Path:
    return Path(cfg.home) / "discovery" / "confirm.json"


def issue_confirm_token(cfg: Any, video_ids: list[str], *, ttl_s: int = 120) -> str:
    """A short-lived, single-use token that means "the user picked these".

    `--confirm` as a boolean was not a guard: any caller, including a shell
    command, could just add the flag. The token is only written by the path that
    handles the user's own click (the plugin's confirm/retry route), it names the
    ids it authorizes, and it is consumed by the first accepted ingest.
    """
    token = secrets.token_hex(12)
    target = _confirm_path(cfg)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "token": token,
        "video_ids": [str(v) for v in video_ids],
        "expires_ms": int(time.time() * 1000) + ttl_s * 1000,
    }), encoding="utf-8")
    return token


def _consume_confirm_token(cfg: Any, token: str, source: str) -> bool:
    target = _confirm_path(cfg)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict) or not token or data.get("token") != token:
        return False
    if int(data.get("expires_ms") or 0) < int(time.time() * 1000):
        return False
    text = str(source or "")
    if not any(str(v) and str(v) in text for v in data.get("video_ids") or []):
        return False
    try:
        target.unlink(missing_ok=True)  # single use
    except OSError:
        pass
    return True


_TOKEN_LOG_DIR: Path | None = None
_TOKEN_LOG_COMMAND = ""


def _log_tool_result(data: Any) -> None:
    """Opt-in measurement of what a tool call puts in front of the model.

    Enabled only when `<home>/token-log.on` exists; it never changes stdout.
    The estimate is a proxy (compact JSON chars / 3.5 + 1100 per image), not a
    model tokenizer; use it to compare commands, not as a billing number.
    """
    try:
        if _TOKEN_LOG_DIR is None:
            return
        root = Path(_TOKEN_LOG_DIR)
        if not (root / "token-log.on").exists():
            return
        text = json_dumps(data, indent=None)
        images = len(data.get("images") or []) if isinstance(data, dict) else 0
        video_id = data.get("video_id") or data.get("id") if isinstance(data, dict) else None
        record = {
            "ts": int(time.time() * 1000),
            "cmd": _TOKEN_LOG_COMMAND,
            "video_id": video_id,
            "text_chars": len(text),
            "images": images,
            "est_tokens": round(len(text) / 3.5 + images * 1100),
        }
        with (root / "token-log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - logging must never break the command
        pass


_SEARCH_COMPACT_FIELDS = ("evidence_id", "video_id", "title", "timecode", "snippet", "modalities", "score")


def _compact_search(data: Any) -> Any:
    """Drop repeated envelope fields from search hits; keep what evidence needs."""
    if not isinstance(data, dict):
        return data
    if isinstance(data.get("queries"), list):
        out = dict(data)
        out["queries"] = [_compact_search(q) if isinstance(q, dict) else q for q in data["queries"]]
        out["compact"] = True
        return out
    rows = []
    for row in data.get("results") or []:
        if isinstance(row, dict):
            rows.append({k: row[k] for k in _SEARCH_COMPACT_FIELDS if k in row})
    out = dict(data)
    out["results"] = rows
    out["compact"] = True
    return out


def _emit(data: Any, as_json: bool, *, compact: bool = False) -> None:
    if as_json:
        _log_tool_result(data)
        print(json_dumps(data, indent=None if compact else 2))
        return
    # A failing command usually returns `{ok:false, error:{...}}`, but `doctor` returns
    # its own check list with `ok:false` and no `error` key. Treating that as an error
    # envelope printed "ERROR [E_UNKNOWN]" with an empty message and hid 15 checks —
    # exactly when the checks are what the user needs.
    if isinstance(data, dict) and data.get("ok") is False and isinstance(data.get("error"), dict):
        err = data.get("error") or {}
        print(f"ERROR [{err.get('code', 'E_UNKNOWN')}] {err.get('message', '')}")
        if err.get("remedy"):
            print(f"  fix: {err['remedy']}")
        return
    print(json_dumps(data, indent=2))


def _err(exc: Exception, as_json: bool) -> int:
    if isinstance(exc, Video2AgentError):
        payload = {"ok": False, "error": exc.as_dict()}
        if as_json:
            print(json_dumps(payload, indent=2))
        else:
            print(f"ERROR [{exc.code}] {exc.message}")
            if exc.remedy:
                print(f"  fix: {exc.remedy}")
        return 1
    if as_json:
        print(json_dumps({"ok": False, "error": {"code": "E_INTERNAL", "message": str(exc)}}, indent=2))
    else:
        print(f"ERROR [E_INTERNAL] {exc}")
    return 1


def _prune_logs(cfg: Any, days: int, dry_run: bool) -> tuple[list[str], int]:
    """Delete job logs older than `days` (0 = all). Only `job_*.log` is touched."""
    # `0 = all` is explicit: Windows time.time() is coarser than file mtime, so a
    # freshly written log could otherwise look "newer than now" and survive.
    cutoff = float("inf") if int(days) <= 0 else time.time() - int(days) * 86400
    removed: list[str] = []
    freed = 0
    for log_path in sorted(cfg.logs_dir.glob("job_*.log")):
        try:
            stat = log_path.stat()
            if stat.st_mtime >= cutoff:
                continue
            if not dry_run:
                log_path.unlink()
            # Count only after a successful unlink; a busy log used to be
            # reported as freed while it still existed.
            removed.append(str(log_path))
            freed += stat.st_size
        except OSError:
            pass
    return removed, freed


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _print_discover(data: dict[str, Any]) -> None:
    print(f"Bilibili · {data.get('query')} · {len(data.get('candidates') or [])} candidates")
    for i, c in enumerate(data.get("candidates") or [], 1):
        dur = format_duration(c.get("duration_ms")) if c.get("duration_ms") else "?"
        print(f"{i:>2}. {c.get('title')}  ({dur})  {c.get('uploader') or ''}")
        print(f"    {c.get('url')}")
    if data.get("cover_sheet"):
        print(f"covers: {data['cover_sheet']}")


def _print_overview(data: dict[str, Any]) -> None:
    print(f"{data.get('title')}  ·  {data.get('duration')}  ·  {data.get('language') or 'unknown'}")
    print(f"video_id: {data.get('video_id')}  status: {data.get('status')}")
    counts = data.get("counts") or {}
    print(f"segments={counts.get('segments', 0)}  frames={counts.get('frames', 0)}  ocr={counts.get('ocr_tracks', 0)}  visual={counts.get('visual_segments', 0)}")
    caps = data.get("capabilities") or {}
    print("capabilities: " + ", ".join(f"{k}={v}" for k, v in caps.items()))
    m = data.get("metrics") or {}
    if m:
        print("metrics: total={}s frames={} ({}s) ocr_frames={} ({}s) scenes={}".format(
            m.get("total_s", "?"), m.get("n_frames", "?"), m.get("frames", "?"),
            m.get("n_ocr_frames", "?"), m.get("ocr", "?"), m.get("n_scenes", "?")))
    if data.get("chapters"):
        print("chapters:")
        for c in data["chapters"][:12]:
            print(f"  {c['timecode']}  {c['title']}")
    for w in data.get("warnings") or []:
        print(f"warning [{w.get('code')}] {w.get('message')}")


def _print_search(data: dict[str, Any]) -> None:
    print(f"query: {data.get('query')}  results: {len(data.get('results') or [])}")
    for r in data.get("results") or []:
        print(f"- {r['timecode']}  [{r.get('score'):.2f}]  {r.get('snippet')}")
        print(f"  {r.get('citation')}  {r.get('modalities')}  {r.get('why')}")
    # A human reading "results: 0" must see the same partial/no-match reason the
    # JSON carries. Without this, an unread OCR index looks like "not in the video".
    vi = data.get("visual_index") or {}
    if vi.get("state") in ("partial", "on_demand", "failed", "unavailable") and vi.get("reason"):
        print(f"note: 画面文字索引 {vi.get('state')} — {vi.get('reason')}")
    for w in data.get("warnings") or []:
        print(f"warning [{w.get('code')}] {w.get('message')}")
        if w.get("remedy"):
            print(f"  fix: {w['remedy']}")


def _print_evidence(data: dict[str, Any]) -> None:
    print(f"{data.get('title')}  {data.get('citation') or '无引用'}")
    if data.get("empty"):
        print("没有可引用的转写、画面文字、视觉片段或图片。")
    for s in data.get("transcript") or []:
        print(f"[{format_timecode(s['start_ms'])}] {s['text']}")
    for o in data.get("ocr") or []:
        print(f"OCR [{format_timecode(o['start_ms'])}] {o['text']}")
    for v in data.get("visual") or []:
        print(f"VIS {v['label']} ({v['score']}) {format_timecode(v['start_ms'])}")
    for img in data.get("images") or []:
        print(f"IMAGE {img}")
    for w in data.get("warnings") or []:
        print(f"warning [{w.get('code')}] {w.get('message')}")


def _print_perceive(data: dict) -> None:
    print(f"{data.get('duration_ms', 0)} ms · {data.get('shot_count', 0)} shot(s)")
    for s in data.get("shots") or []:
        print(f"SHOT {format_timecode(s['start_ms'])}-{format_timecode(s['end_ms'])} "
              f"motion={s['motion']} peak={format_timecode(s['peak_ms'])}")
    for m in data.get("moments") or []:
        print(f"MOMENT {format_timecode(m['t_ms'])} {m['kind']} "
              f"score={m['score']} cell={m['cell']} settles={m['settles']}")
    loop = (data.get("rhythm") or {}).get("loop")
    if loop:
        print(f"LOOP {loop['period_ms']} ms sim={loop['sim']} cycles={loop['cycles']}")
    pts = (data.get("capture") or {}).get("pts")
    if pts:
        print(f"PTS median={pts['median_ms']}ms max={pts['max_ms']}ms gaps={pts['gaps']}")
    for w in data.get("warnings") or []:
        print(f"[{w.get('code')}] {w.get('message')}")


def _make_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", default=None, help="Video2Agent home (default: ~/.video2agent)")
    common.add_argument("--json", action="store_true", help="Output JSON")
    common.add_argument(
        "--cookies",
        default=None,
        metavar="FILE",
        help="Netscape cookie file. A logged-in Bilibili export lets Video2Agent use uploader/AI subtitles instead of local ASR.",
    )

    p = argparse.ArgumentParser(prog="video2agent", allow_abbrev=False,
                                description="Video perception and retrieval for AI agents.")
    p.add_argument("--version", action="version", version=f"video2agent {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def cmd(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], help=help_text)

    d = cmd("doctor", "Check ffmpeg, packages, disk, and permissions")
    d.add_argument("--save", action="store_true", help="Write default config")

    stp = cmd("setup", "Install the Video2Agent Skill into DSH")
    stp.add_argument("--project", action="store_true", help="Install into .dsh/skills instead of ~/.dsh/skills")
    stp.add_argument("--force", action="store_true")
    # Internal JSON-lines worker used by the DSH Host; hidden from normal help.
    sub.add_parser("__worker", help=argparse.SUPPRESS).set_defaults(command="__worker")

    # QR login: the friendly way to give Video2Agent a Bilibili session, which is what
    # unlocks CC/AI subtitles. Cookies never leave the local jar.
    ba = cmd("biliauth", "Bilibili QR login (scan with the mobile app)")
    bag = ba.add_mutually_exclusive_group(required=True)
    bag.add_argument("--start", action="store_true", help="Create a login QR")
    bag.add_argument("--poll", metavar="KEY", default=None, help="Poll a QR key; saves the login when confirmed")
    bag.add_argument("--status", action="store_true", help="Show whether a login is saved")
    bag.add_argument("--clear", action="store_true", help="Forget the saved login")

    d = cmd("discover", "Find candidate videos on Bilibili")
    d.add_argument("query")
    d.add_argument("--limit", type=int, default=8)
    d.add_argument("--no-covers", action="store_true")
    d.add_argument("--out", default=None, help="Save JSON result")
    # Narrow a broad keyword search to one uploader / one time window, which is
    # what "this creator's last three videos" actually needs.
    d.add_argument("--uploader", default=None, help="Uploader name (or numeric UID)")
    d.add_argument("--after", default=None, help="Published on/after: 2026-10-01 or 7d")
    d.add_argument("--before", default=None, help="Published on/before: 2026-10-26 or 30d")

    rv = cmd("resolve", "Read video title/cover/duration without downloading")
    rv.add_argument("url")

    oi = cmd("ocr-index", "Build the on-screen text index for one video")
    oi.add_argument("video_id")
    oi.add_argument("--dry-run", action="store_true", help="Only report how many frames and how long")
    oi.add_argument("--limit", type=int, default=None, help="Max frames to read (6-240)")

    pc = cmd("perceive", "Motion, cut and change map (VPM) for one video")
    pc.add_argument("video_id")
    pc.add_argument("--start", default=None, help="Window start (00:10:00 or milliseconds)")
    pc.add_argument("--end", default=None, help="Window end (exclusive)")
    pc.add_argument("--fps", type=int, default=None, help="Decode fps 1-30 (default by duration)")
    pc.add_argument("--max-frames", type=int, default=None, help="Decode cap (default 20000)")
    pc.add_argument("--brief", action="store_true",
                    help="Survey mode: cuts + top 4 moments, no per-shot rows (~300 tokens)")

    i = cmd("ingest", "Download/index a local video or URL")
    i.add_argument("source")
    i.add_argument("--profile", choices=["auto", "fast", "standard", "deep", "source_only"], default="auto")
    i.add_argument("--ocr-budget", type=int, default=None, help="Max OCR frames (6-240); overrides config")
    i.add_argument("--language", default=None)
    i.add_argument("--collection", default=None)
    i.add_argument("--force", action="store_true")
    i.add_argument("--reselect-ocr", action="store_true",
                   help="On --force, pick new OCR frames instead of reusing the saved anchors")
    i.add_argument("--detach", action="store_true", help="Run in a detached worker")
    # Explicit confirmation that this source was chosen by the user (the card sends
    # it). Without it, ingesting a video that a discover just offered is refused.
    i.add_argument("--confirm-token", default="",
                   help="Single-use token issued when the user picks a candidate on the card")
    # Kept only to answer old callers honestly: a bare flag is not a confirmation.
    i.add_argument("--confirm", action="store_true", help=argparse.SUPPRESS)
    i.add_argument("--wait", action="store_true", help="Wait for a detached job")

    j = cmd("jobs", "List or inspect ingest jobs")
    j.add_argument("--id", default=None)
    j.add_argument("--wait", action="store_true")
    # The caller (a plugin tool) has its own process timeout; let it ask for a
    # shorter wait instead of being killed mid-wait.
    j.add_argument("--wait-timeout", type=int, default=1800, help="Seconds to wait with --wait (default 1800).")

    o = cmd("overview", "Video metadata, chapters, capabilities, warnings")
    o.add_argument("video_id")

    dg = cmd("digest", "One-call extractive video index + contact sheet")
    dg.add_argument("video_id")
    dg.add_argument("--max-chars", type=int, default=6000, help="Transcript text budget (default 6000)")
    dg.add_argument("--max-ocr", type=int, default=80, help="OCR rows budget (default 80)")
    dg.add_argument("--compact", action="store_true",
                    help="Timestamped lines instead of one object per segment/OCR row (default)")
    dg.add_argument("--full", action="store_true",
                    help="Verbose per-segment/per-OCR objects (pre-compact format)")
    dg.add_argument("--frames", "--count", dest="frames", type=int, default=6,
                    help="Contact-sheet frames (1-6); --count is the tool-level name")

    t = cmd("transcript", "Timestamped transcript for a time range")
    t.add_argument("video_id")
    t.add_argument("--start", default=None, help="Start: HH:MM:SS.mmm or seconds")
    t.add_argument("--end", default=None, help="End: HH:MM:SS.mmm or seconds")
    t.add_argument("--max-chars", type=int, default=12000,
                   help="Budget for the emitted text. Compact output counts the timecodes and line breaks too.")
    t.add_argument("--compact", action="store_true",
                   help="One 'mm:ss text' line per segment instead of a JSON object per segment (default for --json).")
    t.add_argument("--full", action="store_true",
                   help="Verbose per-segment objects even with --json (pre-compact format).")

    cmp = cmd("compare", "Pack comparable transcript + aspect hits for 2-10 videos")
    cmp.add_argument("video_ids", nargs="+")
    cmp.add_argument("--aspects", default="", help="Comma-separated comparison dimensions")
    cmp.add_argument("--per-video", type=int, default=2, help="Search hits per video/aspect (1-5)")
    cmp.add_argument("--max-chars", type=int, default=12000, help="Transcript characters per video")
    cmp.add_argument("--max-total-chars", type=int, default=40000, help="Total transcript budget across videos")
    cmp.add_argument("--compact", action="store_true", help="Compact JSON output for tool calls")

    s = cmd("search", "Search inside indexed videos")
    s.add_argument("query")
    s.add_argument("--video", default=None)
    s.add_argument("--collection", default=None)
    s.add_argument("--start", default=None)
    s.add_argument("--end", default=None)
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--modalities", default=None, help="transcript,ocr")
    s.add_argument("--compact", action="store_true",
                   help="Trim repeated hit fields (keeps evidence_id/timecode/snippet)")
    s.add_argument("--queries", nargs="+", default=None, help="Additional query variants (model-generated synonyms)")

    e = cmd("evidence", "Build an evidence bundle with text and frames")
    e.add_argument("video_id")
    e.add_argument("--at", default=None, help="Moment or comma/JSON list of moments: HH:MM:SS.mmm or seconds; batch returns all moments in one call")
    e.add_argument("--start", default=None)
    e.add_argument("--end", default=None)
    e.add_argument("--evidence-id", default=None)
    e.add_argument("--images", type=int, default=2, help="Evidence images per moment (default 2; 0 for text-only)")
    e.add_argument("--max-images", type=int, default=6, help="Total image budget for a multi-moment --at call (1-6, default 6)")
    e.add_argument("--detail", choices=["overview", "read", "zoom"], default="read")
    e.add_argument("--ocr-tiles", action="store_true",
                   help="Read the frame as 3x3 overlapping tiles; better for small text")

    ow = cmd("ocr-window", "OCR every frame of a short window (text that changes over time)")
    ow.add_argument("video_id")
    ow.add_argument("--start", required=True, help="Window start: HH:MM:SS.mmm or seconds")
    ow.add_argument("--end", required=True, help="Window end: HH:MM:SS.mmm or seconds")
    ow.add_argument("--fps", type=int, default=2, help="Samples per second (1-4)")
    ow.add_argument("--max", type=int, default=15, help="Frame cap (1-15); a longer window is sampled and flagged")
    ow.add_argument("--tiles", action="store_true", help="Read each frame as 3x3 tiles (slow, ~5s/frame); use only when the default pass misses small text")

    f = cmd("frames", "Extract exact frame(s)")
    f.add_argument("video_id")
    f.add_argument("--at", default="0", help="Moment: HH:MM:SS.mmm or a bare number in SECONDS (use the ms suffix for milliseconds)")
    f.add_argument("--start", default=None, help="Start of a bounded dense window (the window is capped at 5s)")
    f.add_argument("--end", default=None, help="End of a bounded dense window (clamped to 5s after --start)")
    f.add_argument("--fps", type=int, default=5, help="Dense window fps (1-8)")
    f.add_argument("--max", type=int, default=12, help="Dense window frame cap (1-15); --count >1 is an alias")
    f.add_argument("--mode", choices=["uniform", "change"], default="uniform", help="Dense sampling mode")
    f.add_argument("--count", type=int, default=1, help="Frames from a timestamp; for a start/end window, values >1 become the frame cap")
    f.add_argument("--sheet", action="store_true",
                   help="Tile the returned frames into one labelled image (max 9, adaptive grid)")
    f.add_argument("--windows", type=int, default=None,
                   help="With --start/--end: split the range into N windows and return one coverage montage (2-9)")
    f.add_argument("--width", type=int, default=1280)
    f.add_argument("--format", choices=["jpg", "png"], default="jpg")
    f.add_argument("--crop", default=None, help="Normalized x,y,w,h (0-1) for a detail crop")
    f.add_argument("--scale", type=float, default=1.0, help="Crop upscale factor (1-3)")
    f.add_argument("--out", default=None)

    m = cmd("map", "Visual structure map")
    m.add_argument("video_id")
    m.add_argument("--types", default=None, help="Comma-separated labels")
    m.add_argument("--min-score", type=float, default=0.0)
    m.add_argument("--limit", type=int, default=50)
    m.add_argument("--start", default=None, help="Start of the range (e.g. 00:30:00)")
    m.add_argument("--end", default=None, help="End of the range (e.g. 00:35:00)")

    cd = cmd("candidates", "Candidate shots for a question (timecodes + keyframes)")
    cd.add_argument("video_id")
    cd.add_argument("--query", default=None, help="Question or keywords; without it, shots are spread in time")
    cd.add_argument("--limit", type=int, default=8, help="Candidate shots to return (1-30)")
    cd.add_argument("--images", action="store_true",
                    help="Also render one adaptive montage (up to 9 keyframes) as a single image")

    ex = cmd("export", "Export Markdown, HTML, JSON, or knowledge pack")
    ex.add_argument("video_id")
    ex.add_argument("--format", choices=["md", "html", "json", "knowledge"], default="md")
    ex.add_argument("--out", default=None)
    ex.add_argument("--include-paths", action="store_true",
                    help="Keep absolute local paths in the export (default: redact to file names)")

    b = cmd("bench", "Measure retrieval latency and token estimate")
    b.add_argument("video_id")
    b.add_argument("--queries", default="注意力,表格")
    b.add_argument("--images", type=int, default=2)

    ls = cmd("list", "List videos")
    ls.add_argument("--limit", type=int, default=50)

    cmd("stats", "Show DB and disk usage")
    gc = cmd("gc", "Clean temp files, old covers, and optionally cached URL media")
    gc.add_argument("--dry-run", action="store_true")
    gc.add_argument("--auto", action="store_true", help="Apply the cache policy from settings (expiry and/or capacity cap)")
    gc.add_argument("--sources", action="store_true", help="Evict cached URL sources/derived data older than the retention window")
    gc.add_argument("--older-than-days", type=int, default=None)
    gc.add_argument("--max-gb", type=float, default=None, help="Evict oldest cached URL videos until media+derived is under this size")
    gc.add_argument("--keep-logs-days", type=int, default=None,
                    help="Delete job logs older than N days (default 7; 0 = all)")

    # Bilibili account/library tools. Reads are safe; every write action requires
    # --confirm and is intentionally a separate call from the plan/preview.
    ac = cmd("account", "Read and manage the logged-in Bilibili library")
    ac.add_argument(
        "action",
        choices=[
            "status", "folders", "favorites", "history",
            "create-folder", "rename-folder", "delete-folder",
            "add", "remove", "analyze", "classify-plan", "classify-apply",
        ],
    )
    ac.add_argument("--folder", type=int, default=None, help="Favorites folder id (media_id)")
    ac.add_argument("--videos", nargs="+", default=[], help="BV ids, av ids, aids, or Bilibili URLs")
    ac.add_argument("--title", default=None, help="New folder title")
    ac.add_argument("--expected-title", default=None, help="For delete-folder: refuse unless id has this title")
    ac.add_argument("--intro", default="", help="New folder intro")
    ac.add_argument("--public", action="store_true", help="Create/rename a public folder (default private)")
    ac.add_argument("--days", type=int, default=30, help="History window in days")
    ac.add_argument("--limit", type=int, default=50, help="Maximum favorites/history rows (default 50)")
    ac.add_argument("--source", choices=["favorites", "history"], default="favorites")
    ac.add_argument("--plan", default=None, help="JSON plan file for classify-apply")
    ac.add_argument("--plan-json", default=None, help="JSON plan inline for classify-apply")
    ac.add_argument("--confirm", action="store_true", help="Actually perform a write action")

    # Cloud provider settings. The key is read from stdin or an environment
    # variable, never from argv, so it cannot leak into process listings/logs.
    cl = cmd("cloud", "Configure an OpenAI-compatible cloud ASR/OCR provider")
    cl.add_argument("action", choices=["status", "config", "save", "test", "clear", "ocr-on", "ocr-off", "asr-on", "asr-off"])

    lm = cmd("models", "Inspect or download the local ASR model")
    lm.add_argument("action", choices=["status", "select", "download", "uninstall", "select-ocr"])
    lm.add_argument("--model", default=None, help="Preset name, HuggingFace model ID, or local CTranslate2 path")
    lm.add_argument("--ocr-config", default=None, help="Local RapidOCR YAML config; empty selects the built-in model")

    w = sub.add_parser("worker", parents=[common], help=argparse.SUPPRESS)
    w.add_argument("job_id")
    return p


def _run_ingest(args: argparse.Namespace, cfg: Any) -> dict[str, Any]:
    options = {
        "profile": getattr(args, "profile", "standard"),
        "ocr_budget": getattr(args, "ocr_budget", None),
        "language": getattr(args, "language", None),
        "collection": getattr(args, "collection", None),
        "force": bool(getattr(args, "force", False)),
        "reselect_ocr": bool(getattr(args, "reselect_ocr", False)),
    }
    with Database(cfg.db_path) as db:
        job = db.create_job("ingest", args.source, options=options)
        db.update_job(job, state="running", stage="queued", started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if args.detach:
        env = os.environ.copy()
        env["VIDEO2AGENT_HOME"] = str(cfg.home)
        log = cfg.logs_dir / f"{job}.log"
        pid = spawn_detached(
            [sys.executable, "-m", "video2agent", "worker", job, "--home", str(cfg.home)]
            + (["--cookies", str(cfg.get("cookies_file"))] if cfg.get("cookies_file") else []),
            log_path=log,
            env=env,
            cwd=Path.cwd(),
        )
        with Database(cfg.db_path) as db:
            db.update_job(job, pid=pid)
        return {"ok": True, "job_id": job, "state": "running", "log": str(log), "pid": pid}
    # A foreground ingest must respect the same one-at-a-time rule as a detached
    # worker; otherwise `video2agent ingest` in a terminal walks straight past the queue
    # and thrashes with a background job.
    with _ingest_slot(cfg, job):
        return _run_job(job, cfg)


def _run_job(job_id: str, cfg: Any) -> dict[str, Any]:
    with Database(cfg.db_path) as db:
        job = db.get_job(job_id)
        if not job:
            raise Video2AgentError("E_JOB", f"Job not found: {job_id}")
        source = job["source"]
        try:
            options = json.loads(job.get("options_json") or "{}")
        except Exception:
            options = {}

    if options.get("ocr_budget") is not None:
        try:
            cfg.set("ocr_max_frames", max(6, min(240, int(options["ocr_budget"]))))
        except (TypeError, ValueError):
            pass

    def progress(stage: str, pct: float, msg: str) -> None:
        _raise_if_canceled(cfg, job_id)
        with Database(cfg.db_path) as db:
            db.update_job(job_id, state="running", stage=stage, progress=pct, message=msg)

    try:
        result = analyze(
            cfg, source,
            profile=options.get("profile", "standard"),
            language=options.get("language"),
            collection=options.get("collection"),
            force=bool(options.get("force", False)),
            job_id=job_id,
            progress=progress,
            reselect_ocr=bool(options.get("reselect_ocr", False)),
        )
        _raise_if_canceled(cfg, job_id)
        video_id = result.get("video_id")
        with Database(cfg.db_path) as db:
            # Dedupe paths used to return an existing overview without writing its
            # video_id onto the job. The live card then had no id and the model
            # could not tell which video was reused.
            db.update_job(job_id, state="ready", stage="done", progress=1.0, message="完成",
                          video_id=video_id,
                          finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return {"ok": True, "job_id": job_id, "video_id": video_id, "overview": result}
    except Exception as e:
        code = getattr(e, "code", "E_INTERNAL")
        with Database(cfg.db_path) as db:
            remedy = getattr(e, "remedy", None)
            if code == "E_CANCELED":
                db.update_job(job_id, state="canceled", stage="canceled", progress=0.0,
                              error_code=code, error_message=str(e), message="已取消",
                              finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            else:
                db.update_job(job_id, state="failed", stage="failed", progress=0.0, error_code=code,
                              error_message=str(e), message=code + ': ' + str(e), remedy=remedy,
                              finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            # A failed analysis must not leave the video stuck in "analyzing":
            # overview/list/require_ready would treat it as still working and
            # gc could see it as idle. The job row carries the video id once
            # analyze() reached its upsert, so read it back instead of relying
            # on the success-only local variable.
            try:
                current = db.get_job(job_id) or {}
                stuck_vid = current.get("video_id")
                if stuck_vid:
                    live = db.get_video(stuck_vid) or {}
                    # Never downgrade a video that already finished: a cancel that
                    # arrived after ready (or a stale lock) must not make it
                    # unreadable via require_ready.
                    if live.get("status") in ("analyzing", "new", "queued", "running", "ingesting"):
                        db.update_video(stuck_vid, status="canceled" if code == "E_CANCELED" else "failed")
            except Exception:
                pass
        raise


def _cookie_overrides(args: argparse.Namespace) -> dict[str, Any] | None:
    """Turn --cookies into a per-run config override (never rewrites config)."""
    raw = getattr(args, "cookies", None)
    if not raw:
        return None
    path = Path(str(raw)).expanduser()
    if not path.is_file():
        raise Video2AgentError(
            "E_COOKIES",
            f"Cookie file not found: {path}",
            "Export Bilibili cookies in Netscape format, then pass its path to --cookies.",
        )
    return {"cookies_file": str(path)}


def _cancel_marker(cfg: Any, job_id: str) -> Path:
    return cfg.home / "jobs" / f"{job_id}.cancel"


def _raise_if_canceled(cfg: Any, job_id: str) -> None:
    if _cancel_marker(cfg, job_id).exists():
        raise Video2AgentError("E_CANCELED", "任务已取消", "重新开始即可；已生成的部分不会标记为完成。")


def _mark_canceled(cfg: Any, job_id: str) -> None:
    try:
        with Database(cfg.db_path) as db:
            job = db.get_job(job_id)
            if not job or job.get("state") in ("ready", "failed", "canceled"):
                return
            db.update_job(
                job_id, state="canceled", stage="canceled", progress=0.0,
                message="已取消", finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )
            # A canceled job must not leave its video stuck in analyzing (gc
            # skips analyzing, so it would never be reclaimed).
            if job.get("video_id"):
                live = db.get_video(job["video_id"]) or {}
                if live.get("status") in ("analyzing", "new", "queued", "running", "ingesting"):
                    db.update_video(job["video_id"], status="canceled")
    except Exception:  # noqa: BLE001 - cancellation must not hide the original error
        pass


def _fail_orphaned_job(cfg: Any, lock: Path) -> None:
    """A stale lock means its worker died; close the job it left behind."""
    try:
        parts = lock.read_text(encoding="ascii", errors="replace").split()
    except OSError:
        return
    if len(parts) < 2:
        return
    job_id = parts[1]
    if not job_id.startswith("job_"):
        return
    try:
        with Database(cfg.db_path) as db:
            job = db.get_job(job_id)
            if not job or job.get("state") in ("ready", "failed", "canceled"):
                return
            db.update_job(job_id, state="failed", stage="failed", progress=0.0,
                          error_code="E_WORKER_LOST",
                          error_message="后台进程中断，任务未完成",
                          message="E_WORKER_LOST: 后台进程中断，任务未完成",
                          remedy="重新 ingest 即可（已入库的部分会复用）。",
                          finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            if job.get("video_id"):
                live = db.get_video(job["video_id"]) or {}
                if live.get("status") in ("analyzing", "new", "queued", "running", "ingesting"):
                    db.update_video(job["video_id"], status="failed")
    except Exception:  # noqa: BLE001 - never let cleanup block the queue
        return


@contextlib.contextmanager
def _ingest_slot(cfg: Any, job_id: str, *, timeout_s: int = 1800, stale_s: int = 180):
    """One ingest at a time, with the queue made visible.

    Measured on the same video: alone 74s, three at once 320s (4.3x) — CPU-bound
    work (scenes, OCR, ASR) just thrashes. A lock file serialises them; the job
    that waits reports `排队中` instead of looking stuck at 0%. The lock carries a
    heartbeat so a killed worker cannot wedge the queue forever.
    """
    lock = cfg.home / "jobs" / ".ingest.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    announced = False
    while True:
        if _cancel_marker(cfg, job_id).exists():
            _mark_canceled(cfg, job_id)
            raise Video2AgentError("E_CANCELED", "任务已取消", "重新开始即可。")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except (FileExistsError, PermissionError):
            # Windows can report a held O_EXCL lock as EACCES (PermissionError),
            # not FileExistsError. Treat it as queue contention, not a crash.
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                age = 0.0
            if age > stale_s:
                # The previous worker died without cleaning up. Mark its job failed
                # so its card does not poll a `running` row forever, then take over.
                _fail_orphaned_job(cfg, lock)
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            if not announced:
                announced = True
                with Database(cfg.db_path) as db:
                    db.update_job(job_id, state="queued", stage="queued",
                                  message="排队中：已有一个入库任务在运行")
            if time.monotonic() > deadline:
                # Leave a terminal state behind: a queued row would otherwise be
                # polled forever by the card.
                with Database(cfg.db_path) as db:
                    db.update_job(job_id, state="failed", stage="failed", progress=0.0,
                                  error_code="E_BUSY", error_message="入库队列等待超时",
                                  message="E_BUSY: 入库队列等待超时",
                                  remedy="等当前入库结束，或把并发降到 1 后重试。",
                                  finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                raise Video2AgentError("E_BUSY", "入库队列等待超时", "等当前入库结束，或把并发降到 1 后重试。")
            time.sleep(2.0)
            continue
        os.write(fd, f"{os.getpid()} {job_id}".encode("ascii"))
        os.close(fd)
        if _cancel_marker(cfg, job_id).exists():
            _mark_canceled(cfg, job_id)
            raise Video2AgentError("E_CANCELED", "任务已取消", "重新开始即可。")
        break
    stop = threading.Event()

    def _heartbeat() -> None:
        while not stop.wait(20):
            try:
                os.utime(lock)
            except OSError:
                return

    beat = threading.Thread(target=_heartbeat, name="vp-ingest-lock", daemon=True)
    beat.start()
    try:
        yield
    finally:
        stop.set()
        beat.join(timeout=0.2)
        try:
            lock.unlink()
        except OSError:
            pass


def _worker(args: argparse.Namespace) -> int:
    cfg = load_config(args.home, _cookie_overrides(args))
    try:
        with _ingest_slot(cfg, args.job_id):
            result = _run_job(args.job_id, cfg)
        print(json_dumps(result, indent=2))
        return 0
    except Exception as e:
        # A worker that dies before the pipeline writes a terminal state would
        # leave the card polling "running" forever. Mark the job failed here.
        try:
            with Database(cfg.db_path) as db:
                job = db.get_job(args.job_id)
                if job and job.get("state") in ("queued", "running"):
                    code = getattr(e, "code", "E_WORKER")
                    message = str(e) or "worker failed"
                    if code == "E_CANCELED":
                        db.update_job(args.job_id, state="canceled", stage="canceled", progress=0.0,
                                      error_code=code, error_message=message[:500], message="已取消",
                                      finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                    else:
                        db.update_job(
                            args.job_id, state="failed", stage="failed",
                            error_code=code, error_message=message[:500],
                            message=f"{code}: {message}"[:500],
                            finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        )
        except Exception:
            pass
        return _err(e, True)


def _parse_at_list(raw: str) -> list[int]:
    """Parse one timestamp or a comma/JSON list into millisecond moments."""
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        values = json.loads(text) if text.startswith("[") else [part.strip() for part in text.split(",") if part.strip()]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise Video2AgentError("E_BAD_TIME", f"无法解析 --at 时间列表：{text}", "用 00:00:06,00:00:10 或 [\"00:00:06\",\"00:00:10\"]。") from exc
    moments = []
    for value in values:
        try:
            if isinstance(value, (int, float)):
                moments.append(int(round(float(value) * 1000)) if float(value) < 100000 else int(value))
            else:
                moments.append(parse_time_ms(str(value)))
        except Exception as exc:
            raise Video2AgentError("E_BAD_TIME", f"无法解析 --at 时间：{value}", "用 HH:MM:SS.mmm 或秒数。") from exc
    return moments


def _merge_evidence_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine per-moment evidence bundles without exposing frame paths."""
    first = dict(results[0])
    moments = []
    images = []
    image_frames = []
    frames = []
    ocr = []
    transcript = []
    warnings = []
    evidence_ids = []
    seen_images = set()
    seen_warnings = set()
    for result in results:
        range_ = result.get("range") or {}
        at_ms = result.get("requested_ms")
        if at_ms is None:
            at_ms = range_.get("start_ms")
        moment_frames = [
            {"t_ms": f.get("t_ms"), "timecode": f.get("timecode") or f.get("t_ms")}
            for f in (result.get("frames") or [])
            if isinstance(f, dict)
        ]
        by_path = {
            str(f.get("path")): f for f in (result.get("frames") or [])
            if isinstance(f, dict) and f.get("path")
        }
        evidence_ids.append(result.get("evidence_id"))
        moments.append({
            "at_ms": at_ms,
            "range": range_,
            "evidence_id": result.get("evidence_id"),
            "citation": result.get("citation"),
            "frame_citation": result.get("frame_citation"),
            "ocr_citation": result.get("ocr_citation"),
            "transcript_citation": result.get("transcript_citation"),
            "snapped": bool(result.get("snapped")),
            "frame_ms": result.get("frame_ms"),
            "frame_timecode": result.get("frame_timecode"),
            "ocr_state": result.get("ocr_state"),
            "visual": result.get("visual") or [],
            "image_count": len(result.get("images") or []),
            "frames": moment_frames,
            "ocr": result.get("ocr") or [],
            "transcript": result.get("transcript") or [],
            "warnings": result.get("warnings") or [],
        })
        result_image_times = result.get("image_frame_ms") or []
        for index, image in enumerate(result.get("images") or []):
            key = image.get("path") if isinstance(image, dict) else str(image)
            if key in seen_images:
                continue
            seen_images.add(key)
            images.append(image)
            frame = by_path.get(str(key)) or {}
            t_ms = frame.get("t_ms")
            if t_ms is None and index < len(result_image_times):
                t_ms = result_image_times[index]
            image_frames.append(t_ms)
            frames.append({"t_ms": t_ms, "timecode": format_timecode(t_ms) if t_ms is not None else None})
        ocr.extend(result.get("ocr") or [])
        transcript.extend(result.get("transcript") or [])
        for warning in result.get("warnings") or []:
            marker = (warning.get("code"), warning.get("message")) if isinstance(warning, dict) else str(warning)
            if marker in seen_warnings:
                continue
            seen_warnings.add(marker)
            warnings.append(warning)
    # The batch is empty only when every moment is empty; copying the first
    # moment's flag made a batch look evidence-free when only 00:00:06 was.
    first["empty"] = all(bool(m.get("empty")) for m in results)
    first["moments"] = moments
    first["multi_moment"] = True
    first["evidence_ids"] = evidence_ids
    first["ranges"] = [m["range"] for m in moments]
    first["images"] = images
    first["image_frame_ms"] = image_frames
    first["frames"] = frames
    first["image_count"] = len(images)
    first["ocr"] = ocr
    first["transcript"] = transcript
    first["warnings"] = warnings
    first["range"] = {"start_ms": None, "end_ms": None, "timecode": None, "multiple": True}
    first["requested_timecode"] = None
    first["ocr_frame_timecode"] = None
    first["ocr_state"] = "multiple"
    first["visual"] = []
    first["image_drift_ms"] = None
    # The top-level citation cannot honestly name one moment for a batch.
    first["snapped"] = any(m["snapped"] for m in moments)
    first["citation"] = "multiple" if len(moments) > 1 else first.get("citation")
    first["frame_citation"] = "multiple" if len(moments) > 1 else first.get("frame_citation")
    first["ocr_citation"] = "multiple" if len(moments) > 1 else first.get("ocr_citation")
    first["transcript_citation"] = "multiple" if len(moments) > 1 else first.get("transcript_citation")
    # Do not let a replay of the first moment masquerade as the whole batch.
    first["evidence_id"] = None
    first["frame_ms"] = None
    first["frame_timecode"] = None
    first["ocr_frame_ms"] = None
    first["requested_ms"] = None
    return first


def _wait_job(cfg: Any, job_id: str, timeout: float = 1800) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with Database(cfg.db_path) as db:
            job = db.get_job(job_id)
        if not job:
            raise Video2AgentError("E_JOB", f"Job not found: {job_id}")
        if job["state"] in ("ready", "failed", "canceled"):
            return job
        time.sleep(1.0)
    raise Video2AgentError("E_TIMEOUT", f"Job still running after {timeout}s", "Use video2agent jobs --id to check later.")


def _run_account(args: Any, cfg: Any) -> dict[str, Any]:
    from .bili_account import AccountClient

    client = AccountClient(cfg=cfg)
    action = str(getattr(args, "action", "") or "")
    videos = []
    for raw in getattr(args, "videos", []) or []:
        videos.extend(part.strip() for part in str(raw).split(",") if part.strip())
    privacy = 0 if getattr(args, "public", False) else 1

    if action == "status":
        return client.info()
    if action == "folders":
        return client.folders()
    if action == "favorites":
        if args.folder is None:
            raise Video2AgentError("E_ACCOUNT_ARGS", "查看收藏夹需要 --folder。", "先用 account folders 查看 id。")
        return client.favorites(args.folder, limit=args.limit)
    if action == "history":
        return client.history(days=args.days, limit=args.limit)
    if action in ("create-folder", "rename-folder", "delete-folder", "add", "remove"):
        if not args.confirm:
            raise Video2AgentError(
                "E_ACCOUNT_CONFIRM",
                "这是写账号的操作，需要 --confirm。",
                "确认目标收藏夹/视频后再加 --confirm；delete-folder 建议同时给 --expected-title。",
            )
    if action == "create-folder":
        if not args.title:
            raise Video2AgentError("E_ACCOUNT_ARGS", "创建收藏夹需要 --title。")
        return client.create_folder(args.title, args.intro or "", privacy=privacy)
    if action == "rename-folder":
        if args.folder is None or not args.title:
            raise Video2AgentError("E_ACCOUNT_ARGS", "重命名需要 --folder 和 --title。")
        return client.rename_folder(args.folder, args.title, privacy=None if not args.public else 0)
    if action == "delete-folder":
        if args.folder is None:
            raise Video2AgentError("E_ACCOUNT_ARGS", "删除收藏夹需要 --folder。")
        if not getattr(args, "expected_title", None):
            raise Video2AgentError(
                "E_ACCOUNT_CONFIRM",
                "删除收藏夹需要 --expected-title 作为目标校验。",
                "先 account folders 确认 id 和标题，再传 --expected-title。",
            )
        return client.delete_folder(args.folder, expected_title=args.expected_title)
    if action == "add":
        if args.folder is None or not videos:
            raise Video2AgentError("E_ACCOUNT_ARGS", "加入收藏需要 --folder 和 --videos。")
        return client.add_videos(args.folder, videos)
    if action == "remove":
        if args.folder is None or not videos:
            raise Video2AgentError("E_ACCOUNT_ARGS", "移除视频需要 --folder 和 --videos。")
        return client.remove_videos(args.folder, videos)
    if action == "analyze":
        return client.analyze(args.source, folder_id=args.folder, days=args.days, limit=args.limit)
    if action == "classify-plan":
        return client.classify_plan(args.source, folder_id=args.folder, days=args.days)
    if action == "classify-apply":
        raw_plan = args.plan_json
        if not raw_plan and args.plan:
            plan_path = Path(str(args.plan)).expanduser()
            if not plan_path.is_file():
                raise Video2AgentError("E_ACCOUNT_PLAN", f"计划文件不存在：{plan_path}")
            try:
                raw_plan = plan_path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                raise Video2AgentError(
                    "E_ACCOUNT_PLAN",
                    f"计划文件不是 UTF-8：{plan_path}",
                    "用 UTF-8（无 BOM 也可以）重新保存，或直接把 JSON 传给 --plan-json。",
                ) from exc
        if not raw_plan:
            raise Video2AgentError("E_ACCOUNT_PLAN", "需要 --plan 或 --plan-json。", "先用 classify-plan 生成草案。")
        try:
            plan = json.loads(raw_plan)
        except json.JSONDecodeError as exc:
            raise Video2AgentError("E_ACCOUNT_PLAN", f"计划 JSON 非法：{exc}") from exc
        return client.apply_plan(plan, confirm=bool(args.confirm), default_privacy=privacy)
    raise Video2AgentError("E_ACCOUNT_ARGS", f"未知 account 操作：{action}")


def _run_cloud(args: Any, cfg: Any) -> dict[str, Any]:
    from . import cloud

    action = str(getattr(args, "action", "") or "")
    if action == "status":
        return cloud.status(cfg)
    if action == "config":
        raw = sys.stdin.read().strip()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise Video2AgentError("E_CLOUD_CONFIG", f"配置 JSON 非法：{exc}") from exc
        if not isinstance(payload, dict):
            raise Video2AgentError("E_CLOUD_CONFIG", "配置必须是 JSON 对象。")
        return cloud.set_config(cfg, payload)
    if action == "save":
        key = sys.stdin.read().strip()
        return cloud.save_key(cfg, key)
    if action == "test":
        return cloud.test(cfg)
    if action == "clear":
        return cloud.clear_key(cfg)
    if action in ("ocr-on", "ocr-off"):
        return cloud.set_ocr_enabled(cfg, action == "ocr-on")
    if action in ("asr-on", "asr-off"):
        return cloud.set_asr_enabled(cfg, action == "asr-on")
    raise Video2AgentError("E_CLOUD_ARGS", f"未知 cloud 操作：{action}")


def _run_models(args: Any, cfg: Any) -> dict[str, Any]:
    from . import local_models

    action = str(getattr(args, "action", "") or "")
    if action == "status":
        return local_models.status(cfg, getattr(args, "model", None))
    if action == "select":
        return local_models.select(cfg, str(getattr(args, "model", "") or ""))
    if action == "download":
        return local_models.download(cfg, str(getattr(args, "model", None) or ""))
    if action == "uninstall":
        return local_models.uninstall(cfg, str(getattr(args, "model", None) or ""))
    if action == "select-ocr":
        return local_models.select_ocr(cfg, str(getattr(args, "ocr_config", None) or ""))
    raise Video2AgentError("E_MODEL_ARGS", f"未知 models 操作：{action}")


def resolve_video_ref(cfg: Any, ref: str) -> str:
    """Map a vid_ id, a BV/av id, or a platform URL to the stored video id.

    A model usually has the BV id from `find`, not the internal vid_ id; making it
    run `list` first is a wasted round-trip (real log 2026-11-14: outline by BV failed,
    then succeeded after converting to vid_). An unknown reference is returned
    unchanged so the caller still reports E_NOT_FOUND with its remedy.
    """
    text = str(ref or "").strip()
    if not text:
        return text
    try:
        with Database(cfg.db_path) as db:
            if text.startswith("vid_") or db.get_video(text):
                return text
            row = db.one(
                "SELECT id FROM videos WHERE source_uri = ? OR source_path = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                [text, text],
            )
            if row:
                return str(row["id"])
            match = re.search(r"(BV[0-9A-Za-z]{8,}|av\d+)", text)
            if match:
                like = "%" + match.group(1) + "%"
                row = db.one(
                    "SELECT id FROM videos WHERE source_uri LIKE ? OR source_path LIKE ? "
                    "ORDER BY created_at DESC, id DESC LIMIT 1",
                    [like, like],
                )
                if row:
                    return str(row["id"])
    except Exception:
        # A resolution failure must never hide the real command error.
        pass
    return text

def main(argv: list[str] | None = None) -> int:
    args = _make_parser().parse_args(argv)
    if args.command == "__worker":
        from .worker import serve

        return serve()
    as_json = bool(getattr(args, "json", False))
    try:
        cfg = load_config(getattr(args, "home", None), _cookie_overrides(args))
        global _TOKEN_LOG_DIR, _TOKEN_LOG_COMMAND
        _TOKEN_LOG_DIR = Path(cfg.db_path).parent
        _TOKEN_LOG_COMMAND = str(args.command)
        if args.command == "doctor":
            result = doctor(cfg)
            if _DEP_ERROR:
                # Name the missing package instead of dying before the checks run.
                result["ok"] = False
                result["required_ok"] = False
                result.setdefault("checks", []).insert(0, {
                    "name": "python_deps",
                    "ok": False,
                    "detail": f"{type(_DEP_ERROR).__name__}: {_DEP_ERROR}",
                    "remedy": 'pip install "video2agent"',
                    "required": True,
                })
            if args.save:
                save_config(cfg)
            checks = {str(c.get("name")): c for c in result.get("checks", [])}
            failed_required = [c for c in result.get("checks", []) if c.get("required") and not c.get("ok")]
            cached = checks.get("asr_model_cached")
            rapid = checks.get("rapidocr")
            if failed_required:
                # A required failure blocks everything else; name the fix, not the check.
                next_step = "先修：" + str(failed_required[0].get("remedy") or failed_required[0].get("detail") or "")
            elif cached is not None and not cached.get("ok"):
                next_step = (
                    "现在还不能转写没有字幕的视频：先运行 "
                    f"video2agent models download --model {cfg.get('asr_model') or 'small'}（约 464MB），"
                    "或在设置里连接云端 ASR。"
                )
            elif rapid is not None and not rapid.get("ok"):
                next_step = "能转写，但读不了画面文字：pip install \"video2agent[ocr]\" 后重试（本地 OCR 需要 Python 3.11/3.12）。"
            else:
                next_step = "可以开始：video2agent ingest <本地文件或链接>。"
            result["next_step"] = next_step
            _emit(result, as_json)
            if not as_json:
                print(f"\n下一步：{next_step}")
            return 0 if result["required_ok"] else 1
        _require_deps()
        # Accept the BV id / URL a model has in hand instead of demanding the
        # internal vid_ id first (a wasted round-trip in a real 2026-11-14 log).
        if getattr(args, "video_id", None):
            args.video_id = resolve_video_ref(cfg, args.video_id)
        if isinstance(getattr(args, "video_ids", None), list) and args.video_ids:
            args.video_ids = [resolve_video_ref(cfg, v) for v in args.video_ids]
        if args.command == "setup":
            from .setup import setup_dsh

            data = setup_dsh(project=args.project, force=args.force)
            _emit(data, as_json)
            if not as_json:
                print(f"skill: {data['skill_path']}")
                print(data["next"])
            return 0
        if args.command == "biliauth":
            from . import bili_auth

            if args.start:
                info = bili_auth.start_login()
                data = {"ok": True, "key": info["key"], "url": info["url"], "qr": bili_auth.render_qr(info["url"])}
            elif args.poll is not None:
                res = bili_auth.poll_login(args.poll)
                data = {"ok": True, "state": res.get("state")}
                if res.get("state") == "ok":
                    saved = bili_auth.save_login(cfg, res.get("cookies") or {})
                    data.update({"saved": True, "uid": saved.get("uid", "")})
                elif res.get("state") == "failed":
                    # The scan was confirmed but the response carried no session:
                    # say so instead of letting the UI keep polling into "expired".
                    data = {
                        "ok": False,
                        "state": "failed",
                        "reason": res.get("reason") or "no_cookie",
                        "error": "扫码已确认，但没拿到登录态，请重新生成二维码再扫一次。",
                    }
            elif args.status:
                data = {"ok": True, **bili_auth.login_status(cfg)}
            else:
                data = {"ok": True, **bili_auth.clear_login(cfg)}
            if not as_json and args.start:
                # A 19KB base64 blob is not a human login experience. Save the
                # QR as a file and say what to do with it; JSON callers still
                # receive the data URI for the settings card.
                import base64
                raw = str(data.get("qr") or "").split(",", 1)[-1]
                qr_path = Path(cfg.home) / "biliauth-qr.png"
                qr_path.parent.mkdir(parents=True, exist_ok=True)
                qr_path.write_bytes(base64.b64decode(raw))
                print("用手机 B 站 App 扫描二维码：")
                print(f"  {qr_path}")
                print(f"  key: {data.get('key')}")
                print(f"  轮询: video2agent biliauth --poll {data.get('key')}")
                print("扫码确认后运行上面的轮询命令；二维码过期就重新 --start。")
                return 0
            _emit(data, as_json)
            return 0
        if args.command == "discover":
            from .discover import discover_bilibili

            data = discover_bilibili(args.query, cfg, limit=args.limit, covers=not args.no_covers,
                                     uploader=args.uploader, after=args.after, before=args.before)
            # Remember what was offered. Ingest refuses a video from this list until the
            # user chooses (card confirm passes --confirm) — otherwise nothing stops a
            # caller, including a shell command, from indexing the top hit silently.
            remember_offered(cfg, data.get("candidates") or [])
            if args.out:
                Path(args.out).parent.mkdir(parents=True, exist_ok=True)
                Path(args.out).write_text(json_dumps(data, indent=2), encoding="utf-8")
            if as_json:
                _emit(data, True)
            else:
                _print_discover(data)
            return 0
        if args.command == "resolve":
            data = resolve_info(cfg, args.url)
            _emit(data, as_json)
            if not as_json:
                print(f"{data.get('title')}  {data.get('duration')}  {data.get('uploader') or ''}")
            return 0
        if args.command == "ingest":
            if getattr(args, "confirm", False):
                raise Video2AgentError(
                    "E_CONFIRM_FIRST",
                    "只带 --confirm 不算确认",
                    "不要用 --confirm；让模型重新调用 shortlist，由插件签发一次性的 --confirm-token。",
                )
            # An explicit URL is a user action, not an unconfirmed shortlist
            # candidate. The old gate locked a CLI user out for 10 minutes with a
            # remedy only the model could execute. Keep the gate for bare ids.
            url_source = str(args.source or "").strip().lower().startswith(("http://", "https://"))
            blocked = None if url_source else unconfirmed_offer(cfg, args.source)
            if blocked:
                token = str(getattr(args, "confirm_token", "") or "")
                if not _consume_confirm_token(cfg, token, args.source):
                    raise Video2AgentError(
                        "E_CONFIRM_FIRST",
                        f"{blocked} 来自刚才的候选列表，还没确认",
                        "让模型重新调用 shortlist，由插件签发一次性的 --confirm-token。"
                        "用户直接粘贴的链接不在候选表里，不需要这一步。",
                    )
            if args.detach:
                # The job stores profile/language/collection options; worker reads them.
                data = _run_ingest(args, cfg)
                if getattr(args, "confirm_token", ""):
                    clear_offers(cfg)
                _emit(data, as_json)
                if args.wait:
                    job = _wait_job(cfg, data["job_id"])
                    print(json_dumps(job, indent=2))
                return 0
            data = _run_ingest(args, cfg)
            if getattr(args, "confirm_token", ""):
                clear_offers(cfg)
            if as_json:
                _emit(data, True)
            else:
                _print_overview(data.get("overview") or data)
            return 0
        if args.command == "jobs":
            if args.id:
                if args.wait:
                    job = _wait_job(cfg, args.id, timeout=max(1, int(getattr(args, "wait_timeout", 1800))))
                else:
                    with Database(cfg.db_path) as db:
                        job = db.reconcile_job(args.id)
                if not job:
                    # "null" was the previous answer: exit 1, no code, nothing a caller
                    # could act on.
                    raise Video2AgentError(
                        "E_JOB",
                        f"Job not found: {args.id}",
                        "Run `video2agent jobs` to list recent jobs (a detached job id is printed by ingest).",
                    )
                if as_json and job.get("state") == "failed":
                    _emit({"ok": False, "job": job, "error": {
                        "code": str(job.get("error_code") or "E_JOB_FAILED"),
                        "message": str(job.get("error_message") or job.get("error") or f"Job {args.id} failed"),
                        # The worker stored the remedy the user can actually run
                        # (e.g. video2agent models download --model small); a generic
                        # "read the log" line throws that away.
                        "remedy": str(job.get("remedy") or "") or "Read the job log under $VIDEO2AGENT_HOME/logs, fix the cause, then retry.",
                    }}, True)
                    return 1
                _emit(job, as_json)
                if job.get("state") == "failed":
                    failed = Video2AgentError(
                        str(job.get("error_code") or "E_JOB_FAILED"),
                        str(job.get("error_message") or job.get("error") or f"Job {args.id} failed"),
                        str(job.get("remedy") or "") or "Read the job log under $VIDEO2AGENT_HOME/logs, fix the cause, then retry.",
                    )
                    if as_json:
                        _emit({"ok": False, "error": failed.as_dict()}, True)
                    return 1
                return 0
            with Database(cfg.db_path) as db:
                rows = [db.reconcile_job(j["id"]) or j for j in db.list_jobs()]
            _emit({"ok": True, "jobs": rows}, as_json)
            return 0
        if args.command == "ocr-index":
            data = ocr_index(cfg, args.video_id, dry_run=bool(args.dry_run), limit=args.limit)
            if as_json or data.get("dry_run"):
                _emit(data, True)
                if not as_json and data.get("dry_run"):
                    estimate = data.get("estimated_ms")
                    print(f"\n预计读取 {data['to_read']} 帧"
                          + (f"，约 {estimate / 1000:.0f} 秒（实测 {data['per_frame_ms']} ms/帧）" if estimate else "")
                          + f"；确认后运行：{data['command']}")
            else:
                info = data.get("visual_index") or {}
                print("画面索引：" + f"{data.get('indexed', 0)} 帧 · {data.get('tracks', 0)} 条轨迹 · {data.get('seconds', 0)} 秒 · "
                      + f"{info.get('state')}（{info.get('reason')}）")
            return 0
        if args.command == "perceive":
            from .perception import MAX_FRAMES, perceive

            start_ms = parse_time_ms(args.start) if args.start else None
            end_ms = parse_time_ms(args.end) if args.end else None
            data = perceive(cfg, args.video_id, start_ms=start_ms, end_ms=end_ms,
                            fps=args.fps,
                            max_frames=int(args.max_frames or MAX_FRAMES),
                            brief=bool(args.brief))
            if as_json:
                _emit(data, True)
            else:
                _print_perceive(data)
            return 0
        if args.command == "overview":
            data = overview(cfg, args.video_id)
            if as_json:
                _emit(data, True)
            else:
                _print_overview(data)
            return 0
        if args.command == "digest":
            from .digest import digest

            data = digest(cfg, args.video_id, max_chars=args.max_chars, max_frames=args.frames,
                          max_ocr=args.max_ocr, compact=not bool(args.full))
            if as_json:
                _emit(data, True)
            else:
                print(f"{data.get('title')} · {data.get('duration')}")
                print(f"transcript: {len(data.get('transcript') or [])} segments; ocr: {len(data.get('ocr') or [])} tracks")
                if data.get('contact_sheet'):
                    print(f"contact sheet: {data['contact_sheet']}")
                for w in data.get('warnings') or []:
                    print(f"[{w.get('code')}] {w.get('message')}")
            return 0
        if args.command == "transcript":
            start = parse_time_ms(args.start) if args.start else None
            end = parse_time_ms(args.end) if args.end else None
            with Database(cfg.db_path) as db:
                video = require_ready(db.get_video(args.video_id), args.video_id)
                if _stored_caption_mismatch(db, video):
                    source = video.get("source_uri") or args.video_id
                    raise Video2AgentError(
                        "E_CAPTION_CONTENT_MISMATCH",
                        "这条视频的字幕内容与标题不匹配，整条转写不可信。",
                        f"运行 video2agent ingest \"{source}\" --force 重新分析；会丢弃错字幕并回退 ASR。",
                    )
                fitted = _fit_request_times(video, start_ms=start, end_ms=end)
                start, end = fitted["start_ms"], fitted["end_ms"]
                _require_in_range(video, start_ms=start, end_ms=end)
                segs = db.get_segments(args.video_id, start, end, limit=10000)
            warnings = []
            if fitted["unit_fixed"]:
                warnings.append({
                    "code": "TIME_UNIT_FIXED",
                    "message": f"参数看起来是按毫秒传的，已按 {fitted['clamped_ms']} ms 读取",
                    "severity": "info",
                    "remedy": "纯数字按秒解析；毫秒写 1234ms 或 00:01:23.456。",
                })
            if fitted["clamped_end"]:
                media_end = int(video.get("duration_ms") or 0)
                warnings.append({
                    "code": "RANGE_CLAMPED",
                    "message": f"请求的结尾超出媒体 0.1–2 秒，已截到 {format_timecode(media_end)}",
                    "severity": "info",
                    "remedy": None,
                })

            if start is not None and not segs:
                media_end = int(video.get("duration_ms") or 0)
                warnings.append({
                    "code": "TRANSCRIPT_EMPTY_RANGE",
                    "message": f"{format_timecode(start)} 之后没有语音内容（媒体到 {format_timecode(media_end)}）",
                    "severity": "info",
                    "remedy": "换一个范围内的起点，或确认该段是无声/纯画面。",
                })
            if args.compact or (as_json and not args.full):
                # One line per segment, and the budget applies to what is actually
                # emitted. Counting only the spoken text let a 11-minute transcript
                # serialize to 118KB while still claiming `truncated: false`.
                lines: list[str] = []
                chars = 0
                next_start: int | None = None
                for s in segs:
                    # Full HH:MM:SS, because the Skill tells the model to cite that form
                    # and copying "0:12" back out would violate it.
                    line = f"{format_timecode(s['start_ms'], millis=False)} {s['text']}"
                    if lines and chars + len(line) + 1 > args.max_chars:
                        next_start = s["start_ms"]
                        break
                    lines.append(line)
                    chars += len(line) + 1
                data = {
                    "ok": True,
                    "video_id": args.video_id,
                    "format": "compact",
                    "lines": lines,
                    "chars": chars,
                    "segments": len(segs),
                    "truncated": next_start is not None,
                    "next_start_ms": next_start,
                    "warnings": warnings,
                }
            else:
                out = []
                chars = 0
                next_start = None
                for s in segs:
                    if chars + len(s["text"]) > args.max_chars and out:
                        next_start = s["start_ms"]
                        break
                    out.append(s)
                    chars += len(s["text"])
                data = {"ok": True, "video_id": args.video_id, "segments": out,
                        "chars": chars,
                        "truncated": next_start is not None, "next_start_ms": next_start,
                        "warnings": warnings}
            if as_json:
                _emit(data, True)
            elif args.compact:
                for line in data["lines"]:
                    print(line)
                if data["truncated"]:
                    print(f"... truncated at {format_timecode(data['next_start_ms'])}; raise --max-chars for more")
            else:
                for s in data["segments"]:
                    print(f"[{format_timecode(s['start_ms'])}] {s['text']}")
                if data["truncated"]:
                    print("... truncated; raise --max-chars for more")
            return 0
        if args.command == "compare":
            aspects = [x.strip() for x in str(args.aspects or "").split(",") if x.strip()]
            ids = [str(x) for x in (args.video_ids or [])]
            data = compare_videos(cfg, ids, aspects=aspects, per_video=args.per_video, max_chars=args.max_chars,
                                      max_total_chars=args.max_total_chars)
            if as_json:
                _emit(data, True, compact=args.compact)
            else:
                for video in data.get("videos", []):
                    print(f"{video.get('title')}  {video.get('duration')}  {video.get('video_id')}")
                    for line in video.get("transcript", [])[:20]:
                        print(line)
                    for row in video.get("aspects", []):
                        print(f"  {row['aspect']}: {row['coverage']}  {len(row['hits'])} hit(s)")
            return 0
        if args.command == "search":
            modalities = ([m.strip().lower() for m in args.modalities.split(",") if m.strip()]
                          if args.modalities else None)
            if modalities:
                known = {"transcript", "ocr", "visual", "video", "caption", "asr", "segment",
                         "video_meta", "ocr_track", "visual_segment"}
                unknown = [m for m in modalities if m not in known]
                if unknown:
                    raise Video2AgentError(
                        "E_BAD_MODALITY",
                        "不认识的模态：" + ", ".join(unknown),
                        "可用：" + ", ".join(sorted(known)) + "。",
                    )
            start_ms = parse_time_ms(args.start) if args.start else None
            end_ms = parse_time_ms(args.end) if args.end else None
            if args.queries:
                data = search_queries(cfg, [args.query, *args.queries], video_id=args.video,
                                       collection=args.collection, limit=args.limit,
                                       start_ms=start_ms, end_ms=end_ms, modalities=modalities)
            else:
                data = search(cfg, args.query, video_id=args.video, collection=args.collection,
                              limit=args.limit, start_ms=start_ms, end_ms=end_ms, modalities=modalities)
            if args.compact:
                data = _compact_search(data)
            if as_json:
                _emit(data, True)
            else:
                _print_search(data)
            return 0
        if args.command == "evidence":
            if not args.video_id:
                raise Video2AgentError("E_ARGS", "video_id is required")
            if not args.at and not args.start and not args.end and not args.evidence_id:
                raise Video2AgentError(
                    "E_ARGS",
                    "evidence 需要 --at、--start/--end，或 --evidence-id",
                    "例如：video2agent evidence <id> --at 00:00:23 --images 1；不要依赖默认的 0 秒。",
                )
            if str(args.at or "").strip().startswith("-"):
                raise Video2AgentError(
                    "E_BAD_TIME",
                    f"--at 不能是负数（收到 {args.at}）",
                    "时间从 0 开始；要引用开头，用 --at 0。",
                )
            at_text = str(args.at or "")
            list_syntax = at_text.startswith("[") or "," in at_text
            at_values = _parse_at_list(at_text) if at_text else []
            start = parse_time_ms(args.start) if args.start else None
            end = parse_time_ms(args.end) if args.end else None
            if len(at_values) > 1:
                max_images = max(1, min(6, int(args.max_images)))
                per = max(0, min(int(args.images), max_images // len(at_values)))
                results = [
                    evidence(cfg, video_id=args.video_id, at_ms=int(at_ms), start_ms=None, end_ms=None,
                             evidence_id=None, image_budget=per, detail=args.detail,
                             ocr_tiles=bool(args.ocr_tiles))
                    for at_ms in at_values
                ]
                data = _merge_evidence_results(results)
                if per < int(args.images):
                    data.setdefault("warnings", []).append({
                        "code": "EVIDENCE_IMAGES_CAPPED",
                        "message": f"批量 {len(at_values)} 个时间点，图片预算从 {args.images}/点降到 {per}/点（总上限 {args.max_images}）。",
                        "severity": "info",
                    })
            else:
                at = at_values[0] if list_syntax and at_values else (parse_time_ms(args.at) if args.at else None)
                budget = max(0, min(6, int(args.images)))
                data = evidence(cfg, video_id=args.video_id, at_ms=at, start_ms=start, end_ms=end,
                                evidence_id=args.evidence_id, image_budget=budget, detail=args.detail,
                                ocr_tiles=bool(args.ocr_tiles))
                if budget != int(args.images):
                    data.setdefault("warnings", []).append({
                        "code": "EVIDENCE_IMAGES_CAPPED",
                        "message": f"图片预算 {args.images} 已限制为 {budget}（单次上限 6）。",
                        "severity": "info",
                    })
            if as_json:
                _emit(data, True)
            else:
                _print_evidence(data)
            return 0
        if args.command == "ocr-window":
            data = ocr_window(cfg, args.video_id, start_ms=parse_time_ms(args.start),
                              end_ms=parse_time_ms(args.end), fps=args.fps,
                              tiles=bool(args.tiles), max_frames=args.max)
            _emit(data, as_json)
            # ok:false (every planned frame could not be extracted) must not exit 0:
            # the Host treats exit 0 as success and would report ok:true.
            return 0 if data.get("ok", True) else 1
        if args.command == "frames":
            if any(str(value).strip().startswith("-") for value in (args.start, args.end) if value):
                raise Video2AgentError("E_BAD_TIME", "--start/--end 不能是负数")
            crop = None
            if args.crop:
                try:
                    parts = [float(part.strip()) for part in args.crop.split(",")]
                    if len(parts) != 4:
                        raise ValueError
                    crop = tuple(max(0.0, min(1.0, value)) for value in parts)
                except ValueError as exc:
                    raise Video2AgentError("E_ARGS", "--crop 需要 4 个 0-1 的数字：x,y,w,h") from exc
            start_ms = parse_time_ms(args.start) if args.start else None
            end_ms = parse_time_ms(args.end) if args.end else None
            at_ms = parse_time_ms(args.at) if not (start_ms is not None or end_ms is not None) else None
            # `count` is the natural tool-level name for "how many frames"; for a
            # dense window it used to be ignored while `max` controlled the cap.
            max_frames = args.max
            if (start_ms is not None or end_ms is not None) and int(args.count or 1) > 1:
                max_frames = min(15, int(args.count))
            data = frames(cfg, args.video_id, at_ms=at_ms, count=args.count, width=args.width,
                          fmt=args.format, crop=crop, scale=args.scale, start_ms=start_ms, end_ms=end_ms,
                          fps=args.fps, max_frames=max_frames, mode=args.mode,
                          sheet=bool(args.sheet), windows=args.windows)
            if args.out:
                out_dir = Path(args.out)
                out_dir.mkdir(parents=True, exist_ok=True)
                for img in data.get("images") or []:
                    src = Path(img["path"] if isinstance(img, dict) else img)
                    if not src.exists():
                        continue
                    dest = out_dir / src.name
                    shutil.copy2(src, dest)
                    if isinstance(img, dict):
                        img["path"] = str(dest)
                    elif data.get("sheet") == img:
                        data["sheet"] = str(dest)
            _emit(data, as_json)
            # A `{ok:false}` payload with exit 0 looks like success to the Host
            # (index.js keys `ok` off the exit code), so the card would never show
            # the error. Exit non-zero and let the structured envelope travel.
            return 0 if data.get("ok", True) else 1
        if args.command == "candidates":
            data = candidates(cfg, args.video_id, query=args.query, limit=args.limit,
                              images=bool(args.images))
            _emit(data, as_json)
            return 0
        if args.command == "map":
            types = [x.strip() for x in args.types.split(",")] if args.types else None
            data = visual_map(
                cfg, args.video_id, types=types, min_score=args.min_score,
                start_ms=parse_time_ms(args.start) if args.start else None,
                end_ms=parse_time_ms(args.end) if args.end else None,
                limit=args.limit,
            )
            _emit(data, as_json)
            return 0
        if args.command == "export":
            ext = {"md": "md", "html": "html", "json": "json", "knowledge": "knowledge.json"}[args.format]
            out = Path(args.out) if args.out else cfg.exports_dir / f"{args.video_id}.{ext}"
            include_paths = bool(getattr(args, "include_paths", False))
            if args.format == "md":
                path = export_markdown(cfg, args.video_id, out, include_paths=include_paths)
            elif args.format == "html":
                path = export_html(cfg, args.video_id, out)
            elif args.format == "json":
                path = export_json(cfg, args.video_id, out, include_paths=include_paths)
            else:
                path = export_knowledge(cfg, args.video_id, out, include_paths=include_paths)
            _emit({"ok": True, "path": str(path)}, as_json)
            return 0
        if args.command == "bench":
            from .bench import run_bench

            queries = [q.strip() for q in args.queries.split(",") if q.strip()]
            data = run_bench(cfg, args.video_id, queries, image_budget=args.images)
            if as_json:
                _emit(data, True)
            else:
                print(f"{data.get('title')}  video={data.get('video_id')}")
                print(f"overview={data['latency_ms']['overview']}ms  search p50={data['latency_ms']['search_p50']}ms p95={data['latency_ms']['search_p95']}ms  ~tokens={data['estimated_tokens']}")
                for q in data["queries"]:
                    print(f"- {q['query']}: {q['results']} results, search {q['search_ms']}ms, evidence {q['evidence_ms']}ms, images {q['evidence_images']}")
            return 0
        if args.command == "list":
            data = list_videos(cfg, limit=args.limit)
            _emit(data, as_json)
            return 0
        if args.command == "stats":
            from .visual import ocr_available

            with Database(cfg.db_path) as db:
                stats = db.stats()
            data = {"ok": True, "db": stats, "home": str(cfg.home),
                    "sizes": {"media": _dir_size(cfg.media_dir), "derived": _dir_size(cfg.derived_dir),
                              "covers": _dir_size(cfg.covers_dir), "exports": _dir_size(cfg.exports_dir)},
                    "ocr_available": ocr_available()}
            _emit(data, as_json)
            return 0
        if args.command == "gc":
            # Validate before any deletion: gc --max-gb 0 used to delete old
            # temp files/covers/logs and only then reject the argument.
            if args.max_gb is not None and (not math.isfinite(args.max_gb) or args.max_gb <= 0):
                raise Video2AgentError(
                    "E_MAX_GB", "--max-gb 必须大于 0",
                    "用 --max-gb 0.5 这样的正数；0 或负数会清空所有 URL 缓存。",
                )
            # The cache policy is read (and validated) before any deletion too: a
            # corrupt/Infinity limit used to fail E_INTERNAL after old temp files
            # and logs were already gone.
            auto_policy = cache_policy(cfg) if args.auto else None
            removed = []
            removed_bytes = 0
            for d, pattern in ((cfg.derived_dir, "*.tmp"), (cfg.covers_dir, "*.jpg")):
                for p in d.rglob(pattern):
                    try:
                        if time.time() - p.stat().st_mtime < 7 * 86400:
                            continue
                        size = p.stat().st_size
                        if not args.dry_run:
                            p.unlink()
                        # Count only what actually disappeared; a failed unlink
                        # used to be reported as freed bytes.
                        removed.append(str(p))
                        removed_bytes += size
                    except OSError:
                        pass

            # Job logs carry the source title/URL and local paths. They are pruned by
            # age on every gc (default 7 days), matching the other temp artifacts.
            log_days = int(args.keep_logs_days if args.keep_logs_days is not None else 7)
            logs_removed, logs_bytes = _prune_logs(cfg, log_days, bool(args.dry_run))
            removed_bytes += logs_bytes

            evicted = []
            cache_before = cached_usage(cfg)
            cache_after = cache_before
            retention_days = None
            policy = None
            if args.auto:
                policy = auto_policy
                retention_days = policy["days"] if policy["expire"] else None
                max_gb = policy["limit_gb"] if policy["limit_enabled"] else None
                with Database(cfg.db_path) as db:
                    plan = plan_cache_purge(cfg, db, older_than_days=retention_days, max_gb=max_gb)
                    for item in plan:
                        if args.dry_run:
                            evicted.append(item)
                            freed = int(item.get("bytes") or 0)
                        else:
                            result = purge_video(cfg, db, item["video_id"], reason=item.get("reason", "expiry"))
                            evicted.append(result)
                            freed = int(result.get("bytes") or 0) if not result.get("error") else 0
                        removed_bytes += freed
                        cache_after -= freed
                cache_after = max(0, cache_after)
            elif args.sources or args.max_gb is not None:
                if args.sources:
                    retention_days = args.older_than_days if args.older_than_days is not None else int(cfg.get("source_retention_days") or 7)
                with Database(cfg.db_path) as db:
                    plan = plan_evictions(cfg, db, older_than_days=retention_days, max_gb=args.max_gb)
                    for item in plan:
                        if args.dry_run:
                            evicted.append(item)
                            freed = int(item.get("bytes") or 0)
                        else:
                            result = evict_video(cfg, db, item["video_id"], dry_run=False, reason=item.get("reason", "retention"))
                            evicted.append(result)
                            # files_busy kept the row; nothing was actually freed.
                            freed = int(result.get("bytes") or 0) if not result.get("error") else 0
                        removed_bytes += freed
                        cache_after -= freed
                cache_after = max(0, cache_after)
            payload = {"ok": True, "dry_run": args.dry_run, "removed": removed,
                       "logs_removed": logs_removed, "logs_retention_days": log_days,
                       "removed_bytes": removed_bytes, "removed_human": human_bytes(removed_bytes),
                       "cache_before": cache_before, "cache_after": cache_after,
                       "cache_before_human": human_bytes(cache_before), "cache_after_human": human_bytes(cache_after)}
            if args.auto:
                payload["auto"] = True
                payload["policy"] = policy
            if args.auto or args.sources or args.max_gb is not None:
                payload["evicted"] = evicted
                payload["retention_days"] = retention_days
                payload["max_gb"] = args.max_gb if not args.auto else (policy["limit_gb"] if policy["limit_enabled"] else None)
            _emit(payload, as_json)
            return 0
        if args.command == "worker":
            return _worker(args)
        if args.command == "account":
            result = _run_account(args, cfg)
            _emit(result, as_json)
            return 0 if result.get("ok", True) else 1
        if args.command == "cloud":
            result = _run_cloud(args, cfg)
            _emit(result, as_json)
            return 0 if result.get("ok", True) else 1
        if args.command == "models":
            result = _run_models(args, cfg)
            _emit(result, as_json)
            return 0 if result.get("ok", True) else 1
        raise Video2AgentError("E_ARGS", f"Unknown command: {args.command}")
    except Exception as e:
        if isinstance(e, sqlite3.OperationalError):
            message = str(e)
            if "readonly" in message.lower():
                return _err(Video2AgentError(
                    "E_DB_READONLY",
                    "库是只读打开的，写不进去",
                    "检查库文件权限，或确认没有别的进程以只读方式挂着它。",
                ), as_json)
            if "no such table" in message.lower():
                return _err(Video2AgentError(
                    "E_DB_SCHEMA",
                    f"库缺少索引表（{message}）",
                    "删除该库后重新 ingest，或用 --force 重扫；旧库会自动迁移。",
                ), as_json)
        return _err(e, as_json)


if __name__ == "__main__":
    raise SystemExit(main())
