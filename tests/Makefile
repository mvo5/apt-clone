
all: test

test:
	pyflakes ../apt-clone ../apt_clone.py
	set -e; for f in *.py; do \
		for ver in python3 python; do \
			PYTHONPATH=.. $$ver $$f -v ; \
		done; \
	done; \
	# cruft from the tests
	rm -f ./data/mock-system/var/cache/apt/*.bin
	rm -f ./lala.tar.gz
