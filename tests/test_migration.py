import sqlite3
import tempfile
import unittest
from pathlib import Path

from video2agent.db import SCHEMA_VERSION, Database


class MigrationTests(unittest.TestCase):
    def test_legacy_tables_are_upgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE videos (
                    id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    title TEXT,
                    duration_ms INTEGER
                );
                CREATE TABLE jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    source TEXT,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO videos (id,source_kind,source_uri,title,duration_ms)
                VALUES ('vid_legacy','local','old.mp4','legacy',1000);
                INSERT INTO jobs (id,kind,source,state,created_at)
                VALUES ('job_legacy','ingest','old.mp4','ready','2020-01-01T00:00:00+00:00');
            """)
            conn.commit()
            conn.close()

            db = Database(path)
            self.assertEqual(db.schema_version, SCHEMA_VERSION)
            video = db.get_video("vid_legacy")
            self.assertEqual(video["title"], "legacy")
            self.assertIn("meta", video)
            self.assertIn("warnings", video)
            cols = {row[1] for row in db.conn.execute("PRAGMA table_info(jobs)").fetchall()}
            self.assertIn("options_json", cols)
            self.assertIn("error_code", cols)
            db.close()

            db2 = Database(path)
            self.assertEqual(db2.schema_version, SCHEMA_VERSION)
            self.assertEqual(db2.get_video("vid_legacy")["title"], "legacy")
            db2.close()


if __name__ == "__main__":
    unittest.main()
