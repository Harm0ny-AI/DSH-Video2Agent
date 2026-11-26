from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


class Video2AgentError(Exception):
    def __init__(self, code: str, message: str, remedy: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy = remedy

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "remedy": self.remedy}


# A video in one of these states is finished (unsuccessfully or retired); it is
# not "still processing", so every read surface must say so consistently.
TERMINAL_VIDEO_STATUSES = ("failed", "canceled", "cancelled", "evicted")


def not_ready_error(video_id: str, status: object, *, action: str = "引用") -> "Video2AgentError":
    """One message for every reader that needs a finished video."""
    state = str(status or "unknown")
    if state == "source_ready":
        # source_only is a successful terminal state, just not an analysable one.
        return Video2AgentError(
            "E_NOT_READY",
            f"{video_id} 目前只准备了源文件（source_only），没有转写或画面索引",
            "需要内容时重新 ingest（不要带 --profile source_only）。",
        )
    if state in TERMINAL_VIDEO_STATUSES:
        return Video2AgentError(
            "E_NOT_READY",
            f"{video_id} 处理没有成功（状态 {state}），没有可{action}的内容",
            "重新 ingest 该视频；不要引用失败或已清除的记录。",
        )
    return Video2AgentError(
        "E_NOT_READY",
        f"{video_id} 还在处理（状态 {state}），现在没有可{action}的内容",
        "用 video2agent jobs 看进度，完成后再问；不要从半成品里引用时间码。",
    )


def pid_alive(pid: int) -> bool:
    """Is that process still running?

    A detached worker can die without writing its terminal state; the job row then
    says `running` forever and the next ingest queues behind a ghost.
    """
    if not pid:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid)
        )
        if not handle:
            # ERROR_ACCESS_DENIED (5) means the process exists but is not ours to
            # query; treating that as dead would fail a live job.
            return ctypes.windll.kernel32.GetLastError() == 5
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    raw = "\x1f".join(str(p) for p in parts)
    return f"{prefix}_{sha256_text(raw)[:length]}"


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


_TIME_RE = re.compile(r"^(?:(?P<h>\d+):)?(?:(?P<m>\d+):)?(?P<s>\d+(?:\.\d+)?)$")
_UNIT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>h|m|s|ms)", re.I)


