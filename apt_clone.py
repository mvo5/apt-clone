#!/usr/bin/python


import apt
import apt_pkg
# default in py2.7
import argparse
import logging
import glob
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

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

class AptClone(object):
    """ clone the package selection/installation of a existing system
        using the information that apt provides

        If dpkg-repack is installed, it will be used to generate debs
        for the obsolete ones.
    """
    CLONE_FILENAME = "apt-clone-state-%s.tar" % os.uname()[1]
    
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
    def save_state(self, sourcedir, target, with_dpkg_repack=False):
        """ save the current system state (installed pacakges, enabled
            repositories ...) into the apt-state.tar.gz file in targetdir
        """
        if os.path.isdir(target):
            targetdir = target
            target = os.path.join(target, self.CLONE_FILENAME)
        else:
            targetdir = os.path.dirname(target)
            if not target.endswith(".apt-clone.tar"):
                target += ".apt-clone.tar"

        if sourcedir != '/':
            apt_pkg.init_config()
            apt_pkg.config.set("Dir", sourcedir)
            apt_pkg.config.set("Dir::State::status",
                               os.path.join(sourcedir, 'var/lib/dpkg/status'))
            apt_pkg.init_system()

        tar = tarfile.TarFile(name=target, mode="w")
        self._write_state_installed_pkgs(sourcedir, tar)
        self._write_state_auto_installed(tar)
        self._write_state_sources_list(tar)
        self._write_state_apt_preferences(tar)
        self._write_state_apt_keyring(tar)
        if with_dpkg_repack:
            self._dpkg_repack(tar)
        tar.close()

    def _write_state_installed_pkgs(self, sourcedir, tar):
        cache = self._cache_cls(rootdir=sourcedir)
        if os.getuid() == 0:
            cache.update(self.fetch_progress)
        cache.open()
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
        tarinfo = tarfile.TarInfo("var/lib/apt-clone/installed.pkgs")
        tarinfo.size = len(s)
        tar.addfile(tarinfo, StringIO(s))

    def _write_state_auto_installed(self, tar):
        extended_states = apt_pkg.config.find_file(
            "Dir::State::extended_states")
        if os.path.exists(extended_states):
            tar.add(extended_states, "var/lib/apt-clone/extended_states")

    def _write_state_apt_preferences(self, tar):
        f = apt_pkg.config.find_file("Dir::Etc::preferences")
        if os.path.exists(f):
            tar.add(f, arcname="etc/apt/preferences")
        p = apt_pkg.config.find_dir("Dir::Etc::preferencesparts",
                                    "/etc/apt/preferences.d")
        if os.path.exists(p):
            tar.add(p, arcname="etc/apt/preferences.d")

    def _write_state_apt_keyring(self, tar):
        f = apt_pkg.config.find_file("Dir::Etc::trusted")
        if os.path.exists(f):
            tar.add(f, arcname="etc/apt/trusted.gpg")
        p = apt_pkg.config.find_dir("Dir::Etc::trustedparts")
        if os.path.exists(p):
            tar.add(p, arcname="etc/apt/trusted.gpg.d")

    def _write_state_sources_list(self, tar):
        tar.add(apt_pkg.config.find_file("Dir::Etc::sourcelist"),
                arcname="etc/apt/sources.list")
        source_parts = apt_pkg.config.find_dir("Dir::Etc::sourceparts")
        if os.path.exists(source_parts):
            tar.add(source_parts, arcname="etc/apt/sources.list.d")

    def _dpkg_repack(self, tar):
        tdir = tempfile.mkdtemp()
        for pkgname in self.not_downloadable:
            self.commands.repack_deb(pkgname, tdir)
        tar.add(tdir, arcname="var/lib/apt-clone/debs")
        #shutil.rmtree(tdir)
        print tdir

    # restore
    def restore_state(self, statefile, targetdir="/", new_distro=None):
        """ take a statefile produced via (like apt-state.tar.gz)
            save_state() and restore the packages/repositories
            into targetdir (that is usually "/")
        """
        if targetdir != "/":
            apt_pkg.config.set("DPkg::Chroot-Directory", targetdir)
        sourcedir = self._unpack_statefile(statefile)
        self._restore_sources_list(sourcedir, targetdir)
        if new_distro:
            self._rewrite_sources_list(targetdir, new_distro)
        self._restore_package_selection(sourcedir, targetdir)
        # FIXME: this needs to check if there are conflicts, e.g. via
        #        gdebi
        self._restore_not_downloadable_debs(sourcedir, targetdir)

    # simulate restore and return list of missing pkgs
    def simulate_restore_state(self, statefile, new_distro=None):
        # create tmp target (with host system dpkg-status) to simulate in
        target = tempfile.mkdtemp()
        dpkg_status = apt_pkg.config.find_file("dir::state::status")
        if not os.path.exists(target+os.path.dirname(dpkg_status)):
            os.makedirs(target+os.path.dirname(dpkg_status))
        shutil.copy(dpkg_status, target+dpkg_status)
        # unpack source
        sourcedir = self._unpack_statefile(statefile)
        # restore sources.list and update cache in tmp target
        self._restore_sources_list(sourcedir, target)
        # optionally rewrite on new distro
        if new_distro:
            self._rewrite_sources_list(target, new_distro)
        cache = self._cache_cls(rootdir=target)
        cache.update(apt.progress.base.AcquireProgress())
        cache.open()
        # try to replay cache and see thats missing
        missing = self._restore_package_selection_in_cache(sourcedir, cache)
        return missing

    def _unpack_statefile(self, statefile):
        # unpack state file
        sourcedir = tempfile.mkdtemp(prefix="apt-clone-")
        ret = subprocess.call(["tar", "xzf", os.path.abspath(statefile)],
                              cwd=sourcedir)
        if ret != 0:
            return None
        return sourcedir

    def _restore_sources_list(self, sourcedir, targetdir):
        tdir = targetdir+apt_pkg.config.find_dir("Dir::Etc")
        if not os.path.exists(tdir):
            os.makedirs(targetdir+apt_pkg.config.find_dir("Dir::Etc"))
        shutil.copy2(
            os.path.join(sourcedir, "sources.list"),
            targetdir+apt_pkg.config.find_file("Dir::Etc::sourcelist"))
        # sources.list.d
        tdir = targetdir+apt_pkg.config.find_dir("Dir::Etc::sourceparts")
        if not os.path.exists(tdir):
            os.makedirs(tdir)
        for f in glob.glob(os.path.join(sourcedir, "sources.list.d", "*.list")):
            shutil.copy2(os.path.join(sourcedir, "sources.list.d", f),
                         tdir)

    def _restore_package_selection_in_cache(self, sourcedir, cache):
        # reinstall packages
        pkgs = set()
        for line in open(os.path.join(sourcedir, "installed.pkgs")):
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

    def _restore_package_selection(self, sourcedir, targetdir):
        # create new cache
        cache = self._cache_cls(rootdir=targetdir)
        cache.update(self.fetch_progress)
        cache.open()
        self._restore_package_selection_in_cache(sourcedir, cache)
        # do it
        cache.commit(self.fetch_progress, self.install_progress)

    def _restore_not_downloadable_debs(self, sourcedir, targetdir):
        debs = []
        for deb in glob.glob(os.path.join(sourcedir, "debs", "*.deb")):
            debpath = os.path.join(sourcedir, "debs", deb)
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


