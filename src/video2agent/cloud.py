"""SiliconFlow cloud ASR/OCR and the local secret store.

The key is never written to `ui-settings.json`, never put in argv, never returned
by a route, and never logged. On Windows it is protected with DPAPI (encryption
bound to the current Windows user). Other platforms can use the
`SILICONFLOW_API_KEY` environment variable; Settings key saving is Windows-only.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Config
from .util import Video2AgentError, no_window_kwargs

PROVIDER = "siliconflow"
BASE_URL = "https://api.siliconflow.cn/v1"
INVITE_URL = "https://cloud.siliconflow.cn/i/gFnkeTR4"
INTERNATIONAL_URL = "https://www.siliconflow.com"
DEFAULT_ASR = "XingChenAGI/XingChenASR-V3.2-Ultra"
DEFAULT_OCR = "deepseek-ai/DeepSeek-OCR"
MODEL_OPTIONS = {
    "asr": [DEFAULT_ASR, "XingChenAGI/XingChenASR-V3.2", "whisper-1"],
    "ocr": [DEFAULT_OCR, "gpt-4o-mini", "gpt-4o"],
}
PROVIDER_PRESETS = [
    {
        "id": "siliconflow",
        "label": "SiliconFlow",
        "base_url": BASE_URL,
        "invite_url": INVITE_URL,
        "international_url": INTERNATIONAL_URL,
    },
    {
        "id": "custom",
        "label": "自定义（OpenAI 兼容）",
        "base_url": "",
        "invite_url": None,
        "international_url": None,
    },
]


class _Blob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi(data: bytes, protect: bool) -> bytes:
    if os.name != "nt" or not hasattr(ctypes, "windll"):
        raise Video2AgentError(
            "E_CLOUD_SECRET_STORE",
            "当前系统没有可用的 Windows DPAPI 密钥存储。",
            "在 Windows 上使用设置页保存 Key，或设置 SILICONFLOW_API_KEY 环境变量。",
        )
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    target = _Blob()
    ok = fn(
        ctypes.byref(source),
        ctypes.c_wchar_p("Video2Agent cloud API key") if protect else None,
        None, None, None, 0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(target),
    )
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def _secret_path(cfg: Config) -> Path:
    return cfg.home / "secrets" / "cloud.bin"


def _config_path(cfg: Config) -> Path:
    return cfg.home / "cloud.json"


def _read_config(cfg: Config) -> dict[str, Any]:
    defaults = {
        "provider": PROVIDER,
        "base_url": BASE_URL,
        "asr_model": DEFAULT_ASR,
        "ocr_model": DEFAULT_OCR,
        "ocr_enabled": False,
        "asr_enabled": True,
    }
    path = _config_path(cfg)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                defaults.update({k: data[k] for k in defaults if k in data})
            else:
                defaults["corrupt"] = True
        except Exception:
            # A corrupt file must not silently retarget a stored key at the
            # default SiliconFlow endpoint: that uploads audio to a provider the
            # user never configured. Mark it so callers disable cloud instead.
            defaults["corrupt"] = True
    return defaults


def _write_config(cfg: Config, patch: dict[str, Any]) -> dict[str, Any]:
    data = _read_config(cfg)
    # Only a full provider reset may overwrite a corrupt file; a toggle must not
    # silently adopt the default provider while a custom key is still stored.
    if data.get("corrupt") and not {"provider", "base_url"} <= set(patch):
        raise Video2AgentError(
            "E_CLOUD_CONFIG",
            "cloud.json 已损坏，无法确定当前服务商",
            "在设置页重新填写服务商与 Base URL 并保存（会重建配置）。",
        )
    data.pop("corrupt", None)
    data.update({k: patch[k] for k in data if k in patch})
    path = _config_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic: an interrupted write used to leave unparseable JSON, which then
    # silently changed the provider.
    # Unique per process: a fixed .tmp name lets two concurrent writers collide.
    tmp = path.with_suffix(".json.tmp-" + str(os.getpid()))
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return data


def _clean_text(value: Any, field: str, limit: int = 200) -> str:
    text = str(value or "").strip()
    if not text:
        raise Video2AgentError("E_CLOUD_CONFIG", f"{field}不能为空。", "填写服务商信息和模型 ID。")
    if len(text) > limit or any(ord(c) < 32 for c in text):
        raise Video2AgentError("E_CLOUD_CONFIG", f"{field}格式不正确。", "检查后重试。")
    return text


def _validate_base_url(value: Any) -> str:
    raw = _clean_text(value, "Base URL", 500).rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise Video2AgentError("E_CLOUD_CONFIG", "Base URL 必须是完整的 http(s) 地址。", "例如 https://api.example.com/v1。")
    if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise Video2AgentError(
            "E_CLOUD_CONFIG",
            "远程服务必须使用 HTTPS；HTTP 只允许本机地址。",
            "换成 HTTPS 地址，或用 localhost 上的本地兼容服务。",
        )
    return raw


def set_config(cfg: Config, payload: dict[str, Any]) -> dict[str, Any]:
    """Save any OpenAI-compatible provider/model choice, not just SiliconFlow.

    The key is intentionally cleared when the provider/base URL changes: a key
    issued by one service must never be silently sent to another endpoint.
    """
    old = _read_config(cfg)
    provider = _clean_text(payload.get("provider") or old["provider"], "服务商", 80)
    base_url = _validate_base_url(payload.get("base_url") or old["base_url"])
    asr_model = _clean_text(payload.get("asr_model") or old["asr_model"], "ASR 模型")
    ocr_model = _clean_text(payload.get("ocr_model") or old["ocr_model"], "OCR 模型")
    asr_enabled = bool(payload.get("asr_enabled", old.get("asr_enabled", True)))
    # A corrupt file means we never learned which endpoint the stored key belongs
    # to: treat the save as an endpoint change so the key is not silently reused.
    changed_endpoint = (provider != old["provider"] or base_url != old["base_url"]
                        or bool(old.get("corrupt")))
    # Clear the old key FIRST: if the new endpoint is persisted while the key
    # deletion fails, the next request would send the old key to the new host.
    cleared = False
    if changed_endpoint:
        clear_key(cfg)
        cleared = True
    try:
        data = _write_config(cfg, {
            "provider": provider,
            "base_url": base_url,
            "asr_model": asr_model,
            "ocr_model": ocr_model,
            "asr_enabled": asr_enabled,
        })
    except Exception as exc:
        # The key is already gone at this point; say so instead of a bare failure
        # that leaves the user wondering why cloud turned itself off.
        if cleared:
            raise Video2AgentError(
                "E_CLOUD_CONFIG",
                f"切换服务商时已清除旧 Key，但保存新配置失败：{exc}",
                "重新填写服务商与 Base URL，再粘贴 Key 保存一次。",
            ) from exc
        raise
    # An environment key (VIDEO2AGENT_CLOUD_API_KEY / SILICONFLOW_API_KEY) survives
    # a clear, so claiming "key cleared" next to it told the UI cloud was off while
    # audio still went out with that key. Report what is actually in effect.
    state = status(cfg)
    return {
        "ok": True,
        "provider": data["provider"],
        "base_url": data["base_url"],
        "asr_model": data["asr_model"],
        "ocr_model": data["ocr_model"],
        "asr_enabled": bool(data.get("asr_enabled", True)),
        "key_cleared": bool(cleared and state.get("source") != "env"),
        "configured": bool(state.get("configured")),
        "source": state.get("source"),
        "last4": state.get("last4") or "",
    }


def _key_last4(key: str) -> str:
    return key[-4:] if len(key) >= 4 else ""


def load_key(cfg: Config) -> str | None:
    path = _secret_path(cfg)
    if not path.is_file():
        return os.environ.get("VIDEO2AGENT_CLOUD_API_KEY") or os.environ.get("SILICONFLOW_API_KEY") or None
    try:
        raw = path.read_bytes()
        value = _dpapi(raw, protect=False)
        key = value.decode("utf-8").strip()
        return key or None
    except Exception as exc:
        raise Video2AgentError(
            "E_CLOUD_SECRET_STORE",
            "云端 Key 无法解密。",
            "重新在设置页保存 Key；如果换了 Windows 用户，需要重新保存。",
        ) from exc


def save_key(cfg: Config, key: str) -> dict[str, Any]:
    key = (key or "").strip()
    if len(key) < 8 or len(key) > 500 or any(c.isspace() for c in key):
        raise Video2AgentError("E_CLOUD_KEY", "API Key 格式不正确。", "粘贴服务商控制台生成的完整 Key。")
    path = _secret_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = _dpapi(key.encode("utf-8"), protect=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(encrypted)
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)
    return {"ok": True, "configured": True, "last4": _key_last4(key)}


def clear_key(cfg: Config) -> dict[str, Any]:
    path = _secret_path(cfg)
    try:
        path.unlink(missing_ok=True)
        path.with_suffix(".tmp").unlink(missing_ok=True)
    except OSError as exc:
        raise Video2AgentError(
            "E_CLOUD_CLEAR",
            "无法删除已保存的 API Key。",
            "关闭占用该文件的程序后重试，或手动删除 secrets/cloud.bin。",
        ) from exc
    return {"ok": True, "configured": False}


def configured(cfg: Config) -> bool:
    try:
        # A corrupt cloud.json means we cannot know the provider; never upload
        # audio to a guessed endpoint just because a key exists.
        if _read_config(cfg).get("corrupt"):
            return False
        return bool(load_key(cfg))
    except Video2AgentError:
        return False


def ocr_enabled(cfg: Config) -> bool:
    return bool(_read_config(cfg).get("ocr_enabled"))


def set_ocr_enabled(cfg: Config, enabled: bool) -> dict[str, Any]:
    data = _write_config(cfg, {"ocr_enabled": bool(enabled)})
    return {"ok": True, "ocr_enabled": data["ocr_enabled"]}


def asr_enabled(cfg: Config) -> bool:
    return bool(_read_config(cfg).get("asr_enabled", True))


def set_asr_enabled(cfg: Config, enabled: bool) -> dict[str, Any]:
    data = _write_config(cfg, {"asr_enabled": bool(enabled)})
    return {"ok": True, "asr_enabled": data["asr_enabled"]}


def status(cfg: Config) -> dict[str, Any]:
    try:
        key = load_key(cfg)
        key_error = None
    except Video2AgentError as exc:
        key = None
        key_error = exc.as_dict()
    data = _read_config(cfg)
    preset = next((p for p in PROVIDER_PRESETS if p["id"] == data["provider"]), None)
    return {
        "ok": True,
        "provider": data["provider"],
        "provider_label": (preset or {}).get("label") or data["provider"],
        "base_url": data["base_url"],
        "asr_model": data["asr_model"],
        "ocr_model": data["ocr_model"],
        "ocr_enabled": bool(data["ocr_enabled"]),
        "asr_enabled": bool(data.get("asr_enabled", True)),
        "configured": bool(key) and not data.get("corrupt"),
        "source": ("env" if key and not _secret_path(cfg).is_file() else ("file" if key else None)),
        "last4": _key_last4(key) if key else "",
        "invite_url": INVITE_URL,
        "international_url": INTERNATIONAL_URL,
        "models": MODEL_OPTIONS,
        "presets": PROVIDER_PRESETS,
        "default_models": {"asr": DEFAULT_ASR, "ocr": DEFAULT_OCR},
        "key_error": key_error,
        # The settings page must show 读取失败 rather than a guessed provider.
        "corrupt": bool(data.get("corrupt")),
    }


def _cloud_error(response: requests.Response, what: str) -> Video2AgentError:
    code = None
    message = ""
    try:
        payload = response.json()
        code = payload.get("code")
        message = str(payload.get("message") or "")
    except Exception:
        message = response.text[:300]
    if response.status_code == 402 or code == 30001:
        return Video2AgentError(
            "E_CLOUD_BALANCE",
            "云端服务商返回余额不足。",
            "在服务商控制台领取额度/代金券，或换一个可用的 Key。",
        )
    if response.status_code == 401 or code in (401, 10001):
        return Video2AgentError("E_CLOUD_AUTH", "服务商 API Key 无效或已失效。", "在设置页重新保存 Key。")
    if response.status_code == 429:
        return Video2AgentError("E_CLOUD_RATE", "服务商限流。", "稍后再试；不要连续重试付费请求。")
    return Video2AgentError("E_CLOUD_API", f"{what}失败：{message or response.status_code}", "检查服务商控制台和网络。")


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def test(cfg: Config) -> dict[str, Any]:
    key = load_key(cfg)
    if not key:
        raise Video2AgentError("E_CLOUD_NOT_CONFIGURED", "还没有配置云端 API Key。", "在设置页粘贴 Key。")
    data = _read_config(cfg)
    if data.get("corrupt"):
        raise Video2AgentError(
            "E_CLOUD_CONFIG",
            "cloud.json 已损坏，无法确定要把 Key 发往哪个服务商",
            "在设置页重新填写服务商与 Base URL 并保存后再测试。",
        )
    try:
        response = requests.get(data["base_url"] + "/models", headers=_headers(key), timeout=20)
    except requests.RequestException as exc:
        raise Video2AgentError("E_CLOUD_NETWORK", "无法连接云端服务商。", "检查网络后重试。") from exc
    if response.status_code != 200:
        raise _cloud_error(response, "检查连接")
    ids = {str(item.get("id")) for item in (response.json().get("data") or []) if isinstance(item, dict)}
    return {
        "ok": True,
        "models_seen": len(ids),
        "asr_available": data["asr_model"] in ids,
        "ocr_available": data["ocr_model"] in ids,
        "last4": _key_last4(key),
    }


def _ffmpeg() -> str:
    return os.environ.get("FFMPEG_BIN") or "ffmpeg"


def _ffprobe() -> str:
    return os.environ.get("FFPROBE_BIN") or "ffprobe"


def _duration(path: Path) -> float:
    out = subprocess.run(
        [_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=30, **no_window_kwargs(),
    )
    try:
        return max(0.0, float(out.stdout.strip()))
    except ValueError:
        return 0.0


def _chunks(audio_path: Path, seconds: int = 1800) -> list[tuple[Path, float]]:
    total = _duration(audio_path)
    if total <= seconds and audio_path.stat().st_size <= 45 * 1024 * 1024:
        return [(audio_path, 0.0)]
    tmpdir = Path(tempfile.mkdtemp(prefix="vp-cloud-asr-"))
    chunks: list[tuple[Path, float]] = []
    start = 0.0
    index = 0
    try:
        while start < total:
            target = tmpdir / f"chunk-{index}.mp3"
            subprocess.run(
                [_ffmpeg(), "-y", "-loglevel", "error", "-ss", str(start), "-t", str(seconds),
                 "-i", str(audio_path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(target)],
                capture_output=True, timeout=180, **no_window_kwargs(),
            )
            if target.is_file() and target.stat().st_size > 0:
                chunks.append((target, start))
            start += seconds
            index += 1
        expected = max(0, int((total + seconds - 1) // seconds))
        if not chunks or len(chunks) != expected:
            raise Video2AgentError(
                "E_CLOUD_AUDIO",
                f"音频切分不完整（{len(chunks)}/{expected} 段）。",
                "检查磁盘空间和 FFmpeg 后重试。",
            )
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return chunks


def transcribe(cfg: Config, audio_path: str | Path, *, language: str | None = None) -> dict[str, Any]:
    key = load_key(cfg)
    if not key:
        raise Video2AgentError("E_CLOUD_NOT_CONFIGURED", "还没有配置云端 API Key。", "在设置页粘贴 Key。")
    data = _read_config(cfg)
    model = data["asr_model"]
    segments: list[dict[str, Any]] = []
    # Qwen3-ASR rejects verbose_json and returns no segment timestamps. A 120s
    # chunk keeps a citation inside two minutes instead of one 30-minute blob.
    qwen_like = model.lower().startswith("qwen/")
    chunk_list = _chunks(Path(audio_path), seconds=120 if qwen_like else 1800)
    detected_language: str | None = None

    def post(fmt: str) -> requests.Response:
        with chunk.open("rb") as handle:
            try:
                return requests.post(
                    data["base_url"] + "/audio/transcriptions",
                    headers=_headers(key),
                    files={"file": (chunk.name, handle, mime)},
                    data={"model": model, "response_format": fmt},
                    timeout=300,
                )
            except requests.RequestException as exc:
                raise Video2AgentError("E_CLOUD_NETWORK", "云端 ASR 连接失败。", "检查网络后重试。") from exc

    try:
        for chunk, offset in chunk_list:
            mime = "audio/wav" if chunk.suffix.lower() in (".wav", ".wave") else "audio/mpeg"
            response = post("json" if qwen_like else "verbose_json")
            if response.status_code == 400 and not qwen_like:
                # Qwen3-ASR rejects verbose_json; `json` returns text + language +
                # usage.duration, which is enough for one chunk-level segment.
                response = post("json")
            if response.status_code != 200:
                raise _cloud_error(response, "云端转写")
            payload = response.json()
            if payload.get("code") not in (None, 0) or payload.get("error"):
                raise _cloud_error(response, "云端转写")
            detected_language = str(payload.get("language") or "") or detected_language
            for item in payload.get("segments") or []:
                start = float(item.get("start", 0.0)) + offset
                end = float(item.get("end", start)) + offset
                text = str(item.get("text") or "").strip()
                if text:
                    segments.append({"start_ms": int(start * 1000), "end_ms": int(end * 1000), "text": text})
            if not payload.get("segments"):
                text = str(payload.get("text") or "").strip()
                if text:
                    duration = float((payload.get("usage") or {}).get("duration") or payload.get("duration") or 0)
                    if not duration:
                        try:
                            duration = _duration(chunk)
                        except Exception:
                            duration = 0.0
                    segments.append({
                        "start_ms": int(offset * 1000),
                        "end_ms": int((offset + duration) * 1000) if duration else int(offset * 1000),
                        "text": text,
                    })
    finally:
        for chunk, _offset in chunk_list:
            if chunk != Path(audio_path) and chunk.parent.name.startswith("vp-cloud-asr-"):
                shutil.rmtree(chunk.parent, ignore_errors=True)
                break
    if not segments:
        raise Video2AgentError("E_CLOUD_ASR_EMPTY", "云端没有返回可用的转写。", "检查音频是否有人声。")
    return {
        "segments": segments,
        "language": detected_language or language,
        "model": model,
        "usage": {"type": "cloud", "provider": PROVIDER},
    }


def _image_data(path: Path) -> str:
    suffix = path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def ocr(cfg: Config, image_path: str | Path, *, prompt: str = "Free OCR.") -> dict[str, Any]:
    key = load_key(cfg)
    if not key:
        raise Video2AgentError("E_CLOUD_NOT_CONFIGURED", "还没有配置云端 API Key。", "在设置页粘贴 Key。")
    data = _read_config(cfg)
    try:
        response = requests.post(
            data["base_url"] + "/chat/completions",
            headers={**_headers(key), "Content-Type": "application/json"},
            json={
                "model": data["ocr_model"],
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": _image_data(Path(image_path))}},
                        {"type": "text", "text": str(prompt or "Free OCR.")},
                    ],
                }],
                "max_tokens": 2048,
                "temperature": 0,
            },
            timeout=120,
        )
    except requests.RequestException as exc:
        raise Video2AgentError("E_CLOUD_NETWORK", "云端 OCR 连接失败。", "检查网络后重试。") from exc
    if response.status_code != 200:
        raise _cloud_error(response, "云端画面文字")
    payload = response.json()
    if payload.get("code") not in (None, 0) or payload.get("error"):
        raise _cloud_error(response, "云端画面文字")
    content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return {"text": str(content).strip(), "model": data["ocr_model"]}
