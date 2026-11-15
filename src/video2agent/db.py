from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .text import tokens_for_search
from .util import now_iso, pid_alive, stable_id

SCHEMA_VERSION = 4

SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY,
  source_kind TEXT NOT NULL,
  source_uri TEXT NOT NULL,
  source_path TEXT,
  sha256 TEXT,
  title TEXT,
  duration_ms INTEGER,
  width INTEGER,
  height INTEGER,
  fps REAL,
  language TEXT,
  platform TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  analysis_version TEXT NOT NULL DEFAULT '1',
  meta_json TEXT,
  warnings_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  video_id TEXT,
  source TEXT,
  options_json TEXT,
  state TEXT NOT NULL,
  stage TEXT,
  progress REAL NOT NULL DEFAULT 0,
  message TEXT,
  duration_ms INTEGER,
  position_ms INTEGER,
  counts_json TEXT,
  updated_at TEXT,
  error_code TEXT,
  error_message TEXT,
  remedy TEXT,
  pid INTEGER,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  text TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL,
  speaker TEXT,
  words_json TEXT
);

CREATE TABLE IF NOT EXISTS scenes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  cut_score REAL,
  keyframe_ms INTEGER
);

CREATE TABLE IF NOT EXISTS frames (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  pts_ms INTEGER NOT NULL,
  path TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  motion REAL,
  text_coverage REAL,
  edge_density REAL,
  line_score REAL,
  sharpness REAL,
  has_text INTEGER,
  ocr_status TEXT,
  phash TEXT,
  meta_json TEXT
);

CREATE TABLE IF NOT EXISTS ocr_tracks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  text TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  bbox_json TEXT,
  confidence REAL,
  stability REAL,
  change_type TEXT
);

CREATE TABLE IF NOT EXISTS visual_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  label TEXT NOT NULL,
  score REAL NOT NULL,
  signals_json TEXT
);

CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  modalities TEXT,
  score REAL,
  payload_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_videos (
  collection_id TEXT NOT NULL,
  video_id TEXT NOT NULL,
  PRIMARY KEY (collection_id, video_id)
);

