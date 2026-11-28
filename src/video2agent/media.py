from __future__ import annotations

import json
import math
import os
import re
import tempfile
import urllib.request
import wave
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from .util import Video2AgentError, ensure_dir, run, which

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None


def _ffmpeg() -> str:
    return os.environ.get("FFMPEG_BIN") or which("ffmpeg") or "ffmpeg"


def _ffprobe() -> str:
    return os.environ.get("FFPROBE_BIN") or which("ffprobe") or "ffprobe"


def _fps(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            a, b = value.split("/", 1)
            return float(a) / float(b) if float(b) else None
        return float(value)
    except Exception:
        return None


def probe(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise Video2AgentError("E_NOT_FOUND", f"Video not found: {p}", "Check the path.")
    res = run([
        _ffprobe(), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(p),
    ], timeout=60, check=True, error_code="E_PROBE")
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise Video2AgentError("E_PROBE", "ffprobe returned invalid JSON", "Check the video file.") from e
    fmt = data.get("format", {}) or {}
    streams = data.get("streams", []) or []
    video_streams = [s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if s.get("codec_type") == "subtitle"]
    v = video_streams[0] if video_streams else {}
    rotation = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rotation = int(float(sd["rotation"]))
            except Exception:
                pass
    if not rotation:
        try:
            rotation = int(float((v.get("tags") or {}).get("rotate", 0)))
        except Exception:
            rotation = 0
    duration = fmt.get("duration") or v.get("duration") or 0
    try:
        duration_ms = int(round(float(duration) * 1000))
    except Exception:
        duration_ms = 0
    tags = {**(fmt.get("tags") or {}), **(v.get("tags") or {})}
    return {
        "path": str(p.resolve()),
        "size": p.stat().st_size,
        "duration_ms": duration_ms,
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": _fps(v.get("avg_frame_rate") or v.get("r_frame_rate")),
        "video_codec": v.get("codec_name"),
        "audio_codec": (audio_streams[0].get("codec_name") if audio_streams else None),
        "has_audio": bool(audio_streams),
        "has_video": bool(video_streams),
        "audio_streams": len(audio_streams),
        "subtitle_streams": len(subtitle_streams),
        "rotation": rotation,
        "title": tags.get("title") or p.stem,
        "tags": tags,
        "format_name": fmt.get("format_name"),
        "bit_rate": fmt.get("bit_rate"),
    }


def extract_audio(video_path: str | Path, out_path: str | Path, *, audio_index: int = 0) -> Path:
    out = Path(out_path)
    ensure_dir(out.parent)
    if out.exists() and out.stat().st_size > 0:
        return out
    res = run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path), "-map", f"0:a:{audio_index}?",
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out),
    ], timeout=1200)
    if not res.ok or not out.exists() or out.stat().st_size == 0:
        raise Video2AgentError("E_AUDIO", "Could not extract audio.", "Check whether the video has an audio track.")
    return out


def extract_audio_windows(
    video_path: str | Path,
    out_path: str | Path,
    windows: list[tuple[int, int]],
    *,
    audio_index: int = 0,
) -> Path:
    """Extract a few short audio windows and concatenate them into one WAV.

    Caption trust checking needs only a handful of seconds of real speech, not the
    whole soundtrack. `windows` is a list of ``(start_ms, duration_ms)``; keeping
    it to two 8s windows makes the check cheap on a one-hour video.
    """
    out = Path(out_path)
    ensure_dir(out.parent)
    use = [(max(0, int(s)), max(1, int(d))) for s, d in windows][:3]
    if not use:
        raise Video2AgentError("E_AUDIO_SAMPLE", "No audio window was requested.", "Pass at least one window.")
    cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    for start_ms, dur_ms in use:
        cmd += ["-ss", f"{start_ms / 1000:.3f}", "-t", f"{dur_ms / 1000:.3f}", "-i", str(video_path)]
    if len(use) == 1:
        filt = "[0:a]anull[a]"
    else:
        joins = "".join(f"[{i}:a]" for i in range(len(use)))
        filt = f"{joins}concat=n={len(use)}:v=0:a=1[a]"
    cmd += [
        "-filter_complex", filt, "-map", "[a]", "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out),
    ]
    res = run(cmd, timeout=180)
    if not res.ok or not out.exists() or out.stat().st_size == 0:
        raise Video2AgentError("E_AUDIO_SAMPLE", "Could not extract a caption-check audio sample.", "Check the video's audio track.")
    return out


