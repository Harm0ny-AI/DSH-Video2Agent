import os
import subprocess
import unittest

from video2agent.util import no_window_kwargs


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
