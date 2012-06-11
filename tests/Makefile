
all: test

test:
	pyflakes ../apt-clone ../apt_clone.py
	set -e; for f in *.py; do \
		PYTHONPATH=.. python3 $$f; \
	done; \
	# cruft from the tests
	rm -f ./data/mock-system/var/cache/apt/*.bin
	rm -f ./lala.tar.gz