def extract_frame(video_path: str | Path, at_ms: int, out_path: str | Path,
                  *, width: int | None = 1280, fmt: str = "jpg", exact: bool = True) -> Path:
    out = Path(out_path)
    ensure_dir(out.parent)
    at_s = max(0.0, at_ms / 1000.0)
    if exact and at_s > 2.0:
        start = at_s - 2.0
        offset = 2.0
        cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-i", str(video_path),
               "-ss", f"{offset:.3f}"]
    else:
        cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at_s:.3f}", "-i", str(video_path)]
    if width and width > 0:
        cmd += ["-vf", f"scale=w='min(iw,{int(width)})':h=-2"]
    cmd += ["-frames:v", "1", "-an"]
    if fmt.lower() in ("jpg", "jpeg"):
        cmd += ["-q:v", "2"]
    cmd += [str(out)]
    res = run(cmd, timeout=120)
    if not res.ok or not out.exists():
        # Fallback: fast seek at target.
        cmd2 = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{at_s:.3f}", "-i", str(video_path), "-frames:v", "1", "-an"]
        if width and width > 0:
            cmd2 += ["-vf", f"scale=w='min(iw,{int(width)})':h=-2"]
        cmd2 += [str(out)]
        res = run(cmd2, timeout=120)
    if not res.ok or not out.exists():
        raise Video2AgentError("E_FRAME", f"Could not extract frame at {at_ms} ms.", "Try a smaller width or check the video.")
    return out


def extract_frames_batch(video_path: str | Path, times_ms: list[int], out_dir: str | Path,
                         *, width: int | None = 1280, fmt: str = "jpg",
                         prefix: str = "batch") -> dict[int, Path]:
    """Extract several frames in one ffmpeg process, exactly like `extract_frame`.

    Nearby frames can share a decoder after one seek. Each output still
    selects the first frame at or after its own offset. Spread-out frames use
    independent seeks so the decoder doesn't have to walk the gaps.
    """
    times = sorted({int(t) for t in times_ms})
    if len(times) < 2 or len(times) > 24:
        return {}
    out_root = ensure_dir(Path(out_dir))
    for old in out_root.glob(f"{prefix}_{times[0]}_*.{fmt}"):
        old.unlink(missing_ok=True)
    files = [out_root / f"{prefix}_{times[0]}_{i:04d}.{fmt}" for i in range(1, len(times) + 1)]
    base = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    modes = (True, False) if 0 <= times[0] and times[-1] - times[0] <= 2500 else (False,)
    for shared in modes:
        seeks = [max(0, t - 2000) for t in (times[:1] if shared else times)]
        cmd = base.copy()
        for seek in seeks:
            cmd += ["-ss", f"{seek / 1000:.3f}", "-i", str(video_path)]
        for index, (t, out_path) in enumerate(zip(times, files)):
            input_index = 0 if shared else index
            cmd += ["-ss", f"{(t - seeks[input_index]) / 1000:.3f}"]
            if width and width > 0:
                cmd += ["-vf", f"scale=w='min(iw,{int(width)})':h=-2"]
            cmd += ["-map", f"{input_index}:v:0", "-frames:v", "1", "-an"]
            if fmt.lower() in ("jpg", "jpeg"):
                cmd += ["-q:v", "2"]
            cmd += [str(out_path)]
        res = run(cmd, timeout=120 + len(times) * 10)
        if res.ok and all(path.exists() and path.stat().st_size for path in files):
            return dict(zip(times, files))
        for path in files:
            path.unlink(missing_ok=True)
    return {}


def scene_times(video_path: str | Path, threshold: float = 0.05) -> list[float]:
    expr = f"select=gt(scene\\,{threshold}),showinfo"
    res = run([
        _ffmpeg(), "-hide_banner", "-i", str(video_path), "-filter:v", expr,
        "-an", "-sn", "-f", "null", "-",
    ], timeout=1800)
    text = (res.stderr or "") + "\n" + (res.stdout or "")
    times = []
    for m in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text):
        try:
            t = float(m.group(1))
            if t > 0.05:
                times.append(t)
        except Exception:
            continue
    return sorted(set(round(t, 3) for t in times))


