#!/usr/bin/python3

import logging
import os
import shutil
import sys
import tarfile
import tempfile
import unittest

import apt
import distro_info

sys.path.insert(0, "..")
from apt_clone import AptClone

#apt.apt_pkg.config.set("Debug::pkgProblemResolver", "1")

class TestCloneUpgrade(unittest.TestCase):

    @unittest.skip("need to update apt-clone-state-ubuntu.tar.gz first")
    def test_clone_upgrade_regression(self):
        """ regression test against known installs """
        new = self._create_fake_upgradable_root("natty", meta="ubuntu-desktop")
        cache = apt.Cache(rootdir=new)
        clone = AptClone()
        clone._restore_package_selection_in_cache(
            "./data/regression/apt-clone-state-ubuntu.tar.gz", cache)
        self.assertTrue(len(cache.get_changes()) > 0)

    def test_clone_upgrade_synthetic(self):
        """ test clone upgrade with on-the-fly generated chroots """
        supported = distro_info.UbuntuDistroInfo().supported()
        for meta in ["ubuntu-standard", "ubuntu-desktop", "kubuntu-desktop",
                     "xubuntu-desktop"]:
            logging.info("testing %s" % meta)
            old = self._create_fake_upgradable_root(supported[-2], meta=meta)
            # create statefile based on the old data
            with tarfile.open("lala.tar.gz", "w:gz") as state:
                state.add(
                    os.path.join(old, "var", "lib", "apt-clone",
                                 "installed.pkgs"),
                    arcname = "./var/lib/apt-clone/installed.pkgs")
            # create new fake environment and try to upgrade
            new = self._create_fake_upgradable_root(supported[-1], meta=meta)
            cache = apt.Cache(rootdir=new)
            clone = AptClone()
            clone._restore_package_selection_in_cache("lala.tar.gz", cache, protect_installed=True)
            self.assertFalse(cache[meta].marked_delete,
                             "package %s marked for removal" % meta)
            self.assertTrue(len(cache.get_changes()) > 0)
            # cleanup
            shutil.rmtree(old)
            shutil.rmtree(new)

    def _create_fake_upgradable_root(self, from_dist,
                                     meta="ubuntu-desktop",
                                     tmpdir=None):
        if tmpdir is None:
            tmpdir = tempfile.mkdtemp()
        sources_list = os.path.join(tmpdir, "etc", "apt", "sources.list")
        if not os.path.exists(os.path.dirname(sources_list)):
            os.makedirs(os.path.dirname(sources_list))
        with open(os.path.join(sources_list), "w") as fp:
            fp.write("""
deb http://archive.ubuntu.com/ubuntu %s main restricted universe multiverse
""" % from_dist)
        cache = apt.Cache(rootdir=tmpdir)
        cache.update()
        cache.open()
        if not cache[meta].is_installed:
            cache[meta].mark_install()
            installed_pkgs = os.path.join(tmpdir, "var", "lib", "apt-clone", "installed.pkgs")
            if not os.path.exists(os.path.dirname(installed_pkgs)):
                os.makedirs(os.path.dirname(installed_pkgs))
            dpkg_status = os.path.join(tmpdir, "var", "lib", "dpkg", "status")
            if not os.path.exists(os.path.dirname(dpkg_status)):
                os.makedirs(os.path.dirname(dpkg_status))
            with open(dpkg_status, "w") as dpkg:
                with open(installed_pkgs, "w") as installed:
                    for pkg in cache:
                        if pkg.marked_install:
                            s = str(pkg.candidate.record)
                            s = s.replace("Package: %s\n" % pkg.name,
                                          "Package: %s\n%s\n" % (
                                    pkg.name, "Status: install ok installed"))
                            dpkg.write("%s\n" % s)
                            installed.write("%s %s %s\n" % (pkg.name,
                                                            pkg.candidate.version,
                                                            int(pkg.is_auto_installed)))
        return tmpdir


if __name__ == "__main__":
    unittest.main()
