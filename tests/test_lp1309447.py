#!/usr/bin/python3
# -*- coding: utf-8 -*-

from __future__ import print_function

import os
import sys
import unittest

# this is important
os.environ["LANG"] = "C"


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from apt_clone import AptClone


class MockTar(object):
    def add(self, source, arcname):
        with open(source, "rb") as f:
            self.data = f.read().decode("utf-8")


class TestClone(unittest.TestCase):

    def setUp(self):
        self.apt_clone = AptClone()
        self.test_sources_fname = "test-sources.list"
        with open(self.test_sources_fname, "wb") as f:
            f.write(u"""# äüö
deb http://mvo:secret@archive.u.c/ ubuntu main
""".encode("utf-8"))

    def tearDown(self):
        os.unlink(self.test_sources_fname)

    def test_scrub_file_from_passwords(self):
        """Regression test for utf8 crash LP: #1309447"""
        mock_tar = MockTar()
        self.apt_clone._add_file_to_tar_with_password_check(
            mock_tar, self.test_sources_fname, scrub=True, 
            arcname="some-archname")
        # see if we got the expected data
        self.assertNotIn("mvo:secret", mock_tar.data)
        self.assertEqual(mock_tar.data, u"""# äüö
deb http://USERNAME:PASSWORD@archive.u.c/ ubuntu main
""")


if __name__ == "__main__":
    unittest.main()
