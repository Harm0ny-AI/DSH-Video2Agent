import os
import subprocess
import unittest
from unittest.mock import patch

from video2agent.util import no_window_kwargs, spawn_detached


class NoWindowTest(unittest.TestCase):
    def test_windows_hides_console(self):
        if os.name != "nt":
            self.skipTest("windows only")
        flags = no_window_kwargs()
        expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.assertEqual(flags.get("creationflags"), expected)

    def test_posix_returns_empty(self):
        if os.name == "nt":
            self.skipTest("posix only")
        self.assertEqual(no_window_kwargs(), {})

    def test_background_worker_hides_console_without_losing_its_process_group(self):
        with patch("video2agent.util.subprocess.Popen") as popen:
            popen.return_value.pid = 42
            self.assertEqual(spawn_detached(["python", "-m", "video2agent", "worker", "job_test"]), 42)
        args = popen.call_args.kwargs
        if os.name == "nt":
            self.assertEqual(args["creationflags"], subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertTrue(args["start_new_session"])
