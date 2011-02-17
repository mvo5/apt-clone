#!/usr/bin/python

import apt
import apt_pkg
import os
import shutil
import tarfile

class AptClone(object):
    def __init__(self):
        self.cache = apt.Cache()
        self.not_downloadable = set()
        self.version_mismatch = set()

    def save_state(self, targetdir):
        self.write_state_installed_pkgs(targetdir)
        self.write_state_auto_installed(targetdir)
        self.write_state_sources_list(targetdir)
        shutil.make_archive(
            os.path.join(targetdir, "apt-state"), "gztar", "./target")

    def write_state_installed_pkgs(self, targetdir):
        f = open(os.path.join(targetdir, "installed.pkgs"),"w")
        for pkg in self.cache:
            if pkg.is_installed:
                # a version identifies the pacakge
                f.write("%s %s\n" % (pkg.name, pkg.installed.version))
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

if __name__ == "__main__":

    
    clone = AptClone()
    if os.path.exists("./target"):
        shutil.rmtree("./target")
    os.mkdir("./target")
    clone.save_state("./target")
    
    print "not installable: %s" % ", ".join(clone.not_downloadable)
    print "version mismatch: %s" % ", ".join(clone.version_mismatch)
        