def parse_time_ms(value: str | int | float | None, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return max(0, int(round(float(value) * 1000)))
    text = str(value).strip().lower()
    if not text:
        return default
    if text.isdigit():
        return max(0, int(text) * 1000)
    if text.endswith("ms") and text[:-2].replace(".", "", 1).isdigit():
        return max(0, int(float(text[:-2])))
    total = 0.0
    found = False
    for m in _UNIT_RE.finditer(text):
        found = True
        num = float(m.group("num"))
        unit = m.group("unit").lower()
        total += num * {"h": 3600, "m": 60, "s": 1, "ms": 0.001}[unit]
    if found:
        return max(0, int(round(total * 1000)))
    parts = text.split(":")
    try:
        if len(parts) == 1:
            seconds = float(parts[0])
        elif len(parts) == 2:
            seconds = int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            raise ValueError(text)
        return max(0, int(round(seconds * 1000)))
    except ValueError as e:
        raise Video2AgentError("E_BAD_TIME", f"Cannot parse time: {value!r}", "Use 90, 1:30, 00:01:30.500, or 1m30s.") from e


def format_timecode(ms: int | float | None, millis: bool = True) -> str:
    if ms is None:
        return "--:--"
    total = max(0, int(round(float(ms))))
    h, rem = divmod(total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    if millis:
        return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def short_timecode(ms: int | float | None) -> str:
    """`0:12` / `12:34` / `1:02:03` — the compact form for one transcript line.

    A full `00:00:12` costs five extra characters on every segment; over 460
    segments that is most of the token budget spent on leading zeros.
    """
    if ms is None:
        return "--:--"
    total = max(0, int(round(float(ms))))
    h, rem = divmod(total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s = rem // 1000
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_duration(ms: int | float | None) -> str:
    if ms is None:
        return "?"
    total = int(round(float(ms) / 1000))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def human_bytes(n: int | float | None) -> str:
    n = float(n or 0)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024.0 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def json_dumps(value: Any, indent: int | None = 2) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent, default=str)


def write_json(path: str | Path, value: Any) -> None:
    p = Path(path)
    ensure_dir(p.parent)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json_dumps(value, indent=2), encoding="utf-8")
    tmp.replace(p)


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _video2agent_home() -> Path:
    raw = os.environ.get("VIDEO2AGENT_HOME")
    return Path(raw) if raw else Path.home() / ".video2agent"


def _managed_tool_path(name: str) -> str | None:
    if name not in FFMPEG_TOOLS:
        return None
    try:
        data = json.loads((_video2agent_home() / "tools" / "ffmpeg.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    value = data.get(name) if isinstance(data, dict) else None
    return str(value) if value and Path(str(value)).is_file() else None


def _winget_tool_path(name: str) -> str | None:
    if sys.platform != "win32" or name not in FFMPEG_TOOLS:
        return None
    root = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    packages = root / "Microsoft" / "WinGet" / "Packages"
    if not packages.is_dir():
        return None
    wanted = name + ".exe"
    try:
        candidates = sorted(
            (p for p in packages.iterdir() if "ffmpeg" in p.name.lower()),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return None
    for package in candidates:
        for path in package.rglob(wanted):
            if path.is_file():
                return str(path)
    return None


def which(name: str) -> str | None:
    if name in FFMPEG_TOOLS:
        managed = _managed_tool_path(name)
        if managed:
            return managed
        found = shutil.which(name)
        if found:
            return found
        # WinGet upgrades can leave a stale PATH entry (ffmpeg-8.x) while the
        # current package lives under WinGet/Packages/Gyan.FFmpeg-*/bin.
        return _winget_tool_path(name)
    return shutil.which(name)




FFMPEG_TOOLS = ("ffmpeg", "ffprobe")


def install_hint(tool: str) -> str:
    """A copy-pasteable install command for an external tool we shell out to.

    The agent (or the user) gets this text from a failure, so it must name the
    real command for the platform instead of "install FFmpeg somehow" — a user in
    DSH asks the assistant to fix the error, and this is what it will run.
    """
    name = str(tool).lower()
    if name not in FFMPEG_TOOLS:
        return f"Install {tool} and make sure it is on PATH."
    if sys.platform == "win32":
        command = "winget install Gyan.FFmpeg"
    elif sys.platform == "darwin":
        command = "brew install ffmpeg"
    else:
        command = "sudo apt install ffmpeg"
    return (
        f"{command}（装好后重开终端）。"
        "如果 FFmpeg 已经装在别的目录，把 FFMPEG_BIN / FFPROBE_BIN 设为它的完整路径。"
    )


def _subprocess_kwargs(cwd: str | Path | None = None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


def no_window_kwargs() -> dict[str, Any]:
    """Keep child processes from flashing a console window on Windows."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


@dataclass
class RunResult:
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run(cmd: Sequence[str], *, timeout: float | None = 120, cwd: str | Path | None = None,
        check: bool = False, error_code: str = "E_COMMAND") -> RunResult:
    args = [str(c) for c in cmd]
    try:
        proc = subprocess.run(args, timeout=timeout, **_subprocess_kwargs(cwd))
    except FileNotFoundError as e:
        # The stem keeps "ffmpeg.exe" in the FFmpeg family: the docs tell Windows
        # users to point FFMPEG_BIN at the .exe, so a missing .exe must still be
        # E_FFMPEG with the install command. Normalize both separators so the same
        # error is produced on POSIX when a Windows-style path is passed in.
        raw = str(args[0])
        basename = raw.replace("\\", "/").rsplit("/", 1)[-1].lower()
        tool = basename[:-4] if basename.endswith(".exe") else basename
        if tool in FFMPEG_TOOLS:
            env_key = "FFMPEG_BIN" if tool == "ffmpeg" else "FFPROBE_BIN"
            override = os.environ.get(env_key)
            if override and not Path(override).is_file():
                message = f"{env_key} 指向不存在的文件：{override}"
            elif "\\" in raw or "/" in raw:
                message = f"{tool} 路径不存在：{args[0]}（检查 {env_key}）"
            else:
                message = f"{tool} 未安装或不在 PATH 上（视频探测/抽帧需要它）。"
            raise Video2AgentError("E_FFMPEG", message, install_hint(tool)) from e
        raise Video2AgentError("E_TOOL_MISSING", f"Command not found: {args[0]}", "Run: video2agent doctor") from e
    except subprocess.TimeoutExpired as e:
        raise Video2AgentError("E_TIMEOUT", f"Command timed out after {timeout}s: {args[0]}", "Try a shorter range or smaller profile.") from e
    result = RunResult(proc.returncode, proc.stdout or "", proc.stderr or "", args)
    if check and not result.ok:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise Video2AgentError(error_code, f"Command failed ({result.returncode}): {args[0]}\n{detail}", "Check the input and run video2agent doctor.")
    return result


def spawn_detached(cmd: Sequence[str], *, log_path: str | Path | None = None,
                   env: dict[str, str] | None = None, cwd: str | Path | None = None) -> int:
    args = [str(c) for c in cmd]
    log = open(log_path, "ab") if log_path else subprocess.DEVNULL
    kwargs: dict[str, Any] = {
        "stdout": log,
        "stderr": log,
        "stdin": subprocess.DEVNULL,
        "cwd": str(cwd) if cwd else None,
        "env": env,
    }
    if os.name == "nt":
        # A venv launcher without a console can give the Python process it starts
        # a visible one. Give both a windowless console in a separate process group.
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(args, **kwargs)
    if log_path:
        try:
            log.close()
        except Exception:
            pass
    return proc.pid


def iter_json_lines(text: str) -> Iterable[dict[str, Any]]:
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def require_tool(name: str, remedy: str | None = None) -> str:
    tool = str(name).lower()
    if tool in FFMPEG_TOOLS:
        env_key = "FFMPEG_BIN" if tool == "ffmpeg" else "FFPROBE_BIN"
        override = os.environ.get(env_key)
        if override:
            if Path(override).is_file():
                return override
            raise Video2AgentError(
                "E_FFMPEG",
                f"{env_key} 指向不存在的文件：{override}",
                remedy or install_hint(tool),
            )
        path = which(name)
        if path:
            return path
        raise Video2AgentError(
            "E_FFMPEG",
            f"{name} 未安装或不在 PATH 上（视频探测/抽帧需要它）。",
            remedy or install_hint(name),
        )
    path = which(name)
    if not path:
        raise Video2AgentError("E_TOOL_MISSING", f"Required tool not found: {name}", remedy or "Run: video2agent doctor")
    return path
