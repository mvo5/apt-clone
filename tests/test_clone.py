#!/usr/bin/python

import os
import sys
import tempfile
import unittest

sys.path.insert(0, "..")
from apt_clone import AptClone

class TestClone(unittest.TestCase):
    def test_save_state(self):
        targetdir = tempfile.mkdtemp("apt-clone-tests-")
        clone = AptClone()
        clone.save_state(targetdir)
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "sources.list")))
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "installed.pkgs")))
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "extended_states")))
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "sources.list.d")))
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "apt-state.tar.gz")))


if __name__ == "__main__":
    unittest.main()
