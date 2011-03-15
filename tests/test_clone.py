#!/usr/bin/python

import apt
import apt_pkg
import mock
import os
import shutil
import sys
import tarfile
import tempfile
import unittest

from StringIO import StringIO

sys.path.insert(0, "..")
import apt_clone
from apt_clone import AptClone

class MockAptCache(apt.Cache):
    def commit(self, fetchp, installp):
        pass
    def update(self, fetchp):
        pass

class TestClone(unittest.TestCase):

    def setUp(self):
        apt_pkg.config.set("Dir", "/")
        apt_pkg.config.set("dir::state::status", "/var/lib/dpkg/status")
        self.tempdir = tempfile.mkdtemp("apt-clone-tests")
        os.makedirs(os.path.join(self.tempdir, "var/lib/dpkg/"))
        # ensure we are the right arch
        os.makedirs(os.path.join(self.tempdir, "etc/apt"))
        open(os.path.join(self.tempdir, "etc/apt/apt.conf"), "w").write('''
#clear Dpkg::Post-Invoke;
#clear Dpkg::Pre-Invoke;
#clear APT::Update;
''')

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    @mock.patch("apt_clone.LowLevelCommands")
    def test_save_state(self, mock_lowlevel):
        self._save_state(False)

    @mock.patch("apt_clone.LowLevelCommands")
    def test_save_state_with_dpkg_repack(self, mock_lowlevel):
        self._save_state(True)

    def _save_state(self, with_dpkg_repack):
        # setup mock
        targetdir = self.tempdir
        # test
        clone = AptClone(cache_cls=MockAptCache)
        sourcedir = "./tests/data/mock-system"
        clone.save_state(sourcedir, targetdir, with_dpkg_repack)
        # verify that we got the tarfile
        tarname = os.path.join(targetdir, clone.CLONE_FILENAME)
        self.assertTrue(os.path.exists(tarname))
        tar = tarfile.open(tarname)
        #print tar.getmembers()
        # verify members in tar
        members = [m.name for m in tar.getmembers()]
        self.assertTrue("./etc/apt/sources.list" in members)
        self.assertTrue("./var/lib/apt-clone/installed.pkgs" in members)
        self.assertTrue("./var/lib/apt-clone/extended_states" in members)
        self.assertTrue("./etc/apt/sources.list.d" in members)
        self.assertTrue("./etc/apt/preferences.d" in members)
        self.assertTrue("./etc/apt/preferences" in members)
        if clone.not_downloadable:
            self.assertEqual(clone.commands.repack_deb.called, with_dpkg_repack)

    @mock.patch("apt_clone.LowLevelCommands")
    def test_restore_state(self, mock_lowlevel):
        # setup mock
        mock_lowlevel.install_debs.return_value = True
        targetdir = self.tempdir
        # test
        clone = AptClone(cache_cls=MockAptCache)
        clone.restore_state(
            "./tests/data/apt-state_chroot_with_vim.tar.gz", targetdir)
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "etc","apt","sources.list")))

    @mock.patch("apt_clone.LowLevelCommands")
    def test_restore_state_on_new_distro_release_livecd(self, mock_lowlevel):
        """ 
        test lucid -> maverick apt-clone-ugprade as if it will be used
        from a live cd based upgrader
        """
        # setup mock for dpkg -i
        mock_lowlevel.install_debs.return_value = True
        # create target dir
        targetdir = self.tempdir
        # status file from maverick (to simulate running on a maverick live-cd)
        s=open("./tests/data/dpkg-status/dpkg-status-ubuntu-maverick").read()
        s = s.replace(
            "Architecture: i386",
            "Architecture: %s" % apt_pkg.config.find("Apt::Architecture"))
        open(os.path.join(targetdir, "var/lib/dpkg", "status"), "w").write(s)
        # test upgrade clone from lucid system to maverick
        clone = AptClone(cache_cls=MockAptCache)
        clone.restore_state(
            "./tests/data/apt-state-ubuntu-lucid.tar.gz", 
            targetdir,
            "maverick")
        sources_list = os.path.join(targetdir, "etc","apt","sources.list")
        self.assertTrue(os.path.exists(sources_list))
        self.assertTrue("maverick" in open(sources_list).read())
        self.assertFalse("lucid" in open(sources_list).read())
        
    def test_restore_state_simulate(self):
        clone = AptClone()
        missing = clone.simulate_restore_state("./tests/data/apt-state.tar.gz")
        # missing, because clone does not have universe enabled
        self.assertEqual(list(missing), ["accerciser"])

    def test_restore_state_simulate_with_new_release(self):
        #apt_pkg.config.set("Debug::PkgProblemResolver", "1")
        apt_pkg.config.set(
            "Dir::state::status", 
            "./tests/data/dpkg-status/dpkg-status-ubuntu-maverick")
        clone = AptClone()
        missing = clone.simulate_restore_state(
            "./tests/data/apt-state-ubuntu-lucid.tar.gz", "maverick") 
        # FIXME: check that the stuff in missing is ok
        print missing

if __name__ == "__main__":
    unittest.main()
