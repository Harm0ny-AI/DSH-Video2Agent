from __future__ import annotations

import html
import re
import shutil
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database
from .util import Video2AgentError, ensure_dir, format_duration, format_timecode, not_ready_error, write_json


def _public_path(value: Any) -> Any:
    """An absolute local path becomes its file name; URLs and names stay as-is.

    An export is meant to be shareable. A Windows path carries the user name and
    directory layout, so it is stripped unless the caller asks for it explicitly.
    """
    if not isinstance(value, str) or not value.strip():
        return value
    text = value.strip()
    if text.startswith("file://"):
        text = text[len("file://"):]
    if re.match(r"^[A-Za-z]:[\\/]", text) or text.startswith("\\\\") or text.startswith("/"):
        # `Path(text).name` uses the host separator, so on Linux a Windows path is
        # one long name and the export leaked C:\Users\... . Split both forms.
        parts = [p for p in re.split(r"[\\/]+", text.rstrip("\\/")) if p]
        return parts[-1] if parts else value
    return value


def _video_bundle(cfg: Config, video_id: str) -> dict[str, Any]:
    with Database(cfg.db_path) as db:
        video = db.get_video(video_id)
        if not video:
            raise Video2AgentError("E_NOT_FOUND", f"Video not found: {video_id}", "Run video2agent list.")
        if str(video.get("status") or "") != "ready":
            raise not_ready_error(video_id, video.get("status"), action="导出为证据")
        segments = db.get_segments(video_id, limit=5000)
        scenes = db.get_scenes(video_id)
        frames = db.get_frames(video_id, limit=5000)
        ocr = db.get_ocr_tracks(video_id, limit=5000)
        vis = db.get_visual_segments(video_id, limit=5000)
    return {"video": video, "segments": segments, "scenes": scenes, "frames": frames, "ocr": ocr, "visual": vis}


