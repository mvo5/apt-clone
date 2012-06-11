import unittest
import tempfile
import os
import shutil
import sys

sys.path.insert(0, "..")
from apt_clone import AptClone

class TestMergeSources(unittest.TestCase):
    def test_merge_sources(self):
        clone = AptClone()
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir)
        sources_list = os.path.join(tmpdir, "etc", "apt", "sources.list")
        os.makedirs(os.path.dirname(sources_list))
        shutil.copy('data/lucid-sources.list', sources_list)
        backup = os.path.join(tmpdir, "etc", "apt", "sources.list.apt-clone")
        shutil.copy('data/natty-sources.list', backup)
        clone._rewrite_sources_list(tmpdir, 'natty')
        with open(sources_list) as fp:
            # Tally the occurances of every source line.
            from collections import defaultdict
            tally = defaultdict(int)
            for line in fp:
                if line != '\n' and not line.startswith('#'):
                    tally[line] += 1
            # There should not be any duplicate source lines.
            for line, count in tally.items():
                self.failUnless(count == 1, '"%s" occurred %d times.'
                                % (line, count))

            # Check for extras, others...
            l = (('partner',
                  'deb http://archive.canonical.com/ubuntu natty partner\n'),
                 ('extras',
                  'deb http://extras.ubuntu.com/ubuntu natty main\n'),
                 ('main',
                  'deb http://gb.archive.ubuntu.com/ubuntu/ natty main restricted\n'))
            for pocket, match in l:
                fp.seek(0)
                found = False
                for line in fp:
                    if line == match:
                        found = True
                self.failUnless(found,
                        '%s repository not present or disabled.' % pocket)

if __name__ == "__main__":
    unittest.main()
