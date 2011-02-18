#!/usr/bin/python

import apt
import mock
import os
import sys
import tempfile
import unittest

sys.path.insert(0, "..")
import apt_clone
from apt_clone import AptClone


class TestClone(unittest.TestCase):

    @mock.patch("apt_clone.LowLevelCommands")
    def test_save_state(self, mock_lowlevel):
        # setup mock
        mock_lowlevel.repack_deb.return_value = True
        targetdir = tempfile.mkdtemp("apt-clone-tests-")
        # test
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
        if clone.not_downloadable:
            self.assertTrue(clone.commands.repack_deb.called)

    @mock.patch("apt_clone.LowLevelCommands")
    def test_restore_state(self, mock_lowlevel):
        # setup mock
        mock_lowlevel.install_debs.return_value = True
        targetdir = tempfile.mkdtemp("apt-clone-tests-restore-")
        # test
        clone = AptClone()
        clone._restore_package_selection = mock.Mock()
        clone.restore_state("./tests/data/apt-state.tar.gz", targetdir)
        self.assertTrue(clone._restore_package_selection.called)
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "etc","apt","sources.list")))

if __name__ == "__main__":
    unittest.main()
