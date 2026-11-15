"""Lightweight perception map (VPM) for one video.

Retrieval answers "where is this text / this moment". Perception answers "when,
where and how does the picture change" as numbers the host model can act on. The
thresholds here were measured on synthetic fixtures and a real 161 s 1080p clip
(see docs/PERCEPTION.md); the failure modes are documented there as well.

Nothing in this module claims semantics: it measures pixels and leaves the
meaning to the model. Every returned number carries its sampling and resolution
limits in coverage, because "static at 160x90 / 10 fps" is not "nothing moved".
"""

from __future__ import annotations

import math
import shutil
import subprocess
from typing import Any, Iterator

import numpy as np

from .db import Database
from .util import Video2AgentError, install_hint, no_window_kwargs, not_ready_error

DECODE_W, DECODE_H = 160, 90
ROWS, COLS = 5, 8
THUMB_W, THUMB_H = 40, 22
CHUNK_FRAMES = 120
MAX_FRAMES = 20000          # hard decode cap; coverage.capped says when it hit
MIN_CHANGE_PX = 2.0         # smallest source detail the grid can see, scaled by width

CUT_ABS = 0.35
CUT_COLOR_ABS = 0.15        # a cut between two flat scenes is colour, not structure
CUT_SUPPORT = 0.5
CUT_SPIKE = 0.25
CUT_MERGE_MS = 300
MOMENT_ABS = 0.08          # one changed cell in a still moment can be this small
MOMENT_RATIO = 3.0
MOMENT_NMS_MS = 600
LOOP_MIN_SIM = 0.9
LOOP_MIN_PROMINENCE = 0.15  # a loop must beat its own median lag similarity
BUSY_MOTION = 0.30          # a shot this active is described by motion, not moments
FLAT_STD = 8.0              # a cell this flat has no structure to correlate
FLICKER_RATIO = 5.0           # raw/structural; measured 12.7-290 on flicker fixtures
FLICKER_MIN_RAW = 0.05
FLAT_FRAME_STD = 2.0         # a flat frame has no structure: NCC there is undefined

DEFAULT_FPS_SHORT = 12
DEFAULT_FPS_MID = 8
DEFAULT_FPS_LONG = 4

SHOT_CAP = 20               # longest list in the VPM; a 2-min clip must stay ~1k tokens
SHOT_MERGE_MIN_MS = 1
LONG_FULL_MAX_MS = 10 * 60 * 1000   # beyond this a whole-video scan is slow and coarse


def _require_tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise Video2AgentError(
            "E_FFMPEG",
            f"{name} 未安装或不在 PATH 上（视频探测/抽帧需要它）。",
            install_hint(name),
        )
    return found


def _read_exact(stream: Any, size: int) -> bytes:
    """Read up to size bytes, looping: a pipe read may return short."""
    chunks = []
    got = 0
    while got < size:
        piece = stream.read(size - got)
        if not piece:
            break
        chunks.append(piece)
        got += len(piece)
    return b"".join(chunks)


def _decode_frames(path: str, fps: int, start_s: float, dur_s: float,
                   max_frames: int) -> Iterator[np.ndarray]:
    ff = _require_tool("ffmpeg")
    frame_bytes = DECODE_W * DECODE_H * 3
    cmd = [
        ff, "-v", "error",
        # -ss before -i seeks instead of decoding the prefix; -t bounds the window.
        "-ss", f"{max(0.0, start_s):.3f}",
        "-i", path,
        "-t", f"{max(0.001, dur_s):.3f}",
        "-vf", f"fps={fps},scale={DECODE_W}:{DECODE_H}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    # stderr is never read here: PIPE + a noisy/corrupt input fills the 64KB pipe
    # and blocks ffmpeg forever. Discard it instead.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=frame_bytes * CHUNK_FRAMES, **no_window_kwargs())
    emitted = 0
    try:
        while emitted < max_frames:
            buf = _read_exact(proc.stdout, frame_bytes * CHUNK_FRAMES)
            if not buf:
                break
            usable = len(buf) // frame_bytes
            if usable == 0:
                break
            block = np.frombuffer(buf[:usable * frame_bytes], dtype=np.uint8)
            block = block.reshape(usable, DECODE_H, DECODE_W, 3)
            for i in range(usable):
                yield block[i]
                emitted += 1
                if emitted >= max_frames:
                    return
    finally:
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except Exception:
                pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _thumb(luma: np.ndarray) -> np.ndarray:
    h, w = luma.shape
    bh, bw = h // THUMB_H, w // THUMB_W
    if bh < 1 or bw < 1:
        return np.zeros((THUMB_H, THUMB_W), dtype=np.uint8)
    crop = luma[:THUMB_H * bh, :THUMB_W * bw]
    small = crop.reshape(THUMB_H, bh, THUMB_W, bw).mean(axis=(1, 3))
    return small.astype(np.uint8)


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32) - float(a.mean())
    b = b.astype(np.float32) - float(b.mean())
    den = float(math.sqrt(float((a * a).sum())) * math.sqrt(float((b * b).sum()))) + 1e-6
    return float((a * b).sum() / den)

