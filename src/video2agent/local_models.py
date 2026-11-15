"""Local ASR model management.

Four hardware tiers are recommendations, not a whitelist: any faster-whisper
model ID or local CTranslate2 directory can still be selected under Advanced.
Downloads are explicit user actions.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .config import Config, save_config
from .text import whisper_cache_dir, whisper_cache_state
from .util import Video2AgentError
from .visual import ocr_available

# Conservative, multilingual choices. Speed still depends on actual cores,
# memory and GPU; the CPU names are examples, not hard requirements.
TIERS = [
    {
        "id": "low",
        "label": "入门",
        "model": "base",
        "size": "约 145MB",
        "cpu": "Intel i3-8100 / i5-8250U，AMD Ryzen 3 2200G / 3200G · 4 核 8GB",
        "cpu_short": "4 核 8GB",
        "note": "老办公本/迷你主机；速度优先，适合口播和简单课程，术语准确率一般。",
    },
    {
        "id": "mid",
        "label": "中端",
        "model": "small",
        "size": "约 464MB",
        "cpu": "Intel i5-12400 / i5-1135G7，AMD Ryzen 5 5600 / 5600U · 6–8 核 16GB",
        "cpu_short": "6–8 核 16GB",
        "note": "主流轻薄本/台式机；默认推荐，中文准确率和速度比较平衡。",
    },
    {
        "id": "high",
        "label": "高端",
        "model": "medium",
        "size": "约 1.5GB",
        "cpu": "Intel i7-13700 / i9-12900，AMD Ryzen 7 5800X3D / 7800X3D · 8 核 32GB 或 RTX 3060+",
        "cpu_short": "8 核 / 独显",
        "note": "长视频、课程、会议；有独显会明显更快，CPU 也能跑但更吃内存。",
    },
    {
        "id": "enterprise",
        "label": "企业级",
        "model": "large-v3",
        "size": "约 3GB",
        "cpu": "Intel Xeon W-2400，AMD Threadripper 7960X · 多 GPU / 64GB+",
        "cpu_short": "多 GPU / 64GB+",
        "note": "批量、多语种、高质量归档；建议 GPU，普通笔记本不建议默认选它。",
    },
]


def _clean_model(model: str) -> str:
    value = str(model or "").strip()
    if not value or len(value) > 300 or any(ord(c) < 32 for c in value):
        raise Video2AgentError("E_MODEL_ARGS", "模型名称/路径格式不正确。", "填写模型 ID 或本地 CTranslate2 目录。")
    return value


def status(cfg: Config, model: str | None = None) -> dict[str, Any]:
    selected = _clean_model(model or str(cfg.get("asr_model") or "small"))
    state = whisper_cache_state(selected)
    tier = next((t for t in TIERS if t["model"] == selected), None)
    return {
        "ok": True,
        "asr": {
            "selected": selected,
            "cached": bool(state.get("cached")),
            "bytes": int(state.get("bytes") or 0),
            "path": state.get("path"),
        },
        "tiers": TIERS,
        "tier": tier["id"] if tier else "custom",
        "custom": tier is None,
        "ocr": {
            "available": bool(ocr_available()),
            "engine": "RapidOCR",
            "model": "PP-OCRv4",
            "builtin": not bool(str(cfg.get("ocr_local_config") or "")),
            "selected": "custom" if str(cfg.get("ocr_local_config") or "") else "builtin",
            "config_path": str(cfg.get("ocr_local_config") or ""),
        },
    }


def _ocr_config_from_path(raw: str) -> str:
    path = Path(raw).expanduser()
    if path.is_file() and path.suffix.lower() in (".yaml", ".yml"):
        return str(path.resolve())
    if path.is_dir():
        for name in ("config.yaml", "config.yml"):
            candidate = path / name
            if candidate.is_file():
                return str(candidate.resolve())
    return ""


def _ocr_config_from_huggingface(cfg: Config, repo_id: str) -> str:
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        raise Video2AgentError("E_OCR_MODEL", "huggingface_hub 未安装，无法下载 OCR 模型。", "pip install huggingface_hub") from exc
    try:
        root = Path(snapshot_download(
            repo_id=repo_id,
            allow_patterns=["*.yaml", "*.yml", "*.onnx", "*.txt", "*.json"],
        ))
    except Exception as exc:  # noqa: BLE001
        raise Video2AgentError(
            "E_OCR_MODEL",
            f"无法下载 HuggingFace OCR 模型：{exc}",
            "检查模型 ID/网络；该仓库需要提供 RapidOCR 模型或配置。",
        ) from exc

    onnx = [p for p in root.rglob("*.onnx") if p.is_file()]
    if not onnx:
        for candidate in sorted(root.rglob("config.y*ml")):
            if candidate.is_file():
                return str(candidate.resolve())
        raise Video2AgentError(
            "E_OCR_MODEL",
            "该 HuggingFace 仓库没有 ONNX 模型或 RapidOCR 配置。",
            "使用包含 det/rec ONNX 文件的 RapidOCR 仓库，或本地模型目录。",
        )

    def pick(kind: str) -> Path | None:
        candidates = [p for p in onnx if kind in p.name.lower()]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda p: (
                0 if "pp-ocrv4" in p.name.lower() and "server" not in p.name.lower() else 1,
                0 if "pp-ocrv4" in p.name.lower() else 1,
                len(p.name),
            ),
        )[0]

    det, rec, cls = pick("det"), pick("rec"), pick("cls")
    if not det or not rec:
        raise Video2AgentError(
            "E_OCR_MODEL",
            "HuggingFace 仓库缺少 det/rec ONNX 模型。",
            "使用包含检测和识别 ONNX 的 RapidOCR 模型仓库。",
        )
    try:
        import rapidocr_onnxruntime
        import yaml
    except Exception as exc:  # noqa: BLE001
        raise Video2AgentError("E_OCR_MODEL", "无法生成 RapidOCR 配置。", "检查 PyYAML 和 RapidOCR 安装。") from exc
    base = Path(rapidocr_onnxruntime.__file__).parent / "config.yaml"
    data = yaml.safe_load(base.read_text(encoding="utf-8"))
    data["Det"]["model_path"] = str(det.resolve())
    data["Rec"]["model_path"] = str(rec.resolve())
    if cls:
        data["Cls"]["model_path"] = str(cls.resolve())
    slug = repo_id.replace("/", "__").replace("\\", "__")
    out = cfg.home / "models" / "ocr" / f"{slug}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(out.resolve())


def select_ocr(cfg: Config, config_path: str = "") -> dict[str, Any]:
    """Select built-in RapidOCR, a local config/path, or a HuggingFace repo.

    HuggingFace repos are downloaded as ONNX files and a RapidOCR config is
    generated, so the model ID alone is enough. Repos that ship a config are
    accepted too.
    """
    raw = str(config_path or "").strip()
    if raw:
        resolved = _ocr_config_from_path(raw)
        if not resolved:
            hf_like = (
                "/" in raw and "\\" not in raw and ":" not in raw
                and raw.count("/") == 1 and not raw.startswith(("/", "."))
            )
            if hf_like:
                resolved = _ocr_config_from_huggingface(cfg, raw)
            if not resolved:
                raise Video2AgentError(
                    "E_OCR_MODEL",
                    "需要 HuggingFace 模型 ID、本地 RapidOCR 配置，或包含 config.yaml 的目录。",
                    "例如 SWHL/RapidOCR 这类仓库，或本地 .yaml/.yml 文件。",
                )
        cfg.set("ocr_local_config", resolved)
    else:
        cfg.set("ocr_local_config", None)
    save_config(cfg)
    return status(cfg)


def select(cfg: Config, model: str) -> dict[str, Any]:
    value = _clean_model(model)
    cfg.set("asr_model", value)
    save_config(cfg)
    return status(cfg, value)


def download(cfg: Config, model: str = "") -> dict[str, Any]:
    value = _clean_model(model or str(cfg.get("asr_model") or "small"))
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # noqa: BLE001
        raise Video2AgentError("E_ASR_MISSING", "faster-whisper 未安装。", "pip install faster-whisper") from exc
    try:
        WhisperModel(value, device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001
        raise Video2AgentError("E_MODEL_DOWNLOAD", f"模型下载/加载失败：{exc}", "检查模型 ID、网络和磁盘空间。") from exc
    state = whisper_cache_state(value)
    if not state.get("cached"):
        raise Video2AgentError("E_MODEL_DOWNLOAD", "模型还没有落盘。", "检查网络和磁盘空间后重试。")
    return {
        "ok": True,
        "model": value,
        "cached": True,
        "bytes": state.get("bytes", 0),
        "path": state.get("path"),
    }


def uninstall(cfg: Config, model: str = "") -> dict[str, Any]:
    value = _clean_model(model or str(cfg.get("asr_model") or "small"))
    path = whisper_cache_dir(value)
    if not path.is_dir():
        return {"ok": True, "model": value, "removed": False, **status(cfg, value)}
    # Only remove HuggingFace cache directories. A user-supplied local
    # CTranslate2 directory is theirs; never delete it from Settings.
    raw = Path(str(value)).expanduser()
    # whisper_cache_dir() returns an existing local dir as-is, so raw and path
    # are the same object there; an existing local dir is never cache-managed.
    if raw.is_dir():
        raise Video2AgentError(
            "E_MODEL_UNINSTALL",
            "这是自定义本地模型路径，设置页不会删除它。",
            "如需删除，请手动管理该目录。",
        )
    if path.parent.name != "hub" or not path.name.startswith("models--"):
        raise Video2AgentError(
            "E_MODEL_UNINSTALL",
            "这是自定义本地模型路径，设置页不会删除它。",
            "如需删除，请手动管理该目录。",
        )
    shutil.rmtree(path)
    return {"ok": True, "model": value, "removed": True, **status(cfg, value)}
