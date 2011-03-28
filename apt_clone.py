# Copyright (C) 2011 Canonical
#
# Authors:
#  Michael Vogt
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; version 3.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

import apt
import apt_pkg
import logging
import glob
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

from StringIO import StringIO

if "APT_CLONE_DEBUG_RESOLVER" in os.environ:
    apt_pkg.config.set("Debug::pkgProblemResolver", "1")

class LowLevelCommands(object):
    """ calls to the lowlevel operations to install debs
        or repack a deb
    """
    dpkg_repack = "/usr/bin/dpkg-repack"

    def install_debs(self, debfiles, targetdir):
        if not debfiles:
            return True
        install_cmd = ["dpkg", "-i"]
        if targetdir != "/":
            install_cmd.insert(0, "chroot")
            install_cmd.insert(1, targetdir)
        ret = subprocess.call(install_cmd + debfiles)
        return (ret == 0)
        
    def repack_deb(self, pkgname, targetdir):
        """ dpkg-repack pkgname into targetdir """
        if not os.path.exists(self.dpkg_repack):
            raise IOError("no '%s' found" % self.dpkg_repack)
        repack_cmd = [self.dpkg_repack]
        if not os.getuid() == 0:
            if not os.path.exists("/usr/bin/fakeroot"):
                return
            repack_cmd.insert(0, "fakeroot")
        ret = subprocess.call(repack_cmd + [pkgname], cwd=targetdir)
        return (ret == 0)

    def debootstrap(self, targetdir, distro=None):
        if distro is None:
            import lsb_release
            distro = lsb_release.get_distro_information()['CODENAME']
        ret = subprocess.call(["debootstrap", distro, targetdir])
        return (ret == 0)