def _cell_stats(prev_rgb: np.ndarray, rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-cell structural change (1-NCC on luma) and colour change (mean |dRGB|)."""
    ch, cw = DECODE_H // ROWS, DECODE_W // COLS
    # Frames are (H, W, 3): the row bound is axis 0 and the column bound is axis 1.
    pa = prev_rgb[:ROWS * ch, :COLS * cw, :].reshape(ROWS, ch, COLS, cw, 3)
    pb = rgb[:ROWS * ch, :COLS * cw, :].reshape(ROWS, ch, COLS, cw, 3)
    color = np.abs(pb.mean(axis=(1, 3)) - pa.mean(axis=(1, 3))).mean(axis=2) / 255.0
    la = pa.mean(axis=4)
    lb = pb.mean(axis=4)
    lam = la - la.mean(axis=(1, 3), keepdims=True)
    lbm = lb - lb.mean(axis=(1, 3), keepdims=True)
    sa = np.sqrt((lam * lam).sum(axis=(1, 3)))
    sb = np.sqrt((lbm * lbm).sum(axis=(1, 3)))
    ncc = (lam * lbm).sum(axis=(1, 3)) / (sa * sb + 1e-6)
    struct = 1.0 - ncc
    # A cell with no structure in either frame is "unmeasured", not "unchanged".
    struct[(sa < FLAT_STD) & (sb < FLAT_STD)] = 0.0
    return struct.astype(np.float32), color.astype(np.float32)


def _cut_events(g: np.ndarray, support: np.ndarray, fps: int,
                color: np.ndarray, color_support: np.ndarray) -> list[dict[str, Any]]:
    """Hard cuts: an absolute jump with wide spatial support that stands out from
    its own +-1 s baseline. Structure covers normal cuts; the colour channel
    covers a cut between two flat scenes (a theme switch, a solid title card),
    where luma NCC is undefined. A pan is a sustained drop, not a spike, and
    flicker is periodic, so neither passes the spike test."""
    signal = np.maximum(g, color * 2.0)
    cuts: list[dict[str, Any]] = []
    n = len(g)
    for i in range(3, n):
        structural = g[i] >= CUT_ABS and support[i] >= CUT_SUPPORT
        chromatic = color[i] >= CUT_COLOR_ABS and color_support[i] >= CUT_SUPPORT
        if not (structural or chromatic):
            continue
        lo, hi = max(0, i - fps), min(n, i + fps + 1)
        win = np.concatenate([signal[lo:max(0, i - 2)], signal[min(n, i + 2):hi]])
        base = float(np.median(win)) if len(win) else 0.0
        if float(signal[i] - base) < CUT_SPIKE:
            continue
        t_ms = int(round((i + 1) * 1000 / fps))
        if cuts and t_ms - cuts[-1]["t_ms"] < CUT_MERGE_MS:
            if float(signal[i]) > cuts[-1]["g"]:
                cuts[-1] = {"t_ms": t_ms, "g": round(float(signal[i]), 3),
                            "support": round(float(max(support[i], color_support[i])), 2)}
            continue
        cuts.append({"t_ms": t_ms, "g": round(float(signal[i]), 3),
                     "support": round(float(max(support[i], color_support[i])), 2)})
    return cuts


def _shot_rows(bounds: list[int], score: np.ndarray, start_ms: int, fps: int) -> list[dict[str, Any]]:
    shots: list[dict[str, Any]] = []
    for idx in range(len(bounds) - 1):
        a, b = bounds[idx], bounds[idx + 1]
        i0 = int(round((a - start_ms) * fps / 1000.0))
        i1 = max(i0 + 1, int(round((b - start_ms) * fps / 1000.0)))
        seg = score[max(0, i0):min(len(score), i1)] if i1 > i0 else np.array([0.0], dtype=np.float32)
        shots.append({
            "id": f"s{idx}",
            "start_ms": int(a),
            "end_ms": int(b),
            "motion": round(float(seg.mean()), 2) if len(seg) else 0.0,
            "peak_ms": int(start_ms + (max(0, i0) + int(seg.argmax())) * 1000 / fps) if len(seg) else int(a),
            "_baseline": float(np.median(seg)) if len(seg) else 0.0,
        })
    return shots


def _moment_events(score: np.ndarray, cell_stack: np.ndarray, color_stack: np.ndarray,
                   fps: int, shots: list[dict[str, Any]],
                   cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank changes relative to their own shot: constant motion is not an event,
    one changed cell in a still shot is. Temporal NMS keeps one per 0.6 s."""
    accepted: list[int] = []
    picked: list[dict[str, Any]] = []
    for i in np.argsort(-score):
        t_ms = int(round((i + 1) * 1000 / fps))
        if float(score[i]) < MOMENT_ABS:
            break
        shot = next((s for s in shots if s["start_ms"] <= t_ms < s["end_ms"]), None)
        if shot is None:
            continue
        # A shot in continuous motion is described by its motion field; listing
        # one "moment" per cell crossing is noise, not a decision aid.
        if float(shot["motion"]) >= BUSY_MOTION:
            continue
        # Compare with the local neighbourhood, not the whole shot: a button that
        # changes while a loader runs elsewhere must still stand out from its own
        # +-1 s, while constant motion has no local peak. A shot-wide median hid
        # exactly that case on a real recording (0.18 against a 0.22 bar).
        lo, hi = max(0, i - fps), min(len(score), i + fps + 1)
        window = np.concatenate([score[lo:max(0, i - 2)], score[min(len(score), i + 3):hi]])
        local = float(np.median(window)) if len(window) else 0.0
        if float(score[i]) < MOMENT_RATIO * max(local, 0.02):
            continue
        if any(abs(t_ms - c["t_ms"]) < 400 for c in cuts):
            continue
        if any(abs(t_ms - other) < MOMENT_NMS_MS for other in accepted):
            continue
        accepted.append(t_ms)
        r, c = np.unravel_index(int(np.argmax(cell_stack[i])), (ROWS, COLS))
        after = score[i + 1:i + fps]
        settles = bool(len(after) and float(np.median(after)) < float(score[i]) * 0.5)
        color_dominant = float(color_stack[i].max()) * 3.0 > float(score[i]) * 0.9
        kind = "color" if color_dominant else ("appear" if settles else "motion")
        # A burst has a start and a peak; "when did it start" is not the peak.
        threshold = max(MOMENT_ABS, 2.0 * max(local, 0.02))
        onset = i
        floor_index = max(0, i - int(0.8 * fps))
        while onset > floor_index and float(score[onset - 1]) >= threshold:
            onset -= 1
        picked.append({"t_ms": t_ms, "onset_ms": int(round((onset + 1) * 1000 / fps)),
                       "kind": kind, "score": round(float(score[i]), 2),
                       "cell": [int(r), int(c)], "settles": settles})
        if len(picked) >= 12:
            break
    picked.sort(key=lambda m: m["t_ms"])
    return picked


def _duplicate_runs(g: np.ndarray) -> tuple[list[int], int]:
    runs: list[int] = []
    cur = 0
    pairs = 0
    for value in g:
        if float(value) < 1e-4:
            cur += 1
            pairs += 1
        elif cur:
            runs.append(cur + 1)
            cur = 0
    if cur:
        runs.append(cur + 1)
    return runs[:8], pairs


def _media_duration(path: str) -> int:
    ff = shutil.which("ffprobe")
    if not ff:
        return 0
    out = subprocess.run(
        [ff, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, **no_window_kwargs(),
    ).stdout.strip()
    try:
        return int(float(out) * 1000)
    except ValueError:
        return 0


def _pts_stats(path: str) -> dict[str, Any] | None:
    ff = shutil.which("ffprobe")
    if not ff:
        return None
    # packet timestamps, not frame timestamps: ffprobe decodes every frame for
    # frame=pts_time (measured 21.8 s on a 161 s 60 fps clip), while packets are
    # demux-only and give the same values in 0.1 s.
    out = subprocess.run(
        [ff, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", path],
        capture_output=True, text=True, **no_window_kwargs(),
    ).stdout
    vals: list[float] = []
    for line in out.splitlines():
        token = line.strip().strip(",")
        if not token or token.upper() == "N/A":
            continue
        try:
            vals.append(float(token))
        except ValueError:
            continue
    if len(vals) < 2:
        return None
    deltas = np.diff(sorted(vals)) * 1000.0
    med = float(np.median(deltas))
    return {
        "median_ms": round(med, 1),
        "p95_ms": round(float(np.percentile(deltas, 95)), 1),
        "max_ms": round(float(deltas.max()), 1),
        "gaps": int((deltas > 2 * med).sum()),
    }

def _probe(path: str) -> dict[str, Any]:
    ff = shutil.which("ffprobe")
    if not ff:
        return {}
    import json as _json
    out = subprocess.run(
        [ff, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate:format=duration",
         "-of", "json", path],
        capture_output=True, text=True, **no_window_kwargs(),
    ).stdout
    try:
        data = _json.loads(out)
    except ValueError:
        return {}
    streams = data.get("streams") or [{}]
    stream = streams[0]
    num, _, den = str(stream.get("avg_frame_rate") or "0/1").partition("/")
    try:
        nominal = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        nominal = 0.0
    try:
        duration_ms = int(float((data.get("format") or {}).get("duration") or 0) * 1000)
    except ValueError:
        duration_ms = 0
    return {"width": int(stream.get("width") or 0), "height": int(stream.get("height") or 0),
            "fps": round(nominal, 2), "duration_ms": duration_ms}


def _flicker(luma: np.ndarray, fps: int, raw: np.ndarray,
             structural: np.ndarray) -> dict[str, Any]:
    ratio = float(np.mean(raw) / (np.mean(structural) + 1e-6))
    peak = 0.0
    if len(luma) > 8 and float(np.std(luma)) > 2.0:
        spec = np.abs(np.fft.rfft(luma - luma.mean()))
        freqs = np.fft.rfftfreq(len(luma), 1.0 / fps)
        spec[0] = 0.0
        band = (freqs >= 3.0) & (freqs <= max(3.0, min(15.0, fps / 2.0)))
        if band.any():
            peak = float(freqs[band][int(np.argmax(spec[band]))])
    kind = ("brightness" if ratio >= FLICKER_RATIO and peak >= 3.0
            and float(np.mean(raw)) >= FLICKER_MIN_RAW else None)
    return {"hz": round(peak, 2), "ratio": round(ratio, 1), "kind": kind}


def _loop(thumbs: list[np.ndarray], fps: int,
          shots: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Loop as appearance repetition, not energy autocorrelation: a sine motion
    repeats at half its period in energy, which is a known false period."""
    best: dict[str, Any] | None = None
    for shot in shots:
        i0 = max(0, int(round(shot["start_ms"] * fps / 1000.0)))
        i1 = min(len(thumbs), int(round(shot["end_ms"] * fps / 1000.0)))
        n = i1 - i0
        if n < max(int(1.5 * fps), 8):
            continue
        if float(shot.get("motion") or 0.0) < 0.02:
            continue
        min_lag = max(int(0.4 * fps), 4)
        max_lag = n // 2
        if max_lag <= min_lag:
            continue
        lag_sims: list[tuple[int, float]] = []
        for lag in range(min_lag, max_lag + 1):
            starts = range(i0, max(i0 + 1, i1 - lag), max(1, (n - lag) // 12))
            sims = [_ncc(thumbs[s], thumbs[s + lag]) for s in starts]
            if not sims:
                continue
            lag_sims.append((lag, float(np.mean(sims))))
        if not lag_sims:
            continue
        # A still-ish shot matches at every lag; a real loop is a *peak* over
        # its own lag spectrum, not just a high similarity somewhere.
        spectrum = float(np.median([sim for _, sim in lag_sims]))
        for lag, sim in lag_sims:
            if sim < LOOP_MIN_SIM or (sim - spectrum) < LOOP_MIN_PROMINENCE:
                continue
            cycles = (n - lag) / lag
            if cycles < 2:
                continue
            if best is None or sim > best["sim"]:
                half = lag // 2
                half_sim = 0.0
                if half >= min_lag:
                    half_starts = range(i0, max(i0 + 1, i1 - half), max(1, (n - half) // 8))
                    half_sims = [_ncc(thumbs[s], thumbs[s + half]) for s in half_starts]
                    half_sim = float(np.mean(half_sims)) if half_sims else 0.0
                best = {"found": True,
                        "period_ms": int(round(lag * 1000 / fps)), "sim": round(sim, 3),
                        "cycles": round(cycles, 1),
                        "half_period_sim": round(half_sim, 3)}
    # Never a bare null: "no loop" and "not measurable here" are different facts.
    return best if best else {"found": False, "reason": "not_detected"}


def _compact_shots(shots: list[dict[str, Any]], cap: int = SHOT_CAP) -> tuple[list[dict[str, Any]], int]:
    """Keep the VPM token budget bounded: merge adjacent shots until the list
    fits, preserving the covered timeline. Returns (rows, original_count)."""
    original = len(shots)
    rows = list(shots)
    while len(rows) > cap:
        merged: list[dict[str, Any]] = []
        for i in range(0, len(rows), 2):
            if i + 1 >= len(rows):
                merged.append(rows[i])
                continue
            a, b = rows[i], rows[i + 1]
            da = max(1, a["end_ms"] - a["start_ms"])
            db = max(1, b["end_ms"] - b["start_ms"])
            merged.append({
                "id": a["id"],
                "start_ms": a["start_ms"],
                "end_ms": b["end_ms"],
                "motion": round((a["motion"] * da + b["motion"] * db) / (da + db), 2),
                "peak_ms": a["peak_ms"] if a["motion"] >= b["motion"] else b["peak_ms"],
            })
        rows = merged
    return rows, original


def _require_window(duration_ms: int, explicit: bool) -> None:
    if explicit or duration_ms <= LONG_FULL_MAX_MS:
        return
    raise Video2AgentError(
        "E_WINDOW_REQUIRED",
        f"这条视频 {duration_ms // 60000} 分钟：整段扫描解码很慢，4fps 的结论也很粗。",
        "先用 search / transcript 找到时间点，再 perceive --start/--end；"
        "或显式给 --start 0 --end <媒体时长> 表示整段扫描。",
    )


def _perceive_media(path: str, *, start_ms: int = 0, end_ms: int | None = None,
                    fps: int | None = None,
                    max_frames: int = MAX_FRAMES,
                    brief: bool = False) -> dict[str, Any]:
    probe = _probe(path)
    duration_ms = int(end_ms or probe.get("duration_ms") or 0) - int(start_ms or 0)
    if duration_ms <= 0:
        raise Video2AgentError(
            "E_OUT_OF_RANGE",
            f"窗口为空：start={start_ms}ms，媒体时长未知或已结束。",
            "先运行 video2agent overview 确认时长，再让 start < end。",
        )
    if fps is None:
        fps = (DEFAULT_FPS_SHORT if duration_ms <= 120_000
               else DEFAULT_FPS_MID if duration_ms <= 600_000 else DEFAULT_FPS_LONG)
    fps = max(1, min(30, int(fps)))

    g: list[float] = []
    support: list[float] = []
    color_frame: list[float] = []
    color_support: list[float] = []
    score: list[float] = []
    raw: list[float] = []
    luma_mean: list[float] = []
    thumbs: list[np.ndarray] = []
    cell_sum = np.zeros((ROWS, COLS), dtype=np.float64)
    cell_sq = np.zeros((ROWS, COLS), dtype=np.float64)
    cell_stack: list[np.ndarray] = []
    color_stack: list[np.ndarray] = []
    prev_rgb: np.ndarray | None = None
    frames = 0
    capped = False
    ch, cw = DECODE_H // ROWS, DECODE_W // COLS
    for frame in _decode_frames(path, fps, start_ms / 1000.0, duration_ms / 1000.0, max_frames):
        rgb = frame.astype(np.float32)
        luma = rgb.mean(axis=2)
        luma_mean.append(float(luma.mean()))
        thumbs.append(_thumb(luma))
        cells = luma[:ROWS * ch, :COLS * cw].reshape(ROWS, ch, COLS, cw).mean(axis=(1, 3))
        cell_sum += cells
        cell_sq += cells * cells
        frames += 1
        if prev_rgb is not None:
            struct, color = _cell_stats(prev_rgb, rgb)
            combined = np.maximum(struct, color * 3.0)
            prev_luma = prev_rgb.mean(axis=2)
            # Two flat frames have no structure to compare: NCC is undefined and
            # returns 0, which would read as "totally different". That made every
            # frame after a flat-to-flat cut look like another cut.
            if float(prev_luma.std()) < FLAT_FRAME_STD and float(luma.std()) < FLAT_FRAME_STD:
                g.append(0.0)
            else:
                g.append(1.0 - _ncc(prev_luma, luma))
            support.append(float((struct > 0.5).mean()))
            color_delta = float(np.abs(rgb - prev_rgb).mean() / 255.0)
            color_frame.append(color_delta)
            color_support.append(float((color > 0.08).mean()))
            score.append(float(combined.max()))
            raw.append(color_delta)
            cell_stack.append(combined)
            color_stack.append(color)
        prev_rgb = rgb
        if frames >= max_frames:
            capped = True
            break
    if frames < 2 or not g:
        raise Video2AgentError(
            "E_DECODE",
            "没有解出可分析的帧。",
            "确认视频能播放（ffprobe 可读），或换一个时间窗口再试。",
        )

    g_arr = np.asarray(g, dtype=np.float32)
    sup_arr = np.asarray(support, dtype=np.float32)
    score_arr = np.asarray(score, dtype=np.float32)
    raw_arr = np.asarray(raw, dtype=np.float32)
    cell_arr = np.stack(cell_stack)
    color_arr = np.stack(color_stack)

    cuts = _cut_events(g_arr, sup_arr, fps,
                        np.asarray(color_frame, dtype=np.float32),
                        np.asarray(color_support, dtype=np.float32))
    bounds = [int(start_ms)]
    bounds.extend(c["t_ms"] for c in cuts)
    bounds.append(int(start_ms + frames * 1000 / fps))
    shots = _shot_rows(bounds, score_arr, int(start_ms), fps)
    moments = _moment_events(score_arr, cell_arr, color_arr, fps, shots, cuts)
    for shot in shots:
        shot.pop("_baseline", None)

    cell_var = np.maximum(0.0, cell_sq / frames - (cell_sum / frames) ** 2)
    cell_std = np.sqrt(cell_var)
    static_cells = int((cell_std < 2.0).sum())
    active_cells = int(ROWS * COLS - static_cells)
    active_pos = np.argwhere(cell_std >= 2.0)
    bbox = None
    if len(active_pos):
        r0, c0 = active_pos.min(axis=0)
        r1, c1 = active_pos.max(axis=0)
        bbox = [int(r0), int(c0), int(r1), int(c1)]

    dup_runs, dup_pairs = _duplicate_runs(g_arr)
    warnings: list[dict[str, Any]] = []
    if capped:
        warnings.append({"code": "DECODE_CAPPED",
                         "message": f"只分析了前 {frames} 帧；结果不代表整段窗口。"})
    if dup_pairs == len(g_arr):
        warnings.append({"code": "CONTENT_STATIC",
                         "message": "所有相邻帧都完全相同：这是静止画面，不是录制重复帧。"})
    if active_cells == 0:
        warnings.append({"code": "NO_CHANGE",
                         "message": "该窗口内没有超过解码噪声的画面变化。"})

    compact_shots, shot_count = _compact_shots(shots)
    cut_times = [int(c["t_ms"]) for c in cuts]
    loop = _loop(thumbs, fps, shots)
    window_end = int(start_ms + frames * 1000 / fps)
    payload: dict[str, Any] = {
        "ok": True,
        "vpm": 1,
        "video_id": None,
        "duration_ms": window_end - int(start_ms),
        "window": {"start_ms": int(start_ms), "end_ms": window_end},
        "media": {"w": int(probe.get("width") or 0), "h": int(probe.get("height") or 0),
                  "fps_nominal": float(probe.get("fps") or 0),
                  "decode_w": DECODE_W, "decode_h": DECODE_H},
        "sampling": {"fps": fps, "frames": frames, "grid": [ROWS, COLS],
                     "min_change_px": round(int(probe.get("width") or DECODE_W) / DECODE_W * MIN_CHANGE_PX, 1)},
        "coverage": {"flicker_max_hz": round(fps / 2.0, 2), "cuts": "hard",
                     "camera": "not measured", "capped": capped},
        "shots": compact_shots,
        "shot_count": shot_count,
        "shots_merged": shot_count > len(compact_shots),
        "moments": moments,
        "regions": {"static": static_cells, "active": active_cells,
                    "of": ROWS * COLS, "bbox": bbox},
        "rhythm": {"shots": len(shots),
                   "median_shot_ms": int(np.median([s["end_ms"] - s["start_ms"] for s in shots])) if shots else 0,
                   "loop": loop},
        "capture": {"pts": _pts_stats(path), "dup_pairs": dup_pairs,
                    "frozen_runs": dup_runs,
                    "flicker": _flicker(np.asarray(luma_mean, dtype=np.float32), fps,
                                        raw_arr, g_arr)},
        "warnings": warnings,
    }
    if shot_count > len(compact_shots):
        # The row budget merged shots; the merged rows are still valid boundaries
        # but not the real cut list. Expose it once, capped, so a fast-cut video
        # does not look like it has 20 cuts when it has 87.
        payload["cuts_ms"] = cut_times[:40]
        payload["cuts_truncated"] = len(cut_times) > 40
    if brief:
        # Survey mode: same measurements, no per-shot rows. A long video can be
        # scanned window by window without paying for the shot list each time.
        payload["brief"] = True
        payload["cuts_ms"] = cut_times[:40]
        payload["cuts_truncated"] = len(cut_times) > 40
        payload["shots"] = []
        payload["moments"] = [
            {key: m[key] for key in ("t_ms", "onset_ms", "kind", "cell")}
            for m in moments[:4]
        ]
    return payload


def perceive(cfg: Any, video_id: str, *, start_ms: int | None = None,
             end_ms: int | None = None, fps: int | None = None,
             max_frames: int = MAX_FRAMES, brief: bool = False) -> dict[str, Any]:
    with Database(cfg.db_path) as db:
        video = db.get_video(video_id)
    if not video:
        raise Video2AgentError("E_NOT_FOUND", f"Video not found: {video_id}",
                               "Run video2agent list.")
    status = str(video.get("status") or "")
    if status != "ready":
        raise not_ready_error(video_id, status, action="分析")
    duration = int(video.get("duration_ms") or 0)
    _require_window(duration, explicit=start_ms is not None or end_ms is not None)
    start = max(0, int(start_ms or 0))
    end = int(end_ms) if end_ms is not None else max(0, duration)
    if start >= end:
        raise Video2AgentError(
            "E_OUT_OF_RANGE",
            f"窗口为空：start={start}ms end={end}ms（媒体 {duration}ms）。",
            "把 --start 调到媒体时长之前，并保证 start < end。",
        )
    source = str(video.get("source_path") or "")
    payload = _perceive_media(source, start_ms=start, end_ms=end, fps=fps,
                              max_frames=max_frames, brief=brief)
    payload["video_id"] = video_id
    payload["media"]["w"] = int(video.get("width") or payload["media"]["w"])
    payload["media"]["h"] = int(video.get("height") or payload["media"]["h"])
    payload["media"]["fps_nominal"] = float(video.get("fps") or payload["media"]["fps_nominal"])
    if payload["media"]["w"]:
        payload["sampling"]["min_change_px"] = round(
            payload["media"]["w"] / DECODE_W * MIN_CHANGE_PX, 1)
    return payload
