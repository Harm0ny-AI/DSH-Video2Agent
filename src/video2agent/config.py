from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .util import ensure_dir, human_bytes, install_hint, which

DEFAULT_CONFIG: dict[str, Any] = {
    "asr_model": "small",
    "asr_model_fast": "tiny",
    "asr_device": "auto",
    "asr_compute_type": "int8",
    "asr_beam_size": 1,
    "asr_word_timestamps": False,
    "asr_cpu_threads": 0,
    "cloud_provider": "siliconflow",
    "cloud_base_url": "https://api.siliconflow.cn/v1",
    "cloud_asr_model": "XingChenAGI/XingChenASR-V3.2-Ultra",
    "cloud_ocr_model": "deepseek-ai/DeepSeek-OCR",
    "cloud_ocr_enabled": False,
    "ocr_local_config": None,
    "language": None,
    "max_duration_min": 480,
    "max_download_mb": 4096,
    "cache_gb": 50,
    "source_retention_days": 7,
    "ocr_max_frames": 120,
    "default_profile": "auto",
    "ytdlp_format": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "cookies_file": None,
    "mirror": None,
    "allow_private_urls": False,
    "allowed_roots": [],
}


@dataclass
class Config:
    home: Path
    data: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, Any] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.home / "library.db"

    @property
    def media_dir(self) -> Path:
        return self.home / "media"

    @property
    def derived_dir(self) -> Path:
        return self.home / "derived"

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def covers_dir(self) -> Path:
        return self.home / "covers"

    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.overrides:
            return self.overrides[key]
        return self.data.get(key, DEFAULT_CONFIG.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self.overrides[key] = value

    def as_dict(self) -> dict[str, Any]:
        return {
            "home": str(self.home),
            "db_path": str(self.db_path),
            "media_dir": str(self.media_dir),
            "derived_dir": str(self.derived_dir),
            "config_path": str(self.config_path),
            "settings": {**DEFAULT_CONFIG, **self.data, **self.overrides},
        }


def default_home() -> Path:
    env = os.environ.get("VIDEO2AGENT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".video2agent").resolve()


def load_config(home: str | Path | None = None, overrides: dict[str, Any] | None = None) -> Config:
    h = Path(home).expanduser().resolve() if home else default_home()
    ensure_dir(h)
    data: dict[str, Any] = {}
    cfg_file = h / "config.json"
    if cfg_file.exists():
        try:
            loaded = json.loads(cfg_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
            else:
                raise ValueError("config root is not an object")
        except Exception:
            # Never silently overwrite a corrupt config on the next save: keep a
            # copy for inspection, then start from defaults.
            try:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                shutil.copy2(cfg_file, cfg_file.with_name(cfg_file.name + f".corrupt-{stamp}"))
            except Exception:
                pass
            data = {}
    cfg = Config(home=h, data=data, overrides=overrides or {})
    for d in (cfg.media_dir, cfg.derived_dir, cfg.models_dir, cfg.logs_dir, cfg.exports_dir, cfg.covers_dir):
        ensure_dir(d)
    return cfg


def save_config(cfg: Config) -> Path:
    payload = {**DEFAULT_CONFIG, **cfg.data, **cfg.overrides}
    target = cfg.config_path
    # A unique temp name + atomic replace: a crash mid-write must not leave a
    # truncated config that the next run silently resets.
    tmp = target.with_name(target.name + f".tmp-{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def package_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def disk_usage(path: Path) -> dict[str, int]:
    try:
        usage = shutil.disk_usage(path)
        return {"total": usage.total, "used": usage.used, "free": usage.free}
    except Exception:
        return {"total": 0, "used": 0, "free": 0}


def doctor(cfg: Config | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, remedy: str | None = None, required: bool = True) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "remedy": remedy, "required": required})

    add("python", sys.version_info >= (3, 11), sys.version.split()[0], "Install Python 3.11 or newer.")
    for tool in ("ffmpeg", "ffprobe"):
        p = which(tool)
        add(tool, bool(p), p or "not found", install_hint(tool))
    ytdlp = which("yt-dlp")
    add("yt-dlp", bool(ytdlp), ytdlp or "not found", "pip install yt-dlp", required=False)
    add("yt_dlp_python", package_available("yt_dlp"), "python package", "pip install yt-dlp", required=False)
    add("faster_whisper", package_available("faster_whisper"), "python package", "pip install faster-whisper", required=False)
    add("rapidocr", package_available("rapidocr_onnxruntime"), "python package", "pip install rapidocr-onnxruntime", required=False)
    add("opencv", package_available("cv2"), "python package", "pip install opencv-python-headless", required=False)
    add("numpy", package_available("numpy"), "python package", "pip install numpy", required=False)
    add("pillow", package_available("PIL"), "python package", "pip install Pillow", required=False)
    du = disk_usage(cfg.home)
    free_gb = du["free"] / (1024 ** 3)
    add("disk", free_gb >= 5, f"{free_gb:.1f} GB free at {cfg.home}", "Free at least 5 GB or move VIDEO2AGENT_HOME.", required=True)
    add("home_writable", os.access(cfg.home, os.W_OK), str(cfg.home), "Set VIDEO2AGENT_HOME to a writable directory.", required=True)
    roots = cfg.get("allowed_roots") or []
    add(
        "allowed_roots",
        bool(roots),
        f"{len(roots)} root(s)" if roots else "empty: any local path the user can read",
        "For a shared machine, set allowed_roots in config.json before exposing the CLI to untrusted prompts.",
        required=False,
    )
    add("asr_model", True, str(cfg.get("asr_model")), "Download from Settings → Video2Agent, or run `video2agent models download`.", required=False)
    # "small" being configured says nothing about whether it is on disk. The
    # pipeline no longer downloads it implicitly; the user must choose it in
    # Settings or run the models command.
    try:
        from .text import whisper_cache_state
        cache = whisper_cache_state(str(cfg.get("asr_model") or "small"))
        add(
            "asr_model_cached",
            # A configured model name says nothing about the file being on disk: this
            # used to report ok=True while the model was missing, so doctor was all
            # green and the first silent video then had no transcript.
            bool(cache["cached"]),
            f"{cache['model']}: " + (f"{human_bytes(cache['bytes'])} at {cache['path']}" if cache["cached"]
                                     else f"尚未下载（约 464MB，需要时下载到 {cache['path']}）"),
            f"运行 video2agent models download --model {cache['model']}（约 464MB），或在 DSH 设置 → Video2Agent 里连接云端 ASR。",
            required=False,
        )
    except Exception:  # noqa: BLE001 - doctor must never fail on an optional probe
        pass
    # Bilibili hides CC subtitles from anonymous requests, so this line tells a
    # user whether their cookie export is actually being picked up.
    try:
        from .captions import cookie_path, is_logged_in, load_netscape_cookies
        cookie_file = cookie_path(cfg)
        logged_in = is_logged_in(load_netscape_cookies(cookie_file))
        add(
            "bilibili_login",
            True,
            ("登录 cookie 已配置；优先使用 UP 主/AI 字幕" if logged_in
             else f"匿名（{cookie_file.name if cookie_file else 'no cookies'}）；B 站字幕不可见，会回退 ASR"),
            None if logged_in else "导出 B 站 cookies（Netscape 格式）并设置 cookies_file 或 --cookies，即可优先使用字幕。",
            required=False,
        )
    except Exception:  # noqa: BLE001 - doctor must never fail on an optional hint
        add("bilibili_login", True, "unknown", None, required=False)
    # A transcript that runs past the media, or covers only a fraction of it, means the
    # rows do not belong to this video. Two records in the local library had a 269s video
    # with 562s of someone else's transcript and a 1092s video with 24s; nothing else
    # would ever surface that.
    try:
        from .db import Database
        if Path(cfg.db_path).exists():
            bad: list[str] = []
            with Database(cfg.db_path) as db:
                for video in db.list_videos(limit=200):
                    duration = int(video.get("duration_ms") or 0)
                    if not duration:
                        continue
                    row = db.one(
                        "SELECT count(*) n, max(end_ms) last FROM segments WHERE video_id=?",
                        [video["id"]],
                    ) or {}
                    last = int(row.get("last") or 0)
                    if last > duration * 1.05:
                        bad.append(f"{video['id']} 转写超出媒体 {last - duration}ms")
                        continue
                    if int(row.get("n") or 0) >= 20 and last < duration * 0.3:
                        bad.append(f"{video['id']} 转写只覆盖 {last}/{duration}ms")
                        continue
                    # Duration can be valid while the words belong to another video
                    # (observed with an AI track). Surface that too; otherwise the
                    # doctor says "alignment ok" while the transcript is useless.
                    full = db.get_video(video["id"])
                    metrics = (full.get("meta") or {}).get("analysis_metrics") or {} if full else {}
                    if metrics.get("transcript_source") == "caption":
                        from .captions import caption_content_mismatch
                        segs = db.get_segments(video["id"], limit=120)
                        meta = (full or {}).get("meta") or {}
                        if caption_content_mismatch(segs, (full or {}).get("title"), meta.get("description"), meta.get("tags")):
                            bad.append(f"{video['id']} 字幕内容与标题不匹配")
            add(
                "transcript_alignment",
                not bad,
                "一致" if not bad else "；".join(bad[:5]) + (f"（共 {len(bad)} 条）" if len(bad) > 5 else ""),
                "这些记录的转写不属于该视频：用 video2agent ingest <source> --force 重扫。",
                required=False,
            )
    except Exception:  # noqa: BLE001 - a diagnostic check must not break doctor
        pass

    required_ok = all(c["ok"] for c in checks if c["required"])
    optional_ok = sum(1 for c in checks if c["ok"] and not c["required"])
    optional_total = sum(1 for c in checks if not c["required"])
    return {
        "ok": required_ok,
        "required_ok": required_ok,
        "optional_ok": optional_ok,
        "optional_total": optional_total,
        "checks": checks,
        "home": str(cfg.home),
        "disk": du,
    }
