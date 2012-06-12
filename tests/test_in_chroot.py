#!/usr/bin/python3

from __future__ import print_function

import apt
import logging
import os
import subprocess
import sys
import unittest

# use the right dir
testdir = os.path.dirname(__file__)
if testdir:
    os.chdir(testdir)
# insert path
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
            print("Skipping because uid != 0")
            return
        # do it
        target = "./test-chroot"
        if not os.path.exists(target):
            os.mkdir(target)
            subprocess.call(["debootstrap", "--arch=i386",
                             "maverick", target])
        # force i386
        with open(os.path.join(target, "etc/apt/apt.conf"), "w") as fp:
            fp.write('APT::Architecture "i386";')

        # restore
        clone = AptClone()
        clone.restore_state(
            "./data/apt-state_chroot_with_vim.tar.gz", target, "maverick")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
