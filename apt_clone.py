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
import tempfile

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
    def save_state(self, sourcedir, targetdir):
        """ save the current system state (installed pacakges, enabled
            repositories into the apt-state.tar.gz file in targetdir
        """

        if sourcedir != '/':
            apt_pkg.init_config()
            apt_pkg.config.set("Dir", sourcedir)
            apt_pkg.config.set("Dir::State::status",
                               os.path.join(sourcedir, 'var/lib/dpkg/status'))
            apt_pkg.init_system()

        self._write_state_installed_pkgs(sourcedir, targetdir)
        self._write_state_auto_installed(targetdir)
        self._write_state_sources_list(targetdir)
        self._dpkg_repack(targetdir)
        shutil.make_archive(
            os.path.join(targetdir, "apt-state"), "gztar", targetdir)

    def _write_state_installed_pkgs(self, sourcedir, targetdir):
        cache = self._cache_cls(rootdir=sourcedir)
        if os.getuid() == 0:
            cache.update(self.fetch_progress)
        cache.open()
        f = open(os.path.join(targetdir, "installed.pkgs"),"w")
        for pkg in cache:
            if pkg.is_installed:
                # a version identifies the pacakge
                f.write("%s %s %s\n" % (pkg.name, pkg.installed.version,
                                        int(pkg.is_auto_installed)))
                if not pkg.candidate or not pkg.candidate.downloadable:
                    self.not_downloadable.add(pkg.name)        
                elif not (pkg.installed.downloadable and
                          pkg.candidate.downloadable):
                    self.version_mismatch.add(pkg.name)
        f.close()

    def _write_state_auto_installed(self, targetdir):
        extended_states = apt_pkg.config.find_file("Dir::State::extended_states")
        if os.path.exists(extended_states):
            shutil.copy2(extended_states,
                         os.path.join(targetdir, "extended_states"))

    def _write_state_sources_list(self, targetdir):
        shutil.copy2(apt_pkg.config.find_file("Dir::Etc::sourcelist"),
                    os.path.join(targetdir, "sources.list"))
        source_parts = apt_pkg.config.find_dir("Dir::Etc::sourceparts")
        if os.path.exists(source_parts):
            shutil.copytree(source_parts,
                            os.path.join(targetdir, "sources.list.d"))

    def _dpkg_repack(self, targetdir):
        tdir = os.path.join(targetdir, "debs")
        if not os.path.exists(tdir):
            os.makedirs(tdir)
        for pkgname in self.not_downloadable:
            self.commands.repack_deb(pkgname, tdir)


    # restore
    def restore_state(self, statefile, targetdir="/"):
        """ take a statefile produced via (like apt-state.tar.gz)
            save_state() and restore the packages/repositories
            into targetdir (that is usually "/")
        """
        sourcedir = self._unpack_statefile(statefile)
        self._restore_sources_list(sourcedir, targetdir)
        self._restore_package_selection(sourcedir, targetdir)
        self._restore_not_downloadable_debs(sourcedir, targetdir)

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
        for line in open(os.path.join(sourcedir, "installed.pkgs")):
            actiongroup = cache.actiongroup()
            line = line.strip()
            if line.startswith("#") or line == "":
                continue
            (name, version, auto) = line.split()
            from_user = not int(auto)
            if name in cache:
                cache[name].mark_install(auto_inst=False,
                                         auto_fix=False,
                                         from_user=from_user)
        # check what is broken and try to fix
        if cache.broken_count > 0:
            resolver = apt_pkg.ProblemResolver(cache._depcache)
            for pkg in cache:
                if pkg.is_installed:
                    resolver.protect(pkg._pkg)
            resolver.resolve()

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

    # restore on a new distro release
    def restore_state_on_new_distro_release_livecd(self, statefile, new_distro, 
                                                   targetdir):
        sourcedir = self._unpack_statefile(statefile)
        self._restore_sources_list(sourcedir, targetdir)
        self._rewrite_sources_list(targetdir, new_distro)
        self._restore_package_selection(sourcedir, targetdir)
        # FIXME: this needs to check if there are conflicts, e.g. via
        #        gdebi
        #self._restore_not_downloadable_debs(sourcedir, targetdir)

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
    command.add_argument("source")
    command.add_argument("destination")
    command.set_defaults(command="clone")
    # restore
    command = subparser.add_parser(
        "restore",
        help="restore a clone file from <source> to <destination> (usually '/')")
    command.add_argument("source")
    command.add_argument("destination")
    command.set_defaults(command="restore")
    # restore distro
    command = subparser.add_parser(
        "restore-new-distro",
        help="restore a clone file from <source> to <destination> and try "\
             "upgrading along the way")
    command.add_argument("source")
    command.add_argument("new_distro_codename")
    command.add_argument("destination")
    command.set_defaults(command="restore-new-distro")

    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)


    # do the actual work
    clone = AptClone()
    if args.command == "clone":
        if os.path.exists(args.destination):
            shutil.rmtree(args.destination)
        os.mkdir(args.destination)
        clone.save_state(args.source, args.destination)
        print "not installable: %s" % ", ".join(clone.not_downloadable)
        print "version mismatch: %s" % ", ".join(clone.version_mismatch)
    elif args.command == "restore":
        clone.restore_state(args.source, args.destination)
    elif args.command == "restore-new-distro":
        clone.restore_state_on_new_distro_release_livecd(
            args.source, args.new_distro_codename, args.destination)
        