class AptClone(object):
    """ clone the package selection/installation of a existing system
        using the information that apt provides

        If dpkg-repack is installed, it will be used to generate debs
        for the obsolete ones.
    """
    CLONE_FILENAME = "apt-clone-state-%s.tar.gz" % os.uname()[1]
    
    def __init__(self, fetch_progress=None, install_progress=None,
                 cache_cls=None):
        self.not_downloadable = set()
        self.version_mismatch = set()
        self.commands = LowLevelCommands()
        # fetch
        if fetch_progress:
            self.fetch_progress = fetch_progress
        else:
            self.fetch_progress =  apt.progress.text.AcquireProgress()
        # install
        if install_progress:
            self.install_progress = install_progress
        else:
            self.install_progress = apt.progress.base.InstallProgress()
        # cache class (e.g. apt.Cache)
        if cache_cls:
            self._cache_cls = cache_cls
        else:
            self._cache_cls = apt.Cache

    # save
    def save_state(self, sourcedir, target, 
                   with_dpkg_repack=False, with_dpkg_status=False):
        """ save the current system state (installed pacakges, enabled
            repositories ...) into the apt-state.tar.gz file in targetdir
        """
        if os.path.isdir(target):
            targetdir = target
            target = os.path.join(target, self.CLONE_FILENAME)
        else:
            targetdir = os.path.dirname(target)
            if not target.endswith(".tar.gz"):
                target += ".apt-clone.tar.gz"

        if sourcedir != '/':
            apt_pkg.init_config()
            apt_pkg.config.set("Dir", sourcedir)
            apt_pkg.config.set("Dir::State::status",
                               os.path.join(sourcedir, 'var/lib/dpkg/status'))
            apt_pkg.init_system()

        tar = tarfile.open(name=target, mode="w:gz")
        self._write_uname(tar)
        self._write_state_installed_pkgs(sourcedir, tar)
        self._write_state_auto_installed(tar)
        self._write_state_sources_list(tar)
        self._write_state_apt_preferences(tar)
        self._write_state_apt_keyring(tar)
        if with_dpkg_status:
            self._write_state_dpkg_status(tar)
        if with_dpkg_repack:
            self._dpkg_repack(tar)
        tar.close()

    def _write_uname(self, tar):
        f = tempfile.NamedTemporaryFile()
        f.write("\n".join(os.uname()))
        f.flush()
        tar.add(f.name, arcname="./var/lib/apt-clone/uname")

    def _write_state_installed_pkgs(self, sourcedir, tar):
        cache = self._cache_cls(rootdir=sourcedir)
        s = ""
        for pkg in cache:
            if pkg.is_installed:
                # a version identifies the pacakge
                s += "%s %s %s\n" % (
                    pkg.name, pkg.installed.version, int(pkg.is_auto_installed))
                if not pkg.candidate or not pkg.candidate.downloadable:
                    self.not_downloadable.add(pkg.name)        
                elif not (pkg.installed.downloadable and
                          pkg.candidate.downloadable):
                    self.version_mismatch.add(pkg.name)
        # store the installed.pkgs
        tarinfo = tarfile.TarInfo("./var/lib/apt-clone/installed.pkgs")
        tarinfo.size = len(s)
        tarinfo.mtime = time.time()
        tar.addfile(tarinfo, StringIO(s))

    def _write_state_dpkg_status(self, tar):
        # store dpkg-status, this is not strictly needed as installed.pkgs
        # should contain all we need, but we still keep it for debugging
        # reasons
        dpkg_status = apt_pkg.config.find_file("dir::state::status")
        tar.add(dpkg_status, arcname="./var/lib/apt-clone/dpkg-status")

    def _write_state_auto_installed(self, tar):
        extended_states = apt_pkg.config.find_file(
            "Dir::State::extended_states")
        if os.path.exists(extended_states):
            tar.add(extended_states, "./var/lib/apt-clone/extended_states")

    def _write_state_apt_preferences(self, tar):
        f = apt_pkg.config.find_file("Dir::Etc::preferences")
        if os.path.exists(f):
            tar.add(f, arcname="./etc/apt/preferences")
        p = apt_pkg.config.find_dir("Dir::Etc::preferencesparts",
                                    "/etc/apt/preferences.d")
        if os.path.exists(p):
            tar.add(p, arcname="./etc/apt/preferences.d")

    def _write_state_apt_keyring(self, tar):
        f = apt_pkg.config.find_file("Dir::Etc::trusted")
        if os.path.exists(f):
            tar.add(f, arcname="./etc/apt/trusted.gpg")
        p = apt_pkg.config.find_dir("Dir::Etc::trustedparts",
                                    "/etc/apt/trusted.gpg.d")
        if os.path.exists(p):
            tar.add(p, arcname="./etc/apt/trusted.gpg.d")

    def _write_state_sources_list(self, tar):
        tar.add(apt_pkg.config.find_file("Dir::Etc::sourcelist"),
                arcname="./etc/apt/sources.list")
        source_parts = apt_pkg.config.find_dir("Dir::Etc::sourceparts")
        if os.path.exists(source_parts):
            tar.add(source_parts, arcname="./etc/apt/sources.list.d")

    def _dpkg_repack(self, tar):
        tdir = tempfile.mkdtemp()
        for pkgname in self.not_downloadable:
            self.commands.repack_deb(pkgname, tdir)
        tar.add(tdir, arcname="./var/lib/apt-clone/debs")
        shutil.rmtree(tdir)
        #print tdir

    # info
    def info(self, statefile):
        tar = tarfile.open(statefile)
        # guess distro infos
        f = tar.extractfile("./etc/apt/sources.list")
        distro = "unknown"
        for line in f.readlines():
            if line.startswith("#") or line.strip() == "":
                continue
            l = line.split()
            if len(l) > 2 and not l[2].endswith("/"):
                distro = l[2]
                break
        # nr installed
        f = tar.extractfile("./var/lib/apt-clone/installed.pkgs")
        installed = autoinstalled = 0
        meta = []
        for line in f.readlines():
            (name, version, auto) = line.strip().split()
            installed += 1
            if int(auto):
                autoinstalled += 1
            if name.endswith("-desktop"):
                meta.append(name)
        # date
        m = tar.getmember("./var/lib/apt-clone/installed.pkgs")
        date = m.mtime
        # check hostname (if found)
        hostname = "unknown"
        if "./var/lib/apt-clone/uname" in tar.getnames():
            uname = tar.extractfile("./var/lib/apt-clone/uname").readlines()
            hostname = uname[1].strip()
        return "Hostname: %(hostname)s\n"\
               "Distro: %(distro)s\n"\
               "Meta: %(meta)s\n"\
               "Installed: %(installed)s pkgs (%(autoinstalled)s automatic)\n"\
               "Date: %(date)s" % { 'hostname' : hostname,
                              'distro' : distro,
                              'meta' : ", ".join(meta),
                              'installed' : installed,
                              'autoinstalled' : autoinstalled, 
                              'date' : time.ctime(date) 
                             }
    

    # restore
    def restore_state(self, statefile, targetdir="/", new_distro=None):
        """ take a statefile produced via (like apt-state.tar.gz)
            save_state() and restore the packages/repositories
            into targetdir (that is usually "/")
        """
        if targetdir != "/":
            apt_pkg.config.set("DPkg::Chroot-Directory", targetdir)

        if not os.path.exists(targetdir):
            print "Dir '%s' does not exist, need to bootstrap first" % targetdir
            self.commands.debootstrap(targetdir)

        self._restore_sources_list(statefile, targetdir)
        self._restore_apt_keyring(statefile, targetdir)
        if new_distro:
            self._rewrite_sources_list(targetdir, new_distro)
        self._restore_package_selection(statefile, targetdir)
        # FIXME: this needs to check if there are conflicts, e.g. via
        #        gdebi
        self._restore_not_downloadable_debs(statefile, targetdir)

    # simulate restore and return list of missing pkgs
    def simulate_restore_state(self, statefile, new_distro=None):
        # create tmp target (with host system dpkg-status) to simulate in
        target = tempfile.mkdtemp()
        dpkg_status = apt_pkg.config.find_file("dir::state::status")
        if not os.path.exists(target+os.path.dirname(dpkg_status)):
            os.makedirs(target+os.path.dirname(dpkg_status))
        shutil.copy(dpkg_status, target+dpkg_status)
        # restore sources.list and update cache in tmp target
        self._restore_sources_list(statefile, target)
        # optionally rewrite on new distro
        if new_distro:
            self._rewrite_sources_list(target, new_distro)
        cache = self._cache_cls(rootdir=target)
        cache.update(apt.progress.base.AcquireProgress())
        cache.open()
        # try to replay cache and see thats missing
        missing = self._restore_package_selection_in_cache(statefile, cache)
        return missing

    def _restore_sources_list(self, statefile, targetdir):
        tar = tarfile.open(statefile)
        tar.extract("./etc/apt/sources.list", targetdir)
        tar.extract("./etc/apt/sources.list.d", targetdir)

    def _restore_apt_keyring(self, statefile, targetdir):
        tar = tarfile.open(statefile)
        try:
            tar.extract("./etc/apt/trusted.gpg", targetdir)
        except KeyError:
            pass
        try:
            tar.extract("./etc/apt/trusted.gpg.d", targetdir)
        except KeyError:
            pass

    def _restore_package_selection_in_cache(self, statefile, cache):
        # reinstall packages
        pkgs = set()
        # get the installed.pkgs data
        tar = tarfile.open(statefile)
        f = tar.extractfile("./var/lib/apt-clone/installed.pkgs")
        for line in f.readlines():
            actiongroup = cache.actiongroup()
            line = line.strip()
            if line.startswith("#") or line == "":
                continue
            (name, version, auto) = line.split()
            pkgs.add(name)
            auto_installed = int(auto)
            from_user = not auto_installed
            if name in cache:
                cache[name].mark_install(from_user=from_user)
                # ensure the auto install info is 
                cache[name].mark_auto(auto_installed)
        # check what is broken and try to fix
        if cache.broken_count > 0:
            resolver = apt_pkg.ProblemResolver(cache._depcache)
            for pkg in cache:
                if pkg.is_installed:
                    resolver.protect(pkg._pkg)
            resolver.resolve()
        # now go over and see what is missing
        missing = set()
        for pkg in pkgs:
            if not pkg in cache:
                missing.add(pkg)
                continue
            if not (cache[pkg].is_installed or cache[pkg].marked_install):
                missing.add(pkg)
        return missing

    def _restore_package_selection(self, statefile, targetdir):
        # create new cache
        cache = self._cache_cls(rootdir=targetdir)
        cache.update(self.fetch_progress)
        cache.open()
        self._restore_package_selection_in_cache(statefile, cache)
        # do it
        cache.commit(self.fetch_progress, self.install_progress)

    def _restore_not_downloadable_debs(self, statefile, targetdir):
        tar = tarfile.open(statefile)
        try:
            tar.extract("./var/lib/apt-clone/debs", targetdir)
        except KeyError:
            return
        debs = []
        path = os.path.join(targetdir, "./var/lib/apt-clone/debs")
        for deb in glob.glob(os.path.join(path, "*.deb")):
            debpath = os.path.join(path, deb)
            debs.append(debpath)
        self.commands.install_debs(debs, targetdir)

    def _rewrite_sources_list(self, targetdir, new_distro):
        from aptsources.sourceslist import SourcesList
        apt_pkg.config.set(
            "Dir::Etc::sourcelist",
            os.path.abspath(os.path.join(targetdir, "etc", "apt", "sources.list")))
        apt_pkg.config.set(
            "Dir::Etc::sourceparts",
            os.path.abspath(os.path.join(targetdir, "etc", "apt", "sources.list.d")))
        sources = SourcesList()
        for entry in sources.list[:]:
            if entry.invalid or entry.disabled:
                continue
            entry.dist = new_distro
        sources.save()