def _chapters(video: dict[str, Any], scenes: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not scenes:
        return []
    chapters = []
    start = scenes[0]["start_ms"]
    end = start
    for i, sc in enumerate(scenes):
        end = sc["end_ms"]
        if end - start >= 300_000 or i == len(scenes) - 1:
            title = next((s["text"][:70] for s in segments if start <= s["start_ms"] <= end), "")
            chapters.append({"start_ms": start, "end_ms": end, "title": title or format_duration(start)})
            start = end
    return chapters


def export_markdown(cfg: Config, video_id: str, out_path: str | Path, *,
                    include_paths: bool = False) -> Path:
    b = _video_bundle(cfg, video_id)
    v = b["video"]
    out = Path(out_path)
    ensure_dir(out.parent)
    lines = [
        f"# {v.get('title') or video_id}",
        "",
        f"- 来源：{v.get('source_uri') if include_paths else _public_path(v.get('source_uri'))}",
        f"- 时长：{format_duration(v.get('duration_ms'))}",
        f"- 语言：{v.get('language') or 'unknown'}",
        f"- 状态：{v.get('status')}",
        f"- 视频 ID：{video_id}",
        "",
    ]
    warnings = v.get("warnings") or []
    if warnings:
        lines += ["## 警告", ""]
        for w in warnings:
            lines.append(f"- [{w.get('code')}] {w.get('message')}")
        lines.append("")
    chapters = _chapters(v, b["scenes"], b["segments"])
    if chapters:
        lines += ["## 章节", ""]
        for c in chapters:
            lines.append(f"- {format_timecode(c['start_ms'], millis=False)} · {c['title']}")
        lines.append("")
    lines += ["## 转写", ""]
    for s in b["segments"][:2000]:
        lines.append(f"- [{format_timecode(s['start_ms'])}] {s['text']}")
    lines.append("")
    if b["ocr"]:
        lines += ["## 画面文字（OCR）", ""]
        for o in b["ocr"][:500]:
            lines.append(f"- [{format_timecode(o['start_ms'])}] {o['text']}")
        lines.append("")
    if b["visual"]:
        lines += ["## 视觉结构", ""]
        for s in b["visual"][:300]:
            lines.append(f"- [{format_timecode(s['start_ms'])} – {format_timecode(s['end_ms'])}] {s['label']} ({s['score']})")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def export_json(cfg: Config, video_id: str, out_path: str | Path, *,
                include_paths: bool = False) -> Path:
    b = _video_bundle(cfg, video_id)
    video = dict(b["video"])
    frames = [dict(frame) for frame in b["frames"]]
    if not include_paths:
        for key in ("source_path", "source_uri"):
            if key in video:
                video[key] = _public_path(video[key])
        for frame in frames:
            if "path" in frame:
                frame["path"] = _public_path(frame["path"])
    payload = {
        "schema_version": "1.0",
        "video": video,
        "paths_redacted": not include_paths,
        "chapters": _chapters(b["video"], b["scenes"], b["segments"]),
        "segments": b["segments"],
        "scenes": b["scenes"],
        "frames": frames,
        "ocr": b["ocr"],
        "visual": b["visual"],
    }
    write_json(out_path, payload)
    return Path(out_path)


def export_knowledge(cfg: Config, video_id: str, out_path: str | Path, *,
                     include_paths: bool = False) -> Path:
    b = _video_bundle(cfg, video_id)
    chapters = _chapters(b["video"], b["scenes"], b["segments"])
    payload = {
        "schema_version": "1.0",
        "kind": "video2agent.knowledge",
        "video": {
            "id": video_id,
            "title": b["video"].get("title"),
            "source": b["video"].get("source_uri") if include_paths else _public_path(b["video"].get("source_uri")),
            "duration_ms": b["video"].get("duration_ms"),
            "language": b["video"].get("language"),
        },
        "instructions": "Fill each chapter with evidence-backed knowledge. Every claim must include evidence_id and timecode. Put anything unverified in open_questions.",
        "chapters": [
            {
                **c,
                "timecode": format_timecode(c["start_ms"]),
                "summary": None,
                "concepts": [],
                "claims": [],
                "procedures": [],
                "formulas": [],
                "tables_charts": [],
                "code": [],
                "evidence_ids": [],
            }
            for c in chapters
        ],
        "open_questions": [],
        "warnings": b["video"].get("warnings") or [],
    }
    write_json(out_path, payload)
    return Path(out_path)


def _copy_assets(bundle: dict[str, Any], out_html: Path) -> dict[str, str]:
    assets = ensure_dir(out_html.parent / (out_html.stem + "_assets"))
    mapping: dict[str, str] = {}
    for i, f in enumerate(bundle["frames"][:12]):
        src = Path(f["path"])
        if not src.exists():
            continue
        dst = assets / f"frame_{i:02d}{src.suffix or '.jpg'}"
        try:
            shutil.copy2(src, dst)
            mapping[str(src)] = f"{assets.name}/{dst.name}"
        except Exception:
            continue
    return mapping


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _text_label(frame: dict[str, Any]) -> str:
    """Text coverage, or "text unread" — a frame nobody OCR'd has no measurement."""
    coverage = frame.get("text_coverage")
    if coverage is None:
        return "text 未读"
    return f"text {float(coverage):.2f}"


def export_html(cfg: Config, video_id: str, out_path: str | Path) -> Path:
    b = _video_bundle(cfg, video_id)
    v = b["video"]
    out = Path(out_path)
    ensure_dir(out.parent)
    assets = _copy_assets(b, out)
    chapters = _chapters(v, b["scenes"], b["segments"])
    warnings = v.get("warnings") or []
    labels: dict[str, int] = {}
    for s in b["visual"]:
        labels[s["label"]] = labels.get(s["label"], 0) + 1
    cards = []
    for i, f in enumerate(b["frames"][:12]):
        src = assets.get(str(f["path"]))
        if not src:
            continue
        cards.append(
            "<figure class='frame'>"
            f"<img src='{_esc(src)}' alt='frame at {_esc(format_timecode(f['pts_ms']))}'/>"
            f"<figcaption><span>{_esc(format_timecode(f['pts_ms']))}</span>"
            f"<span class='muted'>{_text_label(f)}</span></figcaption>"
            "</figure>"
        )
    chapter_rows = "".join(
        f"<li><span class='time'>{_esc(format_timecode(c['start_ms'], millis=False))}</span>"
        f"<span>{_esc(c['title'])}</span></li>" for c in chapters
    )
    warning_rows = "".join(
        f"<li><b>{_esc(w.get('code'))}</b> {_esc(w.get('message'))}</li>" for w in warnings
    )
    label_rows = "".join(
        f"<li><span>{_esc(k)}</span><span class='muted'>{_esc(n)}</span></li>" for k, n in sorted(labels.items(), key=lambda kv: -kv[1])
    )
    transcript_rows = "".join(
        f"<tr><td class='time'>{_esc(format_timecode(s['start_ms']))}</td>"
        f"<td>{_esc(s['text'])}</td><td class='muted'>{_esc(s.get('source'))}</td></tr>"
        for s in b["segments"][:800]
    )
    ocr_rows = "".join(
        f"<tr><td class='time'>{_esc(format_timecode(o['start_ms']))}</td>"
        f"<td>{_esc(o['text'])}</td><td class='muted'>{float(o.get('confidence') or 0):.2f}</td></tr>"
        for o in b["ocr"][:400]
    )
    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(v.get('title') or video_id)} · Video2Agent</title>
