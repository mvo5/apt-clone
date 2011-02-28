#!/usr/bin/python

import apt
import apt_pkg
import mock
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, "..")
import apt_clone
from apt_clone import AptClone


class TestClone(unittest.TestCase):

    def setUp(self):
        apt_pkg.init_config()
        apt_pkg.config.set("Debug::pkgDPkgPM","1")
        apt_pkg.config.clear("DPkg::Post-Invoke")
        apt_pkg.config.set("APT::Architecture", "i386")
    
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
        clone.restore_state("./tests/data/apt-state.tar.gz", targetdir)
        self.assertTrue(clone._restore_package_selection.called)
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "etc","apt","sources.list")))

    @mock.patch("apt_clone.LowLevelCommands")
    def test_restore_state_on_new_distro_release(self, mock_lowlevel):
        """ test lucid -> maverick apt-clone-ugprade """
        # setup mock for dpkg -i
        mock_lowlevel.install_debs.return_value = True
        # create target dir
        targetdir = tempfile.mkdtemp("apt-clone-tests-restore-")
        os.makedirs(os.path.join(targetdir, "var/lib/dpkg/"))
        # status file from maverick (to simulate running on a maverick live-cd)
        shutil.copy("./tests/data/dpkg-status/dpkg-status-ubuntu-maverick",
                    os.path.join(targetdir, "var/lib/dpkg", "status"))
        # ensure we are the right arch
        os.makedirs(os.path.join(targetdir, "etc/apt"))
        open(os.path.join(targetdir, "etc/apt/apt.conf"), "w").write(
            'APT::Architecture "i386";')
        # test upgrade clone from lucid system to maverick
        clone = AptClone()
        clone.restore_state_on_new_distro_release(
            "./tests/data/apt-state-ubuntu-lucid.tar.gz", 
            "maverick",
            targetdir)
        sources_list = os.path.join(targetdir, "etc","apt","sources.list")
        self.assertTrue(os.path.exists(sources_list))
        self.assertTrue("maverick" in open(sources_list).read())
        self.assertFalse("lucid" in open(sources_list).read())
        

if __name__ == "__main__":
    unittest.main()
