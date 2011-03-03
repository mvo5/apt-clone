#!/usr/bin/python

import apt
import logging
import os
import subprocess
import sys
import unittest


sys.path.insert(0, "..")
from apt_clone import AptClone

class MockAptCache(apt.Cache):
    def commit(self, fetchp, installp):
        pass
    def update(self, fetchp):
        pass

class TestClone(unittest.TestCase):

    def test_real(self):
        if os.getuid() != 0:
            print "Skipping because uid != 0"
            return
        target = "./tests/data/test-chroot"
        if not os.path.exists(target):
            os.mkdir(target)
            subprocess.call(["debootstrap", "--arch=i386",
                             "maverick", target])
        # force i386
        open(os.path.join(target, "etc/apt/apt.conf"), "w").write('''
APT::Architecture "i386";
''')
        # restore
        clone = AptClone()
        clone.restore_state_on_new_distro_release_livecd(
            "./tests/data/apt-state_chroot_with_vim.tar.gz", "maverick", target)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