if __name__ == "__main__":

    # command line parser
    parser = argparse.ArgumentParser(description="Clone/restore package info")
    parser.add_argument("--debug", action="store_true", default=False,
                        help="enable debug output")
    subparser = parser.add_subparsers(title="Commands")
    # clone
    command = subparser.add_parser(
        "clone", 
        help="create a clone-file from <source> (usually '/') to <destination>")
    command.add_argument("--source", default="/")
    command.add_argument("destination")
    command.add_argument("--with-dpkg-repack", 
                         action="store_true", default=False,
                         help="add no longer downloadable package to the state bundle (that can make it rather big)")
    command.set_defaults(command="clone")
    # restore
    command = subparser.add_parser(
        "restore",
        help="restore a clone file from <source> to <destination> (usually '/')")
    command.add_argument("source")
    command.add_argument("--destination", default="/")
    command.add_argument("--simulate", action="store_true", default=False)
    command.set_defaults(command="restore")
    # restore on new distro
    command = subparser.add_parser(
        "restore-new-distro",
        help="restore a clone file from <source> to <destination> and try "\
             "upgrading along the way")
    command.add_argument("source")
    command.add_argument("new_distro_codename")
    command.add_argument("--destination", default="/")
    command.add_argument("--simulate", action="store_true", default=False)
    command.set_defaults(command="restore-new-distro")

    # parse
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)


    # do the actual work
    clone = AptClone()
    if args.command == "clone":
        clone.save_state(args.source, args.destination, args.with_dpkg_repack)
        print "not installable: %s" % ", ".join(clone.not_downloadable)
        print "version mismatch: %s" % ", ".join(clone.version_mismatch)
    elif args.command == "restore":
        if args.simulate:
            miss = clone.simulate_restore_state(args.source)
            print "missing: %s" % ",".join(sorted(list(miss)))
        else:
            clone.restore_state(args.source, args.destination)
    elif args.command == "restore-new-distro":
        if args.simulate:
            miss = clone.simulate_restore_state(
                args.source, args.new_distro_codename)
            print "missing: %s" % ",".join(sorted(list(miss)))
        else:
            clone.restore_state(
                args.source, args.destination, args.new_distro_codename)
        