<style>
:root{{--bg:#f7f6f2;--panel:#fffefa;--ink:#1f1f1c;--muted:#77746b;--line:#dedbd2;--accent:#2f5d50;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;}}
.wrap{{max-width:1080px;margin:0 auto;padding:48px 24px 80px;}}
.eyebrow{{letter-spacing:.14em;text-transform:uppercase;font-size:11px;color:var(--muted);}}
h1{{font-size:34px;line-height:1.2;letter-spacing:-.02em;margin:10px 0 14px;font-weight:650;}}
.meta{{display:flex;flex-wrap:wrap;gap:10px 20px;color:var(--muted);font-size:13px;border-bottom:1px solid var(--line);padding-bottom:20px;}}
.grid{{display:grid;grid-template-columns:1.4fr .6fr;gap:24px;margin-top:28px;}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;}}
.card h2{{font-size:14px;letter-spacing:.02em;margin:0 0 14px;font-weight:650;}}
.muted{{color:var(--muted);}}
ul.clean{{list-style:none;padding:0;margin:0;display:grid;gap:9px;}}
ul.clean li{{display:flex;gap:12px;justify-content:space-between;border-bottom:1px solid #f0eee8;padding-bottom:9px;font-size:14px;}}
.time{{font:12px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--accent);white-space:nowrap;}}
.frames{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;}}
.frame{{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fff;}}
.frame img{{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;}}
.frame figcaption{{display:flex;justify-content:space-between;padding:8px 10px;font-size:11px;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
td,th{{text-align:left;vertical-align:top;padding:8px 6px;border-bottom:1px solid #f0eee8;}}
th{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600;}}
.warn{{border-left:3px solid #b98b3d;padding-left:14px;}}
.footer{{margin-top:36px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:16px;}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr}}.frames{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:26px}}}}
</style>
</head>
<body>
<div class="wrap">
<div class="eyebrow">Video2Agent · evidence report</div>
<h1>{_esc(v.get('title') or video_id)}</h1>
<div class="meta">
<span>{_esc(format_duration(v.get('duration_ms')))}</span>
<span>{_esc(v.get('language') or 'unknown')}</span>
<span>{_esc(v.get('platform') or '')}</span>
<span>{len(b['segments'])} transcript lines</span>
<span>{len(b['ocr'])} OCR tracks</span>
</div>
<div class="grid">
<div>
<div class="card"><h2>Chapters</h2><ul class="clean">{chapter_rows or '<li class="muted">No chapters</li>'}</ul></div>
<div class="card" style="margin-top:18px"><h2>Key frames</h2><div class="frames">{''.join(cards) or '<p class="muted">No frames</p>'}</div></div>
</div>
<div>
<div class="card"><h2>Visual structure</h2><ul class="clean">{label_rows or '<li class="muted">No map</li>'}</ul></div>
<div class="card" style="margin-top:18px"><h2>Warnings</h2><ul class="clean warn">{warning_rows or '<li class="muted">None</li>'}</ul></div>
</div>
</div>
<div class="card" style="margin-top:24px"><h2>Transcript</h2>
<table><thead><tr><th>Time</th><th>Text</th><th>Source</th></tr></thead><tbody>{transcript_rows}</tbody></table></div>
<div class="card" style="margin-top:18px"><h2>On-screen text</h2>
<table><thead><tr><th>Time</th><th>OCR</th><th>Conf.</th></tr></thead><tbody>{ocr_rows}</tbody></table></div>
<div class="footer">Generated by Video2Agent. Frames are evidence, not decoration. Verify important claims against the source video.</div>
</div>
</body>
</html>"""
    out.write_text(html_doc, encoding="utf-8")
    return out