-- Which frames OCR actually read, so a re-ingest can re-read the same moments and
-- evidence answers stay reproducible. Additive table: no schema bump needed.
CREATE TABLE IF NOT EXISTS ocr_anchors (
  video_id TEXT PRIMARY KEY,
  anchors_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS segment_fts USING fts5(
  tokens,
  segment_id UNINDEXED,
  video_id UNINDEXED
);

CREATE VIRTUAL TABLE IF NOT EXISTS ocr_fts USING fts5(
  tokens,
  track_id UNINDEXED,
  video_id UNINDEXED
);

CREATE VIRTUAL TABLE IF NOT EXISTS video_fts USING fts5(
  tokens,
  video_id UNINDEXED
);

CREATE INDEX IF NOT EXISTS idx_segments_video_time ON segments(video_id, start_ms, end_ms);
CREATE INDEX IF NOT EXISTS idx_scenes_video_time ON scenes(video_id, start_ms, end_ms);
CREATE INDEX IF NOT EXISTS idx_frames_video_time ON frames(video_id, pts_ms);
CREATE INDEX IF NOT EXISTS idx_ocr_video_time ON ocr_tracks(video_id, start_ms, end_ms);
CREATE INDEX IF NOT EXISTS idx_visual_video_time ON visual_segments(video_id, start_ms, end_ms);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at);
"""

VIDEO_FIELDS = [
    "id", "source_kind", "source_uri", "source_path", "sha256", "title", "duration_ms",
    "width", "height", "fps", "language", "platform", "status", "analysis_version",
    "meta_json", "warnings_json", "created_at", "updated_at",
]


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self.path.exists() or self.path.stat().st_size == 0
        self.conn = sqlite3.connect(str(self.path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=30000")
        # DDL and the user_version bump are writes. Running them on every open
        # made read-only calls (e.g. `jobs --id` polling) contend with an active
        # ingest for the write lock; polls then blocked for seconds. Only touch
        # the schema when the database is new or older than this code.
        if fresh:
            try:
                self.conn.executescript(SCHEMA)
            except sqlite3.OperationalError:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.executescript(SCHEMA.replace("PRAGMA journal_mode=WAL;", ""))
            self._migrate()
        elif self._stored_version() < SCHEMA_VERSION:
            self.conn.executescript(SCHEMA)
            self._migrate()
        self.conn.commit()
        try:
            # Cheap when the index is current; a title search is useless otherwise.
            self.backfill_video_fts()
        except sqlite3.OperationalError:
            pass

    def _stored_version(self) -> int:
        try:
            row = self.conn.execute("PRAGMA user_version").fetchone()
            return int(row[0]) if row else 0
        except sqlite3.OperationalError:
            return 0

    def _columns(self, table: str) -> set[str]:
        try:
            return {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            return set()

    def _add_column(self, table: str, column: str, decl: str) -> None:
        if column not in self._columns(table):
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def _migrate(self) -> None:
        # Existing libraries were created before some columns existed. Keep the
        # migration idempotent and additive; never drop user data.
        additions = {
            "videos": {
                "meta_json": "TEXT", "warnings_json": "TEXT", "analysis_version": "TEXT NOT NULL DEFAULT '1'",
                "status": "TEXT NOT NULL DEFAULT 'new'", "updated_at": "TEXT",
            },
            "jobs": {
                "options_json": "TEXT", "video_id": "TEXT", "error_code": "TEXT", "error_message": "TEXT",
                "remedy": "TEXT", "pid": "INTEGER", "started_at": "TEXT", "finished_at": "TEXT",
                "duration_ms": "INTEGER", "position_ms": "INTEGER", "counts_json": "TEXT", "updated_at": "TEXT",
            },
            "frames": {"meta_json": "TEXT", "ocr_status": "TEXT"},
            "ocr_tracks": {"stability": "REAL", "change_type": "TEXT"},
        }
        for table, columns in additions.items():
            for column, decl in columns.items():
                self._add_column(table, column, decl)
        if self._stored_version() != SCHEMA_VERSION:
            self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        row = self.conn.execute(sql, tuple(params)).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def upsert_video(self, data: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        data = dict(data)
        data.setdefault("created_at", now)
        data["updated_at"] = now
        if not data.get("id"):
            data["id"] = stable_id("vid", data.get("source_uri", ""), data.get("sha256", ""))
        fields = [f for f in VIDEO_FIELDS if f in data]
        placeholders = ",".join("?" for _ in fields)
        updates = ",".join(f"{f}=excluded.{f}" for f in fields if f not in ("id", "created_at"))
        sql = f"INSERT INTO videos ({','.join(fields)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}"
        self.conn.execute(sql, [data.get(f) for f in fields])
        self._refresh_video_fts(data["id"])
        self.conn.commit()
        return self.get_video(data["id"]) or data

    def _refresh_video_fts(self, video_id: str) -> None:
        """Index a video's title and platform description for text search."""
        row = self.one("SELECT title, meta_json FROM videos WHERE id=?", [video_id])
        if not row:
            return
        meta = {}
        try:
            meta = json.loads(row["meta_json"] or "{}")
        except (TypeError, ValueError):
            meta = {}
        text = " ".join(str(x) for x in (row["title"], meta.get("description"), meta.get("uploader")) if x)
        self.conn.execute("DELETE FROM video_fts WHERE video_id=?", [video_id])
        if text.strip():
            self.conn.execute(
                "INSERT INTO video_fts (tokens, video_id) VALUES (?,?)",
                [tokens_for_search(text), video_id],
            )

    def backfill_video_fts(self) -> int:
        """Fill the video index for rows written before it existed."""
        missing = self.all(
            "SELECT id FROM videos WHERE id NOT IN (SELECT video_id FROM video_fts)"
        )
        for row in missing:
            self._refresh_video_fts(row["id"])
        if missing:
            self.conn.commit()
        return len(missing)

    def search_videos(self, match_query: str, limit: int = 10,
                  video_ids: list[str] | None = None) -> list[dict[str, Any]]:
        sql = ["SELECT v.id, v.title, v.duration_ms, v.platform, bm25(video_fts) AS rank "
               "FROM video_fts JOIN videos v ON v.id=video_fts.video_id "
               "WHERE video_fts MATCH ?"]
        params: list[Any] = [match_query]
        if video_ids:
            sql.append("AND video_fts.video_id IN (%s)" % ",".join("?" * len(video_ids)))
            params.extend(video_ids)
        sql.append("ORDER BY rank LIMIT ?")
        params.append(limit)
        return self.all(" ".join(sql), params)

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM videos WHERE id = ?", [video_id])
        if row:
            row["meta"] = json.loads(row.pop("meta_json") or "{}")
            row["warnings"] = json.loads(row.pop("warnings_json") or "[]")
        return row

    def find_video_by_source(self, source_uri: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM videos WHERE source_uri = ? ORDER BY created_at DESC LIMIT 1", [source_uri])
        return self.get_video(row["id"]) if row else None

    def list_videos(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.all("SELECT id,title,duration_ms,status,platform,created_at FROM videos ORDER BY created_at DESC LIMIT ?", [limit])
        return rows

    def update_video(self, video_id: str, **fields: Any) -> None:
        # A title/description change must reach the title index, or the old title
        # keeps matching forever (reproduced in review).
        _refresh_fts = any(k in fields for k in ("title", "meta_json"))
        if not fields:
            return
        fields["updated_at"] = now_iso()
        sets = ",".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE videos SET {sets} WHERE id=?", [*fields.values(), video_id])
        if _refresh_fts:
            self._refresh_video_fts(video_id)
        self.conn.commit()

    def create_job(self, kind: str, source: str, video_id: str | None = None, options: dict[str, Any] | None = None) -> str:
        job_id = "job_" + uuid4().hex[:12]
        self.conn.execute(
            "INSERT INTO jobs (id,kind,video_id,source,options_json,state,created_at) VALUES (?,?,?,?,?,?,?)",
            [job_id, kind, video_id, source, json.dumps(options or {}, ensure_ascii=False), "queued", now_iso()],
        )
        self.conn.commit()
        return job_id

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        sets = ",".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE jobs SET {sets} WHERE id=?", [*fields.values(), job_id])
        self.conn.commit()
        self._write_job_sidecar(job_id)

    def _write_job_sidecar(self, job_id: str) -> None:
        """Mirror the job row into `jobs/<id>.json`.

        The Host polls a running job every second or so. Reading this file costs
        ~1ms; asking the CLI costs a 0.5s Python start per poll (250 starts for a
        five-minute job). The database stays authoritative — the sidecar is only a
        fast mirror, rewritten atomically so a reader never sees half a document.
        """
        try:
            row = self.get_job(job_id)
            if not row:
                return
            target = self.path.parent / "jobs" / f"{job_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            payload = {
                "ok": True,
                "job": {
                    key: row.get(key) for key in (
                        "id", "state", "stage", "progress", "message", "position_ms",
                        "duration_ms", "video_id", "error_code", "error_message",
                        # `remedy` and `source` are read by the card: without them a
                        # failed job loses its remedy and the resolve-cache lookup
                        # for the cover never matches.
                        "remedy", "source", "created_at", "updated_at",
                    )
                },
            }
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, target)
        except OSError:
            # A read-only home must not turn a progress update into a failure.
            return

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.one("SELECT * FROM jobs WHERE id=?", [job_id])

    def reconcile_job(self, job_id: str) -> dict[str, Any] | None:
        """Mark a job whose worker is gone as failed, then return the row.

        Reading a job must not write one (a read-only DB, or a UI polling while the
        worker reports progress, would otherwise turn a live job into a failure).
        Only the command that *lists* jobs calls this.
        """
        job = self.get_job(job_id)
        try:
            pid = int(job.get("pid")) if job and job.get("pid") else 0
        except (TypeError, ValueError):
            pid = 0
        state = str(job.get("state") or "") if job else ""
        if job and state in ("running", "queued") and pid and not pid_alive(pid):
            # A queued worker waiting in the CLI's ingest slot holds a real pid, so
            # a dead pid means the row is dead too. Leaving a killed *queued* job
            # untouched made the table show 排队中 forever.
            # Conditional: a worker that finished between the check and here must not
            # be rewritten from ready to failed (reproduced in review).
            self.conn.execute(
                "UPDATE jobs SET state='failed', error_code='E_WORKER_LOST', "
                "error_message='worker 进程已退出，任务没有正常结束', "
                "remedy='重新 ingest 或重试该任务。', stage=NULL, message=NULL, "
                "finished_at=? WHERE id=? AND state IN ('running', 'queued')",
                [now_iso(), job_id],
            )
            self.conn.commit()
            self._write_job_sidecar(job_id)
            job = self.get_job(job_id)
        return job

    def has_analysis(self, video_id: str) -> bool:
        """Cheap: does this record have any transcript or frame at all?"""
        row = self.one(
            "SELECT EXISTS(SELECT 1 FROM segments WHERE video_id=?) AS s, "
            "EXISTS(SELECT 1 FROM frames WHERE video_id=?) AS f",
            [video_id, video_id],
        )
        return bool(row and (row.get("s") or row.get("f")))

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", [limit])

    def clear_video_analysis(self, video_id: str) -> None:
        for table in ("segments", "scenes", "frames", "ocr_tracks", "visual_segments", "evidence", "ocr_anchors"):
            self.conn.execute(f"DELETE FROM {table} WHERE video_id=?", [video_id])
        for table in ("segment_fts", "ocr_fts"):
            self.conn.execute(f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} WHERE video_id=?)", [video_id])
        self.conn.commit()

    def delete_video(self, video_id: str) -> None:
        """Remove a cache entry completely; the caller owns its files."""
        self.clear_video_analysis(video_id)
        self.conn.execute("DELETE FROM collection_videos WHERE video_id=?", [video_id])
        self.conn.execute("DELETE FROM video_fts WHERE rowid IN (SELECT rowid FROM video_fts WHERE video_id=?)", [video_id])
        self.conn.execute("DELETE FROM videos WHERE id=?", [video_id])
        self.conn.commit()

    def set_ocr_anchors(self, video_id: str, anchors: list[int]) -> None:
        """Remember which moments OCR read, so a re-ingest can read the same ones."""
        values = sorted({int(a) for a in anchors if int(a) >= 0})
        if not values:
            self.conn.execute("DELETE FROM ocr_anchors WHERE video_id=?", [video_id])
            self.conn.commit()
            return
        self.conn.execute(
            "INSERT INTO ocr_anchors (video_id, anchors_json, created_at) VALUES (?,?,?) "
            "ON CONFLICT(video_id) DO UPDATE SET anchors_json=excluded.anchors_json",
            [video_id, json.dumps(values), now_iso()],
        )
        self.conn.commit()

    def get_ocr_anchors(self, video_id: str) -> list[int]:
        row = self.one("SELECT anchors_json FROM ocr_anchors WHERE video_id=?", [video_id])
        if not row:
            return []
        try:
            values = json.loads(row["anchors_json"] or "[]")
        except (TypeError, ValueError):
            return []
        return sorted({int(v) for v in values if isinstance(v, (int, float))})

    def insert_segments(self, video_id: str, segments: list[dict[str, Any]]) -> int:
        count = 0
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            cur = self.conn.execute(
                "INSERT INTO segments (video_id,start_ms,end_ms,text,source,confidence,speaker,words_json) VALUES (?,?,?,?,?,?,?,?)",
                [
                    video_id, int(seg.get("start_ms", 0)), int(seg.get("end_ms", 0)), text,
                    seg.get("source", "unknown"), seg.get("confidence"), seg.get("speaker"),
                    json.dumps(seg.get("words", []), ensure_ascii=False) if seg.get("words") else None,
                ],
            )
            seg_id = cur.lastrowid
            tokens = seg.get("tokens") or ""
            if tokens:
                self.conn.execute("INSERT INTO segment_fts (tokens,segment_id,video_id) VALUES (?,?,?)", [tokens, seg_id, video_id])
            count += 1
        self.conn.commit()
        return count

    def insert_scenes(self, video_id: str, scenes: list[dict[str, Any]]) -> int:
        for s in scenes:
            self.conn.execute(
                "INSERT INTO scenes (video_id,start_ms,end_ms,cut_score,keyframe_ms) VALUES (?,?,?,?,?)",
                [video_id, int(s.get("start_ms", 0)), int(s.get("end_ms", 0)), s.get("cut_score"), s.get("keyframe_ms")],
            )
        self.conn.commit()
        return len(scenes)

    def insert_frames(self, video_id: str, frames: list[dict[str, Any]]) -> int:
        for f in frames:
            self.conn.execute(
                """INSERT INTO frames
                (video_id,pts_ms,path,width,height,motion,text_coverage,edge_density,line_score,sharpness,has_text,ocr_status,phash,meta_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    video_id, int(f.get("pts_ms", 0)), f.get("path", ""), f.get("width"), f.get("height"),
                    f.get("motion"), f.get("text_coverage"), f.get("edge_density"), f.get("line_score"),
                    f.get("sharpness"), f.get("has_text"), f.get("ocr_status"), f.get("phash"),
                    json.dumps(f.get("meta", {}), ensure_ascii=False) if f.get("meta") else None,
                ],
            )
        self.conn.commit()
        return len(frames)

    def insert_ocr_tracks(self, video_id: str, tracks: list[dict[str, Any]]) -> int:
        for t in tracks:
            cur = self.conn.execute(
                "INSERT INTO ocr_tracks (video_id,text,start_ms,end_ms,bbox_json,confidence,stability,change_type) VALUES (?,?,?,?,?,?,?,?)",
                [
                    video_id, t.get("text", ""), int(t.get("start_ms", 0)), int(t.get("end_ms", 0)),
                    json.dumps(t.get("bbox"), ensure_ascii=False) if t.get("bbox") else None,
                    t.get("confidence"), t.get("stability"), t.get("change_type", "appear"),
                ],
            )
            tokens = t.get("tokens") or ""
            if tokens:
                self.conn.execute("INSERT INTO ocr_fts (tokens,track_id,video_id) VALUES (?,?,?)", [tokens, cur.lastrowid, video_id])
        self.conn.commit()
        return len(tracks)

    def insert_visual_segments(self, video_id: str, segments: list[dict[str, Any]]) -> int:
        for s in segments:
            # `reason` explains an `unknown` label ("text_unmeasured" / "no_frame").
            # It has no column, and dropping it made every unknown segment look the
            # same as a genuinely empty one.
            signals = dict(s.get("signals") or {})
            if s.get("reason"):
                signals["reason"] = s["reason"]
            self.conn.execute(
                "INSERT INTO visual_segments (video_id,start_ms,end_ms,label,score,signals_json) VALUES (?,?,?,?,?,?)",
                [video_id, int(s.get("start_ms", 0)), int(s.get("end_ms", 0)), s.get("label", "unknown"),
                 float(s.get("score", 0)), json.dumps(signals, ensure_ascii=False)],
            )
        self.conn.commit()
        return len(segments)

    def get_segments(self, video_id: str, start_ms: int | None = None, end_ms: int | None = None,
                     limit: int = 500) -> list[dict[str, Any]]:
        sql = "SELECT * FROM segments WHERE video_id=?"
        params: list[Any] = [video_id]
        if start_ms is not None:
            sql += " AND end_ms >= ?"
            params.append(start_ms)
        if end_ms is not None:
            sql += " AND start_ms <= ?"
            params.append(end_ms)
        sql += " ORDER BY start_ms LIMIT ?"
        params.append(limit)
        rows = self.all(sql, params)
        for r in rows:
            r["words"] = json.loads(r.pop("words_json") or "[]")
        return rows

    def get_segment_at(self, video_id: str, at_ms: int) -> dict[str, Any] | None:
        row = self.one(
            "SELECT * FROM segments WHERE video_id=? AND start_ms<=? AND end_ms>=? ORDER BY start_ms DESC LIMIT 1",
            [video_id, at_ms, at_ms],
        )
        if row:
            row["words"] = json.loads(row.pop("words_json") or "[]")
        return row

    def get_scenes(self, video_id: str) -> list[dict[str, Any]]:
        return self.all("SELECT * FROM scenes WHERE video_id=? ORDER BY start_ms", [video_id])

    def get_frames(self, video_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        rows = self.all("SELECT * FROM frames WHERE video_id=? ORDER BY pts_ms LIMIT ?", [video_id, limit])
        for r in rows:
            r["meta"] = json.loads(r.pop("meta_json") or "{}")
        return rows

    def set_frame_ocr(self, video_id: str, pts_ms: int, *, ocr_status: str,
                      text_coverage: float | None, has_text: bool | None = None) -> None:
        """Record an on-demand or explicit index read on the frame row."""
        sql = "UPDATE frames SET ocr_status=?, text_coverage=?"
        params: list[Any] = [ocr_status, text_coverage]
        if has_text is not None:
            sql += ", has_text=?"
            params.append(1 if has_text else 0)
        sql += " WHERE video_id=? AND pts_ms=?"
        params.extend([video_id, int(pts_ms)])
        self.conn.execute(sql, params)
        self.conn.commit()

    def frame_ocr_counts(self, video_id: str) -> dict[str, int]:
        """How many frames were read / empty / failed / never read."""
        rows = self.all(
            "SELECT COALESCE(ocr_status, 'unmeasured') AS status, COUNT(*) AS n "
            "FROM frames WHERE video_id=? GROUP BY status",
            [video_id],
        )
        return {str(r["status"]): int(r["n"]) for r in rows}

    def video_count(self) -> int:
        row = self.one("SELECT COUNT(*) AS n FROM videos")
        return int(row["n"]) if row else 0

    def get_frame_at(self, video_id: str, at_ms: int) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM frames WHERE video_id=? ORDER BY ABS(pts_ms-?) LIMIT 1", [video_id, at_ms])
        if row:
            row["meta"] = json.loads(row.pop("meta_json") or "{}")
        return row

    def count_ocr_tracks(self, video_id: str) -> int:
        """The real row count, not len(get_ocr_tracks(limit=...))."""
        row = self.one("SELECT COUNT(*) AS n FROM ocr_tracks WHERE video_id=?", [video_id])
        return int((row or {}).get("n") or 0)

    def get_ocr_tracks(self, video_id: str, start_ms: int | None = None, end_ms: int | None = None,
                       limit: int = 500) -> list[dict[str, Any]]:
        sql = "SELECT * FROM ocr_tracks WHERE video_id=?"
        params: list[Any] = [video_id]
        if start_ms is not None:
            sql += " AND end_ms >= ?"
            params.append(start_ms)
        if end_ms is not None:
            sql += " AND start_ms <= ?"
            params.append(end_ms)
        sql += " ORDER BY start_ms LIMIT ?"
        params.append(limit)
        rows = self.all(sql, params)
        for r in rows:
            r["bbox"] = json.loads(r.pop("bbox_json") or "null")
        return rows

    def get_visual_segments(self, video_id: str, start_ms: int | None = None, end_ms: int | None = None,
                            types: list[str] | None = None, min_score: float = 0.0,
                            limit: int = 500) -> list[dict[str, Any]]:
        sql = "SELECT * FROM visual_segments WHERE video_id=? AND score>=?"
        params: list[Any] = [video_id, min_score]
        if start_ms is not None:
            sql += " AND end_ms > ?"
            params.append(start_ms)
        if end_ms is not None:
            sql += " AND start_ms < ?"
            params.append(end_ms)
        if types:
            sql += f" AND label IN ({','.join('?' for _ in types)})"
            params.extend(types)
        sql += " ORDER BY start_ms LIMIT ?"
        params.append(limit)
        rows = self.all(sql, params)
        for r in rows:
            r["signals"] = json.loads(r.pop("signals_json") or "{}")
        return rows

    def search_segments(self, match_query: str, video_id: str | None = None, limit: int = 20,
                        video_ids: list[str] | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT s.*, bm25(segment_fts) AS rank FROM segment_fts "
               "JOIN segments s ON s.id=segment_fts.segment_id WHERE segment_fts MATCH ?")
        params: list[Any] = [match_query]
        if video_id:
            sql += " AND segment_fts.video_id=?"
            params.append(video_id)
        elif video_ids:
            # Filter in SQL: filtering after LIMIT let stale non-ready rows fill
            # the pool and hid real hits (rank 250 of 251).
            sql += " AND segment_fts.video_id IN (%s)" % ",".join("?" * len(video_ids))
            params.extend(video_ids)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self.all(sql, params)
        for r in rows:
            r["words"] = json.loads(r.pop("words_json") or "[]")
        return rows

    def search_ocr(self, match_query: str, video_id: str | None = None, limit: int = 20,
                   video_ids: list[str] | None = None) -> list[dict[str, Any]]:
        sql = ("SELECT o.*, bm25(ocr_fts) AS rank FROM ocr_fts "
               "JOIN ocr_tracks o ON o.id=ocr_fts.track_id WHERE ocr_fts MATCH ?")
        params: list[Any] = [match_query]
        if video_id:
            sql += " AND ocr_fts.video_id=?"
            params.append(video_id)
        elif video_ids:
            sql += " AND ocr_fts.video_id IN (%s)" % ",".join("?" * len(video_ids))
            params.extend(video_ids)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self.all(sql, params)
        for r in rows:
            r["bbox"] = json.loads(r.pop("bbox_json") or "null")
        return rows

    def add_collection(self, name: str) -> str:
        cid = stable_id("col", name)
        self.conn.execute("INSERT OR IGNORE INTO collections (id,name,created_at) VALUES (?,?,?)", [cid, name, now_iso()])
        self.conn.commit()
        return cid

    def add_to_collection(self, collection: str, video_id: str) -> None:
        cid = self.add_collection(collection)
        self.conn.execute("INSERT OR IGNORE INTO collection_videos (collection_id,video_id) VALUES (?,?)", [cid, video_id])
        self.conn.commit()

    def collection_videos(self, collection: str) -> list[dict[str, Any]]:
        return self.all(
            "SELECT v.* FROM videos v JOIN collection_videos cv ON cv.video_id=v.id "
            "JOIN collections c ON c.id=cv.collection_id WHERE c.name=? ORDER BY v.created_at DESC",
            [collection],
        )

    def counts(self, video_id: str) -> dict[str, int]:
        out = {}
        for table in ("segments", "scenes", "frames", "ocr_tracks", "visual_segments"):
            row = self.one(f"SELECT COUNT(*) AS n FROM {table} WHERE video_id=?", [video_id])
            out[table] = int(row["n"]) if row else 0
        return out

    def stats(self) -> dict[str, Any]:
        tables = {}
        for table in ("videos", "segments", "scenes", "frames", "ocr_tracks", "visual_segments", "jobs"):
            row = self.one(f"SELECT COUNT(*) AS n FROM {table}")
            tables[table] = int(row["n"]) if row else 0
        return {"tables": tables, "schema_version": self.schema_version,
                "db_bytes": self.path.stat().st_size if self.path.exists() else 0}
