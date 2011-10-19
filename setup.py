#!/usr/bin/env python

from distutils.core import setup
import glob

# real setup
setup(name="apt-clone", 
      version="0.2.1",
      scripts=["apt-clone"],
      data_files = [ ('share/man/man8', 
                      glob.glob("*.8")),
                   ],
      py_modules = ['apt_clone'],
      )
