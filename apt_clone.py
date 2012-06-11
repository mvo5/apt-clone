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

from __future__ import print_function

import apt
from apt.cache import FetchFailedException
import apt_pkg
import logging
import glob
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import time

from StringIO import StringIO

if "APT_CLONE_DEBUG_RESOLVER" in os.environ:
    apt_pkg.config.set("Debug::pkgProblemResolver", "1")
    apt_pkg.config.set("Debug::pkgDepCache::AutoInstall", "1")

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
            repack_cmd = ["fakeroot", "-u"] + repack_cmd
        ret = subprocess.call(repack_cmd + [pkgname], cwd=targetdir)
        return (ret == 0)

    def debootstrap(self, targetdir, distro=None):
        if distro is None:
            import lsb_release
            distro = lsb_release.get_distro_information()['CODENAME']
        ret = subprocess.call(["debootstrap", distro, targetdir])
        return (ret == 0)

    def merge_keys(self, fromkeyfile, intokeyfile):
        ret = subprocess.call(['apt-key', '--keyring', intokeyfile,
                               'add', fromkeyfile])
        return (ret == 0)

class AptClone(object):
    """ clone the package selection/installation of a existing system
        using the information that apt provides

        If dpkg-repack is installed, it will be used to generate debs
        for the obsolete ones.
    """
    CLONE_FILENAME = "apt-clone-state-%s.tar.gz" % os.uname()[1]

    TARPREFIX = "./"
    
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
            target = os.path.join(target, self.CLONE_FILENAME)
        else:
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
        # not really uname
        host_info = { 'hostname'   : os.uname()[1],
                       'kernel'     : os.uname()[2],
                       'uname_arch' : os.uname()[4],
                       'arch'       : apt_pkg.config.find("APT::Architecture")
                     }
        # save it
        f = tempfile.NamedTemporaryFile()
        info = "\n".join(["%s: %s" % (key, value) 
                          for (key, value) in host_info.items()])
        f.write(info+"\n")
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

    def _write_modified_files_from_etc(self, tar):
        #etcdir = os.path.join(apt_pkg.config.get("Dir"), "etc")
        pass

    def _dpkg_repack(self, tar):
        tdir = tempfile.mkdtemp()
        for pkgname in self.not_downloadable:
            self.commands.repack_deb(pkgname, tdir)
        tar.add(tdir, arcname="./var/lib/apt-clone/debs")
        shutil.rmtree(tdir)
        #print(tdir)

    # detect prefix
    def _detect_tarprefix(self, tar):
        print(tar.getnames())
        if tar.getnames()[-1].startswith("./"):
            self.TARPREFIX = "./"
        else:
            self.TARPREFIX = ""

    # info
    def _get_info_distro(self, statefile):
        tar = tarfile.open(statefile)
        self._detect_tarprefix(tar)
        # guess distro infos
        f = tar.extractfile(self.TARPREFIX+"etc/apt/sources.list")
        distro = None
        for line in f.readlines():
            if line.startswith("#") or line.strip() == "":
                continue
            l = line.split()
            if len(l) > 2 and not l[2].endswith("/"):
                distro = l[2]
                break
        return distro
    def info(self, statefile):
        distro = self._get_info_distro(statefile) or "unknown"
        # nr installed
        tar = tarfile.open(statefile)
        f = tar.extractfile(self.TARPREFIX+"var/lib/apt-clone/installed.pkgs")
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
        m = tar.getmember(self.TARPREFIX+"var/lib/apt-clone/installed.pkgs")
        date = m.mtime
        # check hostname (if found)
        hostname = "unknown"
        arch = "unknown"
        if self.TARPREFIX+"var/lib/apt-clone/uname" in tar.getnames():
            info = tar.extractfile(self.TARPREFIX+"var/lib/apt-clone/uname").read()
            section = apt_pkg.TagSection(info)
            hostname = section.get("hostname", "unknown")
            arch = section.get("arch", "unknown")
        return "Hostname: %(hostname)s\n"\
               "Arch: %(arch)s\n"\
               "Distro: %(distro)s\n"\
               "Meta: %(meta)s\n"\
               "Installed: %(installed)s pkgs (%(autoinstalled)s automatic)\n"\
               "Date: %(date)s\n" % { 'hostname' : hostname,
                                      'distro' : distro,
                                      'meta' : ", ".join(meta),
                                      'installed' : installed,
                                      'autoinstalled' : autoinstalled, 
                                      'date' : time.ctime(date),
                                      'arch' : arch,
                                      }

    # restore
    def restore_state(self, statefile, targetdir="/", new_distro=None, protect_installed=False):
        """ take a statefile produced via (like apt-state.tar.gz)
            save_state() and restore the packages/repositories
            into targetdir (that is usually "/")
        """
        if targetdir != "/":
            apt_pkg.config.set("DPkg::Chroot-Directory", targetdir)

        # detect prefix
        tar = tarfile.open(statefile)
        self._detect_tarprefix(tar)

        if not os.path.exists(targetdir):
            print("Dir '%s' does not exist, need to bootstrap first" % targetdir)
            distro = self._get_info_distro(statefile)
            self.commands.debootstrap(targetdir, distro)

        self._restore_sources_list(statefile, targetdir)
        self._restore_apt_keyring(statefile, targetdir)
        if new_distro:
            self._rewrite_sources_list(targetdir, new_distro)
        self._restore_package_selection(statefile, targetdir, protect_installed)
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
        try:
            cache.update(apt.progress.base.AcquireProgress())
        except FetchFailedException:
            # This cannot be resolved here, but it should not be interpreted as
            # a fatal error.
            pass
        cache.open()
        # try to replay cache and see thats missing
        missing = self._restore_package_selection_in_cache(statefile, cache)
        return missing

    def _restore_sources_list(self, statefile, targetdir):
        tar = tarfile.open(statefile)
        existing = os.path.join(targetdir, "etc", "apt", "sources.list")
        if os.path.exists(existing):
            shutil.copy(existing, '%s.apt-clone' % existing)
        tar.extract(self.TARPREFIX+"etc/apt/sources.list", targetdir)
        try:
            tar.extract(self.TARPREFIX+"etc/apt/sources.list.d", targetdir)
        except KeyError:
            pass

    def _restore_apt_keyring(self, statefile, targetdir):
        existing = os.path.join(targetdir, "etc", "apt", "trusted.gpg")
        backup = '%s.apt-clone' % existing
        if os.path.exists(existing):
            shutil.copy(existing, backup)
        tar = tarfile.open(statefile)
        try:
            tar.extract(self.TARPREFIX+"etc/apt/trusted.gpg", targetdir)
        except KeyError:
            pass
        try:
            tar.extract(self.TARPREFIX+"etc/apt/trusted.gpg.d", targetdir)
        except KeyError:
            pass
        if os.path.exists(backup):
            self.commands.merge_keys(backup, existing)
            os.remove(backup)

    def _restore_package_selection_in_cache(self, statefile, cache, protect_installed=False):
        # reinstall packages
        missing = set()
        pkgs = set()
        # procted installed pkgs
        resolver = apt_pkg.ProblemResolver(cache._depcache)
        if protect_installed:
            for pkg in cache:
                if pkg.is_installed:
                    resolver.protect(pkg._pkg)
        # get the installed.pkgs data
        tar = tarfile.open(statefile)
        f = tar.extractfile(self.TARPREFIX+"var/lib/apt-clone/installed.pkgs")
        # the actiongroup will help libapt to speed up the following loop
        with cache.actiongroup():
            for line in f.readlines():
                line = line.strip()
                if line.startswith("#") or line == "":
                    continue
                (name, version, auto) = line.split()
                pkgs.add(name)
                auto_installed = int(auto)
                from_user = not auto_installed
                if name in cache:
                    try:
                        # special mode, most useful for release-upgrades
                        if protect_installed:
                            cache[name].mark_install(from_user=from_user, auto_fix=False)
                            if cache.broken_count > 0:
                                resolver.resolve()
                                if not cache[name].marked_install:
                                    raise SystemError("pkg %s not marked upgrade" % name)
                        else:
                            # normal mode, this assume the system is consistent
                            cache[name].mark_install(from_user=from_user)
                    except SystemError as e:
                        logging.warn("can't add %s (%s)" % (name, e))
                        missing.add(name)
                    # ensure the auto install info is 
                    cache[name].mark_auto(auto_installed)
        # check what is broken and try to fix
        if cache.broken_count > 0:
            resolver.resolve()
        # now go over and see what is missing
        for pkg in pkgs:
            if not pkg in cache:
                missing.add(pkg)
                continue
            if not (cache[pkg].is_installed or cache[pkg].marked_install):
                missing.add(pkg)
        return missing

    def _restore_package_selection(self, statefile, targetdir, protect_installed):
        # create new cache
        cache = self._cache_cls(rootdir=targetdir)
        try:
            cache.update(self.fetch_progress)
        except FetchFailedException:
            # This cannot be resolved here, but it should not be interpreted as
            # a fatal error.
            pass
        cache.open()
        self._restore_package_selection_in_cache(statefile, cache, protect_installed)
        # do it
        cache.commit(self.fetch_progress, self.install_progress)

    def _restore_not_downloadable_debs(self, statefile, targetdir):
        tar = tarfile.open(statefile)
        try:
            debsdir = [ tarinfo for tarinfo in tar.getmembers() if tarinfo.name.startswith(self.TARPREFIX+"var/lib/apt-clone/debs/")]
            tar.extractall(targetdir,debsdir)
        except KeyError:
            return
        debs = []
        path = os.path.join(targetdir, "./var/lib/apt-clone/debs")
        for deb in glob.glob(os.path.join(path, "*.deb")):
            debpath = os.path.join(path, deb)
            debs.append(debpath)
        self.commands.install_debs(debs, targetdir)

    def _rewrite_sources_list(self, targetdir, new_distro):
        from aptsources.sourceslist import SourcesList, SourceEntry
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
            replacement = ''
            for pocket in ('updates', 'security', 'backports'):
                if entry.dist.endswith('-%s' % pocket):
                    replacement = '%s-%s' % (new_distro, pocket)
                    break
            if replacement:
                entry.dist = replacement
            else:
                entry.dist = new_distro

        existing = os.path.join(targetdir, "etc", "apt",
                                "sources.list.apt-clone")
        sourcelist = apt_pkg.config.find_file("Dir::Etc::sourcelist")
        if os.path.exists(existing):
            with open(existing, 'r') as fp:
                for line in fp:
                    src = SourceEntry(line, sourcelist)
                    if (src.invalid or src.disabled) or src not in sources:
                        sources.list.append(src)
            os.remove(existing)

        for entry in sources.list:
            if entry.uri.startswith('cdrom:'):
                # Make sure CD entries come first.
                sources.list.remove(entry)
                sources.list.insert(0, entry)
                entry.disabled = True
        sources.save()

    def _find_unowned_in_etc(self, sourcedir=""):
        if sourcedir:
            etcdir = os.path.join(sourcedir, "etc")
        else:
            etcdir = "/etc"
        # get all the files that dpkg "owns"
        owned = set()
        dpkg_basedir = os.path.dirname(apt_pkg.config.get("Dir::State::status"))
        for f in glob.glob(os.path.join(dpkg_basedir, "info", "*.list")):
            for line in open(f):
                if line.startswith("/etc/"):
                    owned.add(line.strip())
        # now go over etc
        unowned = set()
        for dirpath, dirnames, filenames in os.walk(etcdir):
            for name in filenames:
                fullname = os.path.join(dirpath[len(sourcedir):], name)
                if not fullname in owned:
                    unowned.add(fullname)
        return unowned

    def _find_modified_conffiles(self, sourcedir="/"):
        dpkg_status = sourcedir+apt_pkg.config.find("Dir::State::status")
        modified = set()
        # iterate dpkg-status file
        tag = apt_pkg.TagFile(open(dpkg_status))
        for entry in tag:
            if "conffiles" in entry:
                for line in entry["conffiles"].split("\n"):
                    obsolete = None
                    if len(line.split()) == 3:
                        name, md5sum, obsolete = line.split()
                    else:
                        name, md5sum = line.split()
                    # update
                    path = sourcedir+name
                    md5sum = md5sum.strip()
                    # ignore oboslete conffiles
                    if obsolete == "obsolete":
                        continue
                    # user removed conffile
                    if not os.path.exists(path):
                        logging.debug("conffile %s removed" % path)
                        modified.add(path)
                        continue
                    # check content
                    md5 = hashlib.md5()
                    md5.update(open(path).read())
                    if md5.hexdigest() != md5sum:
                        logging.debug("conffile %s (%s != %s)" % (
                                path, md5.hexdigest(), md5sum))
                        modified.add(path)
        return modified

    def _dump_debconf_database(self, sourcedir):
        print("not implemented yet")
        # debconf-copydb configdb newdb --config=Name:newdb --config=Driver:File --config=Filename:/tmp/lala.db
        # 
        # debconf-copydb newdb configdb --config=Name:newdb --config=Driver:File --config=Filename:/tmp/lala.db
        # 
        # dump to text with:
        #  debconf-copydb configdb pipe --config=Name:pipe
        #                 --config=Driver:Pipe --config=InFd:none
        # 
        # restore from text with:
        #   ssh remotehost debconf-copydb pipe configdb --config=Name:pipe --config=Driver:Pipe