def speech_profile(path: str | Path, *, max_gaps: int = 4, min_gap_ms: int = 2000) -> dict[str, Any] | None:
    """Speech / no-speech intervals from Silero VAD, no new dependency.

    faster-whisper already ships the Silero ONNX model (1.25 MB) and onnxruntime
    is installed with it, so this reuses that rather than adding a package.
    Returns None when the VAD stack or the audio is unavailable, so the caller
    can fall back to volume-based silence. Measured: 0.7 h audio → 3.6 s.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except Exception:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wav = extract_audio(p, Path(tmp) / "audio.wav")
            with wave.open(str(wav), "rb") as wf:
                rate = wf.getframerate() or 16000
                raw = wf.readframes(wf.getnframes())
    except Exception:
        return None
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if not len(audio):
        return None
    try:
        stamps = get_speech_timestamps(
            audio, VadOptions(min_silence_duration_ms=500), sampling_rate=rate,
        )
    except Exception:
        return None
    total_ms = int(len(audio) / rate * 1000)
    spans = sorted((int(s["start"] / rate * 1000), int(s["end"] / rate * 1000)) for s in stamps)
    if not spans:
        return {"speech_ratio": 0.0, "first_speech_ms": None,
                "no_speech_ms": [[0, total_ms]] if total_ms else []}
    speech_ms = sum(end - start for start, end in spans)
    gaps: list[list[int]] = []
    cursor = 0
    for start, end in spans:
        if start - cursor >= min_gap_ms:
            gaps.append([cursor, start])
        cursor = max(cursor, end)
    if total_ms - cursor >= min_gap_ms:
        gaps.append([cursor, total_ms])
    gaps.sort(key=lambda pair: pair[1] - pair[0], reverse=True)
    return {
        "speech_ratio": round(min(1.0, speech_ms / total_ms), 3) if total_ms else None,
        "first_speech_ms": spans[0][0],
        "no_speech_ms": sorted(gaps[:max_gaps]),
    }


def audio_profile(path: str | Path, *, silence_db: float = -30.0, min_silence_s: float = 0.8,
                  max_gaps: int = 4) -> dict[str, Any]:
    """Compact audio hints for digest: loudness, speech ratio, no-speech gaps.

    Loudness and volume-based silence come from one ffmpeg pass; speech/no-speech
    comes from Silero VAD when faster-whisper is present, and falls back to the
    volume-based silence otherwise (`source` says which). Music with a loud bed
    is not silence, which is why the VAD path matters.

    Output is deliberately small (milliseconds, at most `max_gaps` intervals)
    because it rides along in every digest call. `has_audio: false` means there
    is no track; a missing file is unmeasured, never "silent".
    """
    p = Path(path)
    body: dict[str, Any] = {
        "has_audio": False,
        "mean_dbfs": None,
        "max_dbfs": None,
        "silence_ratio": None,
        "speech_ratio": None,
        "first_speech_ms": None,
        "no_speech_ms": [],
        "source": None,
    }
    if not p.exists():
        return body
    try:
        info = probe(p)
    except Video2AgentError:
        return body
    duration_ms = int(info.get("duration_ms") or 0)
    if not info.get("has_audio"):
        return body
    body["has_audio"] = True
    res = run([
        _ffmpeg(), "-hide_banner", "-nostdin", "-v", "info", "-i", str(p),
        # The null muxer selects video too unless it is disabled. A digest only
        # needs the audio stream for these filters.
        "-vn", "-sn", "-dn",
        "-af", f"silencedetect=noise={silence_db}dB:d={min_silence_s},volumedetect",
        "-f", "null", "-",
    ], timeout=900)
    text = res.stderr or ""
    mean = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", text)
    peak = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", text)
    if mean:
        body["mean_dbfs"] = round(float(mean.group(1)), 1)
    if peak:
        body["max_dbfs"] = round(float(peak.group(1)), 1)
    starts = [float(m.group(1)) for m in re.finditer(r"silence_start:\s*(-?[0-9.]+)", text)]
    ends = [float(m.group(1)) for m in re.finditer(r"silence_end:\s*(-?[0-9.]+)", text)]
    silences: list[list[int]] = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else (duration_ms / 1000.0)
        start_ms = max(0, int(round(start * 1000)))
        end_ms = max(start_ms, int(round(end * 1000)))
        if end_ms - start_ms >= int(min_silence_s * 1000):
            silences.append([start_ms, end_ms])
    if duration_ms:
        # Scanned and found nothing: 0.0, not null. null means "not measured".
        body["silence_ratio"] = round(min(1.0, sum(e - s for s, e in silences) / duration_ms), 3)
    speech = speech_profile(p, max_gaps=max_gaps)
    if speech is not None:
        body.update({
            "speech_ratio": speech["speech_ratio"],
            "first_speech_ms": speech["first_speech_ms"],
            "no_speech_ms": speech["no_speech_ms"],
            "source": "silero",
        })
    else:
        longest = sorted(silences, key=lambda pair: pair[1] - pair[0], reverse=True)[:max_gaps]
        body["no_speech_ms"] = sorted(longest)
        body["source"] = "silence"
    return body


def extract_embedded_subtitle(video_path: str | Path, out_path: str | Path, stream_index: int = 0) -> Path | None:
    out = Path(out_path)
    ensure_dir(out.parent)
    res = run([
        _ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path),
        "-map", f"0:s:{stream_index}", "-c:s", "webvtt", str(out),
    ], timeout=120)
    if res.ok and out.exists() and out.stat().st_size > 0:
        return out
    return None


def download_cover(url: str, out_path: str | Path, *, referer: str = "https://www.bilibili.com/",
                   allow_private: bool = False) -> Path | None:
    """Fetch a cover image from a public http(s) URL.

    The URL comes from search results, so it is untrusted: `file://` would read a local
    file, and 127.0.0.1 / 169.254.169.254 would reach the loopback or a metadata
    service.
    """
    from .net import assert_public_url, safe_urlopen

    out = Path(out_path)
    ensure_dir(out.parent)
    try:
        assert_public_url(url, allow_private=allow_private)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Referer": referer,
        })
        with safe_urlopen(req, timeout=20, allow_private=allow_private) as resp:
            data = resp.read(8 * 1024 * 1024)
        out.write_bytes(data)
        with Image.open(out) as im:
            im = im.convert("RGB")
            im.save(out, "JPEG", quality=86)
        return out
    except Exception:
        return None


def contact_sheet(paths: list[str | Path], out_path: str | Path, *, cols: int = 3,
                  thumb_width: int = 480, labels: bool = True) -> Path | None:
    paths = [Path(p) for p in paths if Path(p).exists()]
    if not paths:
        return None
    out = Path(out_path)
    ensure_dir(out.parent)
    thumb_h = int(thumb_width * 9 / 16)
    rows = math.ceil(len(paths) / cols)
    pad = 12
    label_h = 22 if labels else 0
    W = cols * thumb_width + (cols + 1) * pad
    H = rows * (thumb_h + label_h) + (rows + 1) * pad
    canvas = Image.new("RGB", (W, H), (245, 245, 242))
    draw = ImageDraw.Draw(canvas)
    for i, p in enumerate(paths):
        r, c = divmod(i, cols)
        x = pad + c * (thumb_width + pad)
        y = pad + r * (thumb_h + label_h + pad)
        try:
            with Image.open(p) as im:
                tile = ImageOps.fit(im.convert("RGB"), (thumb_width, thumb_h), method=Image.Resampling.LANCZOS)
                canvas.paste(tile, (x, y))
            if labels:
                draw.rectangle([x, y + thumb_h, x + thumb_width, y + thumb_h + label_h], fill=(32, 32, 30))
                draw.text((x + 8, y + thumb_h + 4), f"{i + 1:02d}", fill=(255, 255, 255))
        except Exception:
            continue
    canvas.save(out, "JPEG", quality=88)
    return out


def _edge_density(gray: np.ndarray) -> float:
    if cv2 is not None:
        edges = cv2.Canny(gray, 80, 160)
        return float(np.count_nonzero(edges) / edges.size)
    gy, gx = np.gradient(gray.astype(np.float32))
    mag = np.abs(gx) + np.abs(gy)
    return float(np.count_nonzero(mag > 32) / mag.size)


def _line_score(gray: np.ndarray) -> float:
    if cv2 is None:
        return 0.0
    edges = cv2.Canny(gray, 60, 160)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60, minLineLength=max(40, gray.shape[1] // 8), maxLineGap=8)
    if lines is None:
        return 0.0
    long = 0
    for line in lines[:200]:
        # OpenCV 4.x returns (N, 1, 4) and 5.x returns (N, 4); flatten before
        # unpacking so a fresh install (which gets opencv 5) does not crash the
        # whole ingest on the first frame.
        pts = np.asarray(line, dtype=np.float64).reshape(-1)
        if pts.size < 4:
            continue
        x1, y1, x2, y2 = pts[:4]
        if abs(x2 - x1) > gray.shape[1] * 0.35 or abs(y2 - y1) > gray.shape[0] * 0.35:
            long += 1
    return min(1.0, long / 40.0)


def _sharpness(gray: np.ndarray) -> float:
    """Smooth 0-1 sharpness from Laplacian variance.

    The old `min(1, var/900)` pinned 62-71% of real frames at exactly 1.0 (measured:
    var p50 = 1111, p90 = 3216), which made the feature useless downstream. An
    exponential saturates just as monotonically but keeps ordering: p50 -> 0.52,
    p90 -> 0.88 on the same 120 frames.
    """
    if cv2 is not None:
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        var = float(np.var(lap))
        return float(1.0 - math.exp(-var / 1500.0))
    gy, gx = np.gradient(gray.astype(np.float32))
    var = float(np.var(gx) + np.var(gy))
    return float(1.0 - math.exp(-var / 200.0))


def _phash(gray: np.ndarray) -> str:
    """Real perceptual hash (DCT), not an 8x8 average.

    The old version compared an 8x8 thumbnail against its own mean, which is an
    average hash: it only survives downscaling, not brightness/geometry changes, and
    it was never read anyway. This is the classic pHash: 32x32 DCT, keep the low
    8x8 block, threshold at its median. Same 16-hex output, now comparable with
    hamming distance (see hamming_distance).
    """
    small = gray if gray.shape == (32, 32) else np.asarray(
        Image.fromarray(gray).resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32
    )
    small = small.astype(np.float32)
    n = 32
    k = np.arange(n)
    dct = np.cos(np.pi * (2 * k[:, None] + 1) * k[None, :] / (2 * n)) * np.sqrt(2.0 / n)
    dct[0, :] *= np.sqrt(1.0 / 2.0)
    low = dct @ small @ dct.T
    block = low[:8, :8].flatten().copy()
    median = float(np.median(block[1:]))  # drop DC: it encodes average brightness
    value = 0
    for b in block:
        value = (value << 1) | int(b > median)
    return f"{value:016x}"


def hamming_distance(a: str, b: str) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def frame_features(path: str | Path, prev_gray: np.ndarray | None = None) -> tuple[dict[str, Any], np.ndarray]:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        gray = np.asarray(im.convert("L").resize((160, 90), Image.Resampling.BILINEAR), dtype=np.uint8)
    if prev_gray is not None and prev_gray.shape == gray.shape:
        motion = float(np.mean(np.abs(gray.astype(np.int16) - prev_gray.astype(np.int16))) / 255.0)
    else:
        motion = 0.0
    color_entropy = 0.0
    with Image.open(path) as im:
        hist = im.convert("RGB").histogram()
    total = sum(hist) or 1
    for i in range(0, len(hist), 256):
        channel = hist[i:i + 256]
        probs = [c / total for c in channel if c]
        ent = -sum(p * math.log(p + 1e-12, 2) for p in probs) / 8.0
        color_entropy += ent / 3.0
    return {
        "width": w,
        "height": h,
        "motion": round(motion, 4),
        "edge_density": round(_edge_density(gray), 4),
        "line_score": round(_line_score(gray), 4),
        "sharpness": round(_sharpness(gray), 4),
        "color_entropy": round(color_entropy, 4),
        "phash": _phash(gray),
        # Not measured yet, and deliberately not 0.0: "we never read this frame" and
        # "this frame has no text" are different facts, and the label scorer used to
        # treat the former as the latter (every slide became `animation`).
        "text_coverage": None,
        "ocr_status": "unmeasured",
    }, gray
