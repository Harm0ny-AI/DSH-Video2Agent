from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from video2agent.bili_account import AccountClient, _video_ref
from video2agent.util import Video2AgentError


class _Client(AccountClient):
    def __init__(self):
        super().__init__(cfg=None, delay_read=0, delay_write=0)
        self.calls: list[tuple[str, dict, bool]] = []

    def _csrf(self) -> str:
        return "csrf-token"

    def folders(self):
        return {"ok": True, "folders": []}

    def _request(self, path, *, params=None, data=None, write=False, allow_already=False):
        self.calls.append((path, dict(params or data or {}), write))
        if path == "/x/web-interface/view":
            return {"aid": 12345, "bvid": "BV1xx411c7mD"}
        if path == "/x/v3/fav/resource/deal":
            return {"prompt": True}
        if path == "/x/v3/fav/folder/add":
            return {"id": 999, "title": data.get("title"), "attr": 1}
        if path == "/x/v3/fav/folder/edit":
            return {"id": data.get("media_id"), "title": data.get("title")}
        if path == "/x/v3/fav/resource/batch-del":
            return 0
        if path == "/x/v3/fav/resource/list":
            return {
                "info": {"id": 7, "title": "收藏夹", "media_count": 2, "attr": 0},
                "medias": [
                    {"id": 1, "type": 2, "bvid": "BV1xx411c7mD", "title": "A", "duration": 60,
                     "upper": {"name": "UP", "mid": 2}, "attr": 0, "cnt_info": {"play": 3}},
                    {"id": 2, "type": 2, "bvid": "BV1yy411c7mE", "title": "B", "duration": 120,
                     "upper": {"name": "UP", "mid": 2}, "attr": 0, "cnt_info": {}},
                ],
                "has_more": False,
            }
        raise AssertionError(path)


