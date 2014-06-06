#!/usr/bin/python3
# -*- coding: utf-8 -*-
from __future__ import print_function

import apt
import apt_pkg
import mock
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import distro_info

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from apt_clone import AptClone


class MockAptCache(apt.Cache):
    def commit(self, fetchp, installp):
        pass
    def update(self, fetchp):
        pass


class TestClone(unittest.TestCase):

    def setUp(self):
        # clean custom apt config - once apt_pkg.config.clear() is exposed
        # use that
        for d in apt_pkg.config.keys():
            apt_pkg.config.clear(d)
        apt_pkg.init_config()
        # setup our custom vars
        apt_pkg.config.set("Dir", "/")
        apt_pkg.config.set("dir::state::status", "/var/lib/dpkg/status")
        self.tempdir = tempfile.mkdtemp("apt-clone-tests")
        os.makedirs(os.path.join(self.tempdir, "var/lib/dpkg/"))
        # ensure we are the right arch
        os.makedirs(os.path.join(self.tempdir, "etc/apt"))
        with open(os.path.join(self.tempdir, "etc/apt/apt.conf"), "w") as fp:
            fp.write('''
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
        sourcedir = "./data/mock-system"
        clone.save_state(sourcedir, targetdir, with_dpkg_repack, with_dpkg_status=True)
        # verify that we got the tarfile
        tarname = os.path.join(targetdir, clone.CLONE_FILENAME)
        self.assertTrue(os.path.exists(tarname))
        with tarfile.open(tarname) as tar:
            #print(tar.getmembers())
            # verify members in tar
            members = [m.name for m in tar.getmembers()]
        self.assertTrue("./etc/apt/sources.list" in members)
        self.assertTrue("./var/lib/apt-clone/installed.pkgs" in members)
        self.assertTrue("./var/lib/apt-clone/extended_states" in members)
        self.assertTrue("./var/lib/apt-clone/dpkg-status" in members)
        self.assertTrue("./etc/apt/sources.list.d" in members)
        self.assertTrue("./etc/apt/preferences.d" in members)
        self.assertTrue("./etc/apt/preferences" in members)
        if clone.not_downloadable:
            self.assertEqual(clone.commands.repack_deb.called, with_dpkg_repack)
        # ensure we have no duplicates in the sources.list.d
        sources_list_d = [p for p in members
                          if p.startswith("./etc/apt/sources.list.d")]
        self.assertEqual(
            sorted(sources_list_d),
            sorted(
                ['./etc/apt/sources.list.d',
                 './etc/apt/sources.list.d/ubuntu-mozilla-daily-ppa-maverick.list']))

    @mock.patch("apt_clone.LowLevelCommands")
    def test_restore_state(self, mock_lowlevel):
        # setup mock
        mock_lowlevel.install_debs.return_value = True
        targetdir = self.tempdir
        # test
        clone = AptClone(cache_cls=MockAptCache)
        clone.restore_state(
            "./data/apt-state_chroot_with_vim.tar.gz", targetdir)
        self.assertTrue(
            os.path.exists(os.path.join(targetdir, "etc","apt","sources.list")))

    @mock.patch("apt_clone.LowLevelCommands")
    def test_restore_state_with_not_downloadable_debs(self, mock_lowlevel):
        # setup mock
        mock_lowlevel.install_debs.return_value = True
        targetdir = self.tempdir
        # test
        clone = AptClone(cache_cls=MockAptCache)
        clone.restore_state(
            "./data/apt-state_with_not_downloadable_debs.tar.gz", targetdir)
        self.assertTrue(
            os.path.exists(
                os.path.join(targetdir, "var", "lib", "apt-clone", "debs", "foo.deb")))

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
        with open("./data/dpkg-status/dpkg-status-ubuntu-maverick",
                  "rb") as fp:
            s = fp.read().decode("utf8")
        s = s.replace(
            "Architecture: i386",
            "Architecture: %s" % apt_pkg.config.find("Apt::Architecture"))
        path = os.path.join(targetdir, "var/lib/dpkg", "status")
        with open(path, "wb",) as fp:
            fp.write(s.encode("utf-8"))
        # test upgrade clone from lucid system to maverick
        clone = AptClone(cache_cls=MockAptCache)
        clone.restore_state(
            "./data/apt-state-ubuntu-lucid.tar.gz",
            targetdir,
            "maverick")
        sources_list = os.path.join(targetdir, "etc","apt","sources.list")
        self.assertTrue(os.path.exists(sources_list))
        with open(sources_list) as fp:
            self.assertTrue("maverick" in fp.read())
        with open(sources_list) as fp:
            self.assertFalse("lucid" in fp.read())

    def test_restore_state_simulate(self):
        clone = AptClone()
        supported = distro_info.UbuntuDistroInfo().supported()

        missing = clone.simulate_restore_state("./data/apt-state.tar.gz", new_distro=supported[-1])
        # missing, because clone does not have universe enabled
        self.assertEqual(list(missing), ['accerciser'])

    def test_restore_state_simulate_with_new_release(self):
        #apt_pkg.config.set("Debug::PkgProblemResolver", "1")
        apt_pkg.config.set(
            "Dir::state::status",
            "./data/dpkg-status/dpkg-status-ubuntu-maverick")
        clone = AptClone()
        missing = clone.simulate_restore_state(
            "./data/apt-state-ubuntu-lucid.tar.gz", "maverick")
        # FIXME: check that the stuff in missing is ok
        #print(missing)

    def test_modified_conffiles(self):
        clone = AptClone()
        modified = clone._find_modified_conffiles("./data/mock-system")
        self.assertEqual(
            modified, set(["./data/mock-system/etc/conffile.modified"]))

    def test_unowned_in_etc(self):
        # test in mock environement
        apt_pkg.config.set(
            "Dir::state::status",
            "./data/mock-system/var/lib/dpkg/status")
        clone = AptClone()
        unowned = clone._find_unowned_in_etc("./data/mock-system")
        self.assertFalse("/etc/conffile.modified" in unowned)
        self.assertFalse("/etc/conffile.not-modified" in unowned)
        self.assertTrue("/etc/unowned-file" in unowned)
        # test on the real system and do very light checks
        apt_pkg.config.set(
            "Dir::state::status",
            "/var/lib/dpkg/status")
        unowned = clone._find_unowned_in_etc()
        #print(unowned)
        self.assertNotEqual(unowned, set())
        # negative test, is created by the installer
        self.assertTrue("/etc/apt/sources.list" in unowned)
        # postivie test, belongs to base-files
        self.assertFalse("/etc/issue" in unowned)
        #print("\n".join(sorted(unowned)))


if __name__ == "__main__":
    unittest.main()
