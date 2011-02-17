#!/usr/bin/python

import apt
import apt_pkg
import os
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile

class AptClone(object):
    def __init__(self):
        self.not_downloadable = set()
        self.version_mismatch = set()
        self.fetch_progress =  apt.progress.text.AcquireProgress()
        self.install_progress = apt.progress.base.InstallProgress()

    # save
    def save_state(self, targetdir):
        self.write_state_installed_pkgs(targetdir)
        self.write_state_auto_installed(targetdir)
        self.write_state_sources_list(targetdir)
        shutil.make_archive(
            os.path.join(targetdir, "apt-state"), "gztar", "./target")

    def write_state_installed_pkgs(self, targetdir):
        cache = apt.Cache()
        cache.update(self.fetch_progress)
        f = open(os.path.join(targetdir, "installed.pkgs"),"w")
        for pkg in cache:
            if pkg.is_installed:
                # a version identifies the pacakge
                f.write("%s %s %s\n" % (
                    pkg.name, pkg.installed.version, pkg.is_auto_installed))
                if not pkg.candidate or not pkg.candidate.downloadable:
                    self.not_downloadable.add(pkg.name)        
                elif not (pkg.installed.downloadable and
                          pkg.candidate.downloadable):
                    self.version_mismatch.add(pkg.name)
        f.close()

    def write_state_auto_installed(self, targetdir):
        shutil.copy(apt_pkg.config.find_file("Dir::State::extended_states"),
                    os.path.join(targetdir, "extended_states"))

    def write_state_sources_list(self, targetdir):
        shutil.copy(apt_pkg.config.find_file("Dir::Etc::sourcelist"),
                    os.path.join(targetdir, "sources.list"))
        shutil.copytree(apt_pkg.config.find_dir("Dir::Etc::sourceparts"),
                        os.path.join(targetdir, "sources.list.d"))

    # restore
    def restore_state(self, statefile, targetdir):
        tmp = tempfile.mkdtemp(prefix="apt-clone-")
        subprocess.call(["tar", "xzvf", os.path.abspath(statefile)],
                        cwd=tmp)
        # copy sources.list into place
        tdir = targetdir+apt_pkg.config.find_dir("Dir::Etc")
        shutil.rmtree(tdir)
        os.makedirs(targetdir+apt_pkg.config.find_dir("Dir::Etc"))
        shutil.copy2(
            os.path.join(tmp, "sources.list"),
            targetdir+apt_pkg.config.find_file("Dir::Etc::sourcelist"))
        # sources.list.d
        tdir = targetdir+apt_pkg.config.find_dir("Dir::Etc::sourceparts")
        if os.path.exists(tdir):
            shutil.rmtree(tdir)
        shutil.copytree(os.path.join(tmp, "sources.list.d"), tdir)
            
        # create new cache
        cache = apt.Cache(rootdir=targetdir)
        cache.update(self.fetch_progress)
        cache.open()
        # reinstall packages
        for line in open(os.path.join(tmp, "installed.pkgs")):
            line = line.strip()
            if line.startswith("#") or line == "":
                continue
            (name, version, auto) = line.split()
            if name in cache:
                cache[name].mark_install(auto_inst=False,
                                         auto_fix=False,
                                         from_user=bool(auto))
        # do it
        cache.commit(self.fetch_progress, self.install_progress)

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
    
        