class BiliAccountTest(unittest.TestCase):
    def test_video_ref(self):
        self.assertEqual(_video_ref("BV1xx411c7mD"), ("bvid", "BV1xx411c7mD"))
        self.assertEqual(_video_ref("av123"), ("aid", "123"))
        self.assertEqual(_video_ref("123"), ("aid", "123"))
        self.assertEqual(_video_ref("https://www.bilibili.com/video/BV1xx411c7mD/"),
                         ("bvid", "BV1xx411c7mD"))

    def test_favorites_normalizes_and_pages(self):
        client = _Client()
        result = client.favorites(7, limit=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["folder"]["title"], "收藏夹")
        self.assertEqual([item["bvid"] for item in result["items"]], ["BV1xx411c7mD", "BV1yy411c7mE"])
        self.assertEqual(result["items"][0]["duration"], "1:00")
        self.assertEqual([c[0] for c in client.calls], ["/x/v3/fav/resource/list"])

    def test_history_filters_old_items(self):
        client = _Client()
        now = int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp())
        with patch("video2agent.bili_account._now", return_value=datetime(2026, 11, 2, tzinfo=timezone.utc)):
            client._request = lambda path, **kw: {
                "list": [
                    {"title": "new", "duration": 60, "author_name": "u", "view_at": now - 60,
                     "history": {"bvid": "BV1xx411c7mD", "oid": 1}},
                    {"title": "old", "duration": 60, "author_name": "u", "view_at": now - 30 * 86400,
                     "history": {"bvid": "BV1yy411c7mE", "oid": 2}},
                ],
                "cursor": {},
            }
            result = client.history(days=1, limit=10)
        self.assertEqual(result["count"] if "count" in result else result["returned"], 1)
        self.assertEqual(result["items"][0]["bvid"], "BV1xx411c7mD")

    def test_history_marks_near_complete_progress(self):
        client = _Client()
        now = int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp())
        with patch("video2agent.bili_account._now", return_value=datetime(2026, 11, 2, tzinfo=timezone.utc)):
            client._request = lambda path, **kw: {
                "list": [{
                    "title": "nearly done", "duration": 100, "author_name": "u",
                    "view_at": now - 60, "progress": 96, "is_finish": 0,
                    "history": {"bvid": "BV1xx411c7mD", "oid": 1},
                }],
                "cursor": {},
            }
            result = client.history(days=1, limit=10)
        self.assertTrue(result["items"][0]["completed"])
        self.assertTrue(result["items"][0]["finished"])

    def test_add_videos_rejects_too_many(self):
        with self.assertRaises(Video2AgentError) as ctx:
            _Client().add_videos(7, [f"BV{i:010d}" for i in range(201)])
        self.assertEqual(ctx.exception.code, "E_ACCOUNT_ARGS")

    def test_create_folder_uses_title_and_private(self):
        client = _Client()
        result = client.create_folder(" 新夹 ", intro="说明", privacy=1)
        self.assertTrue(result["ok"])
        path, data, write = client.calls[-1]
        self.assertEqual(path, "/x/v3/fav/folder/add")
        self.assertEqual(data["title"], "新夹")
        self.assertEqual(data["privacy"], 1)
        self.assertEqual(data["csrf"], "csrf-token")
        self.assertTrue(write)

    def test_create_folder_rejects_overlong_title(self):
        with self.assertRaises(Video2AgentError) as ctx:
            _Client().create_folder("x" * 21)
        self.assertEqual(ctx.exception.code, "E_ACCOUNT_ARGS")

    def test_add_videos_resolves_bv_and_builds_deal(self):
        client = _Client()
        result = client.add_videos(7, ["BV1xx411c7mD"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["added"], 1)
        path, data, write = client.calls[-1]
        self.assertEqual(path, "/x/v3/fav/resource/deal")
        self.assertEqual(data["rid"], 12345)
        self.assertEqual(data["add_media_ids"], "7")
        self.assertEqual(data["csrf"], "csrf-token")
        self.assertTrue(write)

    def test_classify_plan_returns_applyable_plan(self):
        result = _Client().classify_plan("favorites", 7)
        self.assertTrue(result["ok"])
        self.assertTrue(result["plan"]["folders"])
        self.assertEqual(result["plan"]["folders"][0]["privacy"], 1)

    def test_classify_plan_dry_run_does_not_write(self):
        client = _Client()
        plan = {"folders": [{"title": "新夹", "videos": ["BV1xx411c7mD"]}]}
        result = client.apply_plan(plan, confirm=False)
        self.assertTrue(result["dry_run"])
        self.assertEqual(client.calls, [])

    def test_apply_plan_rejects_too_many_videos(self):
        plan = {"folders": [{"title": "大夹", "videos": [f"BV{i:010d}" for i in range(201)]}]}
        with self.assertRaises(Video2AgentError) as ctx:
            _Client().apply_plan(plan, confirm=False)
        self.assertEqual(ctx.exception.code, "E_ACCOUNT_PLAN")

    def test_classify_apply_creates_and_adds(self):
        client = _Client()
        client.folders = lambda: {"folders": []}
        plan = {"folders": [{"title": "新夹", "videos": ["BV1xx411c7mD"], "privacy": 1}]}
        result = client.apply_plan(plan, confirm=True)
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["created"][0]["id"], 999)
        self.assertEqual(len([c for c in client.calls if c[0] == "/x/v3/fav/resource/deal"]), 1)
        self.assertEqual(result["added"], 1)
        self.assertFalse(result["results"][0]["already"])

    def test_rename_folder_uses_edit(self):
        client = _Client()
        result = client.rename_folder(7, "新名字", privacy=0)
        self.assertTrue(result["ok"])
        path, data, write = client.calls[-1]
        self.assertEqual(path, "/x/v3/fav/folder/edit")
        self.assertEqual(data["media_id"], 7)
        self.assertEqual(data["title"], "新名字")
        self.assertEqual(data["privacy"], 0)
        self.assertTrue(write)

    def test_remove_videos_uses_batch_del(self):
        client = _Client()
        result = client.remove_videos(7, ["BV1xx411c7mD"])
        self.assertTrue(result["ok"])
        path, data, write = client.calls[-1]
        self.assertEqual(path, "/x/v3/fav/resource/batch-del")
        self.assertEqual(data["resources"], "12345:2")
        self.assertEqual(data["media_id"], 7)
        self.assertTrue(write)

    def test_add_videos_requires_confirmed_manifest(self):
        client = _Client()
        client._request = lambda path, **kw: (_ for _ in ()).throw(
            Video2AgentError("E_BILI_LOGIN_REQUIRED", "expired")
        )
        result = client.add_videos(7, ["BV1xx411c7mD"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["error"]["code"], "E_ACCOUNT_PARTIAL")
        self.assertEqual(result["results"][0]["error"]["code"], "E_BILI_LOGIN_REQUIRED")


if __name__ == "__main__":
    unittest.main()
