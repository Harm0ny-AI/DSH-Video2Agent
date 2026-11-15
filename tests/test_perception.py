import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from video2agent.config import Config
from video2agent.db import Database
from video2agent.perception import _compact_shots, _perceive_media, _require_window, perceive
from video2agent.util import Video2AgentError

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        # Swallowing stderr made a CI-only ffmpeg failure indistinguishable from a
        # code bug; keep the tail so the next runner failure is diagnosable.
        raise RuntimeError(
            f"fixture command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-800:]}"
        )


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe required for perception fixtures")
class PerceptionFixtureTests(unittest.TestCase):
    """Behaviour of the measured primitives on generated clips with known events.

    The numbers asserted here are the ones measured in docs/PERCEPTION.md; a
    threshold change that breaks one of them is a regression, not a tuning knob.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        ff = FFMPEG
        common = ["-y", "-hide_banner", "-loglevel", "error"]
        # Hard cuts between three static patterned scenes, 2 s each.
        _run([ff, *common,
              "-f", "lavfi", "-i", "smptebars=s=640x360:d=2:r=30",
              "-f", "lavfi", "-i", "rgbtestsrc=s=640x360:d=2:r=30",
              "-f", "lavfi", "-i", "smptehdbars=s=640x360:d=2:r=30",
              "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0",
              "-pix_fmt", "yuv420p", str(cls.dir / "cuts.mp4")])
        # A cut between two flat colours: no structure to correlate, so the
        # colour channel is the only thing that can see it.
        _run([ff, *common,
              "-f", "lavfi", "-i", "color=c=0x0a84ff:s=640x360:d=2:r=30",
              "-f", "lavfi", "-i", "color=c=0x2ea043:s=640x360:d=2:r=30",
              "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
              "-pix_fmt", "yuv420p", str(cls.dir / "flatcut.mp4")])
        # Still frame with a static box.
        _run([ff, *common, "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:d=6:r=30",
              "-vf", "drawbox=x=280:y=140:w=80:h=80:color=0xffa500:t=fill",
              "-pix_fmt", "yuv420p", str(cls.dir / "static.mp4")])
        # Object motion on a still background.
        _run([ff, *common, "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:d=6:r=30",
              "-f", "lavfi", "-i", "color=c=0xffa500:s=80x80:d=6:r=30",
              "-filter_complex", "[0:v][1:v]overlay=x='40+90*t':y=140:shortest=1",
              "-pix_fmt", "yuv420p", str(cls.dir / "move.mp4")])
        # A 2 s loop repeated three times.
        _run([ff, *common, "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:d=6:r=30",
              "-f", "lavfi", "-i", "color=c=0xffa500:s=80x80:d=6:r=30",
              "-filter_complex", "[0:v][1:v]overlay=x='280+150*sin(2*PI*t/2)':y=140:shortest=1",
              "-pix_fmt", "yuv420p", str(cls.dir / "loop.mp4")])
        # Brightness flicker at 6 Hz (needs >= 12 fps to be visible).
        _run([ff, *common, "-f", "lavfi", "-i", "smptebars=s=640x360:d=6:r=30",
              "-vf", "eq=brightness='0.25*sin(2*PI*6*t)':eval=frame",
              "-pix_fmt", "yuv420p", str(cls.dir / "flicker.mp4")])
        # Colour-only change at 2 s: the luma structure does not change.
        _run([ff, *common,
              "-f", "lavfi", "-i", "color=c=0xf6f4ee:s=640x360:d=4:r=30",
              "-f", "lavfi", "-i", "color=c=0x0a84ff:s=120x60:d=4:r=30",
              "-f", "lavfi", "-i", "color=c=0x2ea043:s=120x60:d=4:r=30",
              "-filter_complex",
              "[0:v][1:v]overlay=x=300:y=80:enable='lt(t,2)'[a];"
              "[a][2:v]overlay=x=300:y=80:enable='gte(t,2)'",
              "-pix_fmt", "yuv420p", str(cls.dir / "color.mp4")])
        # A loop that starts mid-shot (static until 2.5 s, then a 1 s cycle):
        # the shot-level average hides it, so the detector must look at runs.
        _run([ff, *common,
              "-f", "lavfi", "-i", "color=c=0x203040:s=640x360:d=6:r=30",
              "-f", "lavfi", "-i", "color=c=0xffa500:s=80x80:d=6:r=30",
              "-filter_complex", "[0:v][1:v]overlay=x='280+120*sin(2*PI*t/1)':y=140:enable='gte(t,2.5)'",
              "-pix_fmt", "yuv420p", str(cls.dir / "midloop.mp4")])
        # Two known events at 2.1 s (colour swap) and 3.15 s (box appears),
        # deliberately off the grid a 6-frame uniform digest would sample.
        _run([ff, *common,
              "-f", "lavfi", "-i", "color=c=0xf6f4ee:s=640x360:d=4:r=30",
              "-f", "lavfi", "-i", "color=c=0x0a84ff:s=120x60:d=4:r=30",
              "-f", "lavfi", "-i", "color=c=0x2ea043:s=120x60:d=4:r=30",
              "-f", "lavfi", "-i", "color=c=0x8a6a2f:s=100x100:d=4:r=30",
              "-filter_complex",
              "[0:v][1:v]overlay=x=300:y=60:enable='lt(t,2.1)'[a];"
              "[a][2:v]overlay=x=300:y=60:enable='gte(t,2.1)'[b];"
              "[b][3:v]overlay=x=430:y=210:enable='gte(t,3.15)'",
              "-pix_fmt", "yuv420p", str(cls.dir / "events.mp4")])
        # 26 shots of 0.4 s: more cuts than the 20-row shot budget, so the rows
        # must merge while cuts_ms keeps the real boundaries.
        mc = cls.dir / "manycuts"
        mc.mkdir()
        colors = [(0, 0, 0), (255, 255, 255), (255, 165, 0), (0, 0, 255)]
        for i in range(26):
            Image.new("RGB", (320, 180), colors[i % len(colors)]).save(mc / f"{i:02d}.png")
        # image2 with 2.5 fps = 0.4 s per shot. The concat demuxer needs a text
        # list and failed on the Windows CI runner's ffmpeg; image2 has no list.
        _run([ff, *common, "-framerate", "2.5", "-i", str(mc / "%02d.png"),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "2.5",
              str(cls.dir / "manycuts.mp4")])
        # Dropped frames: keep 29 of every 30, original timestamps.
        _run([ff, *common, "-i", str(cls.dir / "move.mp4"),
              "-vf", "select='not(eq(mod(n,30),29))'", "-fps_mode", "passthrough",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.dir / "drop.mp4")])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def clip(self, name: str, ms: int, fps: int = 15) -> dict:
        return _perceive_media(str(self.dir / name), end_ms=ms, fps=fps)

    def test_hard_cuts_land_on_the_known_times(self) -> None:
        vpm = self.clip("cuts.mp4", 6000)
        starts = [s["start_ms"] for s in vpm["shots"]]
        self.assertEqual(len(starts), 3, starts)
        self.assertAlmostEqual(starts[1], 2000, delta=120)
        self.assertAlmostEqual(starts[2], 4000, delta=120)

    def test_colour_only_cut_is_detected(self) -> None:
        vpm = self.clip("flatcut.mp4", 4000)
        starts = [s["start_ms"] for s in vpm["shots"]]
        self.assertEqual(len(starts), 2, starts)
        self.assertAlmostEqual(starts[1], 2000, delta=120)

    def test_merged_shot_rows_still_expose_the_real_cuts(self) -> None:
        vpm = self.clip("manycuts.mp4", 10400, fps=10)
        self.assertTrue(vpm["shots_merged"], json.dumps(vpm.get("shots"))[:200])
        self.assertLessEqual(len(vpm["shots"]), 20)
        self.assertGreaterEqual(vpm["shot_count"], 24, "the fixture has 26 shots")
        self.assertEqual(len(vpm["cuts_ms"]), vpm["shot_count"] - 1, json.dumps(vpm["cuts_ms"]))
        self.assertFalse(vpm["cuts_truncated"])

    def test_still_clip_has_no_events_and_says_so(self) -> None:
        vpm = self.clip("static.mp4", 6000)
        self.assertEqual(vpm["moments"], [])
        self.assertEqual(vpm["shots"], [{"id": "s0", "start_ms": 0, "end_ms": 6000,
                                        "motion": 0.0, "peak_ms": 0}])
        loop = vpm["rhythm"]["loop"]
        self.assertFalse(loop["found"])
        self.assertEqual(loop["reason"], "not_detected")
        codes = [w["code"] for w in vpm["warnings"]]
        self.assertIn("CONTENT_STATIC", codes)
        self.assertIn("NO_CHANGE", codes)

    def test_continuous_object_motion_is_not_a_moment_list(self) -> None:
        vpm = self.clip("move.mp4", 6000)
        self.assertEqual([s["start_ms"] for s in vpm["shots"]], [0])
        self.assertEqual(vpm["moments"], [], "constant motion must not become moments")
        bbox = vpm["regions"]["bbox"]
        self.assertIsNotNone(bbox)
        self.assertEqual(bbox[0], bbox[2], "the box only crosses one grid row")
        self.assertGreater(vpm["regions"]["active"], 0)
        self.assertLess(vpm["regions"]["active"], 40)

    def test_periodic_loop_is_reported_with_its_period(self) -> None:
        vpm = self.clip("loop.mp4", 6000)
        loop = vpm["rhythm"]["loop"]
        self.assertTrue(loop["found"], "a 2 s sine loop must be detected")
        self.assertAlmostEqual(loop["period_ms"], 2000, delta=120)
        self.assertGreaterEqual(loop["cycles"], 2)

    def test_loop_that_starts_mid_shot_is_not_guessed(self) -> None:
        # Known v0 limit: the detector compares the shot average, so a loop that
        # starts mid-shot is not measured. It must say so instead of inventing a
        # period (a real browser recording made it report 417 ms for a 1 s loop).
        vpm = self.clip("midloop.mp4", 6000)
        loop = vpm["rhythm"]["loop"]
        self.assertFalse(loop["found"], json.dumps(loop))
        self.assertEqual(loop["reason"], "not_detected")

    def test_brightness_flicker_is_capture_not_motion(self) -> None:
        vpm = self.clip("flicker.mp4", 6000, fps=30)
        flicker = vpm["capture"]["flicker"]
        self.assertEqual(flicker["kind"], "brightness")
        self.assertAlmostEqual(flicker["hz"], 6.0, delta=0.6)
        self.assertEqual([s["start_ms"] for s in vpm["shots"]], [0])

    def test_colour_only_change_is_a_moment(self) -> None:
        vpm = self.clip("color.mp4", 4000)
        color = [m for m in vpm["moments"] if m["kind"] == "color"]
        self.assertTrue(color, "a colour-only change must not be invisible: " + json.dumps(vpm["moments"]))
        self.assertAlmostEqual(color[0]["t_ms"], 2000, delta=150)
        self.assertAlmostEqual(color[0]["onset_ms"], 2000, delta=150)

    def test_dropped_frames_show_up_in_pts(self) -> None:
        vpm = self.clip("drop.mp4", 6000)
        pts = vpm["capture"]["pts"]
        self.assertIsNotNone(pts)
        self.assertGreaterEqual(pts["gaps"], 1)
        self.assertGreater(pts["max_ms"], pts["median_ms"] * 1.5)

    def test_moments_beat_uniform_sampling_on_known_events(self) -> None:
        # The point of the layer: pick where to look. A 6-frame uniform digest of
        # a 4 s clip samples 333/1000/1667/2333/3000/3667 ms and misses both
        # events at 2.1 s and 3.15 s; the ranked moments must find them.
        vpm = self.clip("events.mp4", 4000)
        moments = [m["t_ms"] for m in vpm["moments"]]
        events = [2100, 3150]

        def covered(times: list[int], tol: int = 150) -> int:
            return sum(1 for e in events if any(abs(t - e) <= tol for t in times))

        uniform6 = [int((i + 0.5) * 4000 / 6) for i in range(6)]
        self.assertGreaterEqual(covered(moments), 2,
                                "perceive missed a known event: " + json.dumps(moments))
        self.assertLess(covered(uniform6), 2,
                        "the fixture no longer shows the uniform-sampling gap")

    def test_brief_mode_keeps_cuts_and_drops_shot_rows(self) -> None:
        full = _perceive_media(str(self.dir / "cuts.mp4"), end_ms=6000, fps=15)
        brief = _perceive_media(str(self.dir / "cuts.mp4"), end_ms=6000, fps=15, brief=True)
        self.assertGreaterEqual(len(full["shots"]), 2)
        self.assertTrue(brief["brief"])
        self.assertEqual(brief["shots"], [], "survey mode must not carry shot rows")
        self.assertGreaterEqual(len(brief["cuts_ms"]), 2, "cuts must survive the survey")
        self.assertLess(len(json.dumps(brief)), len(json.dumps(full)))

    def test_vpm_payload_stays_small(self) -> None:
        vpm = self.clip("move.mp4", 6000)
        self.assertLess(len(json.dumps(vpm)), 4000, "a 6 s map must stay in the token budget")


class PerceptionBudgetTests(unittest.TestCase):
    def test_many_shots_are_merged_without_losing_coverage(self) -> None:
        shots = [{"id": f"s{i}", "start_ms": i * 1000, "end_ms": (i + 1) * 1000,
                  "motion": float(i % 7), "peak_ms": i * 1000 + 500} for i in range(40)]
        rows, original = _compact_shots(shots, cap=20)
        self.assertEqual(original, 40)
        self.assertLessEqual(len(rows), 20)
        self.assertEqual(rows[0]["start_ms"], 0, "the map must still cover the clip")
        self.assertEqual(rows[-1]["end_ms"], 40_000)

    def test_long_video_needs_a_window(self) -> None:
        with self.assertRaises(Video2AgentError) as ctx:
            _require_window(30 * 60 * 1000, explicit=False)
        self.assertEqual(ctx.exception.code, "E_WINDOW_REQUIRED")
        _require_window(30 * 60 * 1000, explicit=True)
        _require_window(120_000, explicit=False)


class PerceptionEntryTests(unittest.TestCase):
    def test_missing_video_is_an_error_not_an_empty_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(home=Path(tmp))
            with Database(cfg.db_path):
                pass
            with self.assertRaises(Video2AgentError) as ctx:
                perceive(cfg, "vid_missing")
            self.assertEqual(ctx.exception.code, "E_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
