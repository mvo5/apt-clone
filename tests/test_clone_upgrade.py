#!/usr/bin/python3

import logging
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
import io

import apt
import apt_pkg
import distro_info

sys.path.insert(0, "..")
from apt_clone import AptClone

#apt.apt_pkg.config.set("Debug::pkgProblemResolver", "1")

class TestCloneUpgrade(unittest.TestCase):

    @unittest.skip("need to update apt-clone-state-ubuntu.tar.gz first")
    def test_clone_upgrade_regression(self):
        """ regression test against known installs """
        new = self._create_fake_upgradable_root("natty", meta="ubuntu-desktop")
        self.addCleanup(shutil.rmtree, new)
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
            self.addCleanup(shutil.rmtree, old)
            # create statefile based on the old data
            with tarfile.open("lala.tar.gz", "w:gz") as state:
                state.add(
                    os.path.join(old, "var", "lib", "apt-clone",
                                 "installed.pkgs"),
                    arcname = "./var/lib/apt-clone/installed.pkgs")
            # create new fake environment and try to upgrade
            new = self._create_fake_upgradable_root(supported[-1], meta=meta)
            self.addCleanup(shutil.rmtree, new)
            cache = apt.Cache(rootdir=new)
            clone = AptClone()
            clone._restore_package_selection_in_cache("lala.tar.gz", cache, protect_installed=True)
            self.assertFalse(cache[meta].marked_delete,
                             "package %s marked for removal" % meta)
            self.assertTrue(len(cache.get_changes()) > 0)

    def _ensure_arch_available_on_server(self, server, from_dist, arch):
        # py2/py3 compat
        try:
            from urllib.request import urlopen
        except ImportError:
            from urllib import urlopen
            urlopen  # pyflakes
        uri = "http://%s/dists/%s/main/binary-%s/" % (server, from_dist, arch)
        try:
            fp = urlopen(uri)
            fp.close()
        except IOError:
            return self.skipTest("can not find %s" % uri)
        if fp.getcode() == 404:
            return self.skipTest("can not find %s" % uri)

    def _create_fake_upgradable_root(self, from_dist,
                                     meta="ubuntu-desktop",
                                     tmpdir=None):
        if tmpdir is None:
            tmpdir = tempfile.mkdtemp()
        sources_list = os.path.join(tmpdir, "etc", "apt", "sources.list")
        if not os.path.exists(os.path.dirname(sources_list)):
            os.makedirs(os.path.dirname(sources_list))
        arch = apt_pkg.config.find("APT::Architecture")
        if arch in ['i386', 'amd64']:
            server = 'archive.ubuntu.com/ubuntu'
        else:
            server = 'ports.ubuntu.com/ubuntu-ports'
        # check that the server actually has the given arch, this may not
        # be the case if a architecture is new (like ppc64el)
        self._ensure_arch_available_on_server(server, from_dist, arch)
        with open(os.path.join(sources_list), "w") as fp:
            fp.write("""
deb http://%s %s main restricted universe multiverse
""" % (server, from_dist))
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
            with io.open(dpkg_status, "w", encoding="utf-8") as dpkg:
                with open(installed_pkgs, "w") as installed:
                    for pkg in cache:
                        if pkg.marked_install:
                            s = str(pkg.candidate.record)
                            s = s.replace("Package: %s\n" % pkg.name,
                                          "Package: %s\n%s\n" % (
                                    pkg.name, "Status: install ok installed"))
                            if sys.version < '3':
                                s = unicode(s, encoding='utf-8')
                            dpkg.write(u"%s\n" % s)
                            installed.write("%s %s %s\n" % (pkg.name,
                                                            pkg.candidate.version,
                                                            int(pkg.is_auto_installed)))
        return tmpdir


if __name__ == "__main__":
    unittest.main()
