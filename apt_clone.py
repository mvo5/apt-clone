#!/usr/bin/python

import apt
import apt_pkg
import glob
import os
import shutil
import string
import subprocess
import sys
import tarfile
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
    
    def __init__(self, fetch_progress=None, install_progress=None):
        self.not_downloadable = set()
        self.version_mismatch = set()
        self.commands = LowLevelCommands()
        if fetch_progress:
            self.fetch_progress = fetch_progres
        else:
            self.fetch_progress =  apt.progress.text.AcquireProgress()
        if install_progress:
            self.install_progress = install_progress
        else:
            self.install_progress = apt.progress.base.InstallProgress()

    # save
    def save_state(self, targetdir):
        """ save the current system state (installed pacakges, enabled
            repositories into the apt-state.tar.gz file in targetdir
        """
        self._write_state_installed_pkgs(targetdir)
        self._write_state_auto_installed(targetdir)
        self._write_state_sources_list(targetdir)
        self._dpkg_repack(targetdir)
        shutil.make_archive(
            os.path.join(targetdir, "apt-state"), "gztar", targetdir)

    def _write_state_installed_pkgs(self, targetdir):
        cache = apt.Cache()
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
        shutil.copy2(apt_pkg.config.find_file("Dir::State::extended_states"),
                     os.path.join(targetdir, "extended_states"))

    def _write_state_sources_list(self, targetdir):
        shutil.copy2(apt_pkg.config.find_file("Dir::Etc::sourcelist"),
                    os.path.join(targetdir, "sources.list"))
        shutil.copytree(apt_pkg.config.find_dir("Dir::Etc::sourceparts"),
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
        # unpack state file
        sourcedir = tempfile.mkdtemp(prefix="apt-clone-")
        subprocess.call(["tar", "xzf", os.path.abspath(statefile)],
                        cwd=sourcedir)
        self._restore_sources_list(sourcedir, targetdir)
        self._restore_package_selection(sourcedir, targetdir)
        self._restore_not_downloadable_debs(sourcedir, targetdir)

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

    def _restore_package_selection(self, sourcedir, targetdir):
        # create new cache
        cache = apt.Cache(rootdir=targetdir)
        cache.update(self.fetch_progress)
        cache.open()
        # reinstall packages
        for line in open(os.path.join(sourcedir, "installed.pkgs")):
            line = line.strip()
            if line.startswith("#") or line == "":
                continue
            (name, version, auto) = line.split()
            from_user = not int(auto)
            if name in cache:
                cache[name].mark_install(auto_inst=False,
                                         auto_fix=False,
                                         from_user=from_user)
        # do it
        cache.commit(self.fetch_progress, self.install_progress)

    def _restore_not_downloadable_debs(self, sourcedir, targetdir):
        debs = []
        for deb in glob.glob(os.path.join(sourcedir, "debs", "*.deb")):
            debpath = os.path.join(sourcedir, "debs", deb)
            debs.append(debpath)
        self.commands.install_debs(debs, targetdir)

if __name__ == "__main__":

    clone = AptClone()

    command = sys.argv[1]
    if command == "clone":
        if os.path.exists("./clone-dir"):
            shutil.rmtree("./clone-dir")
        os.mkdir("./clone-dir")
        clone.save_state("./clone-dir")
        print "not installable: %s" % ", ".join(clone.not_downloadable)
        print "version mismatch: %s" % ", ".join(clone.version_mismatch)
    elif command == "restore":
        if os.path.exists("./restore-dir"):
            shutil.rmtree("./restore-dir")
        os.mkdir("./restore-dir")
        clone.restore_state(sys.argv[2], "./restore-dir")
    
        
