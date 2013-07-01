
all: test

test:
	if find \! -user $$USER | grep -q .; then \
		sudo chown -R $$USER:$$USER .; \
	fi
	pyflakes ../apt-clone ../apt_clone.py
	set -e; for f in *.py; do \
		for ver in python3 python; do \
			PYTHONPATH=.. $$ver $$f -v 2>&1; \
		done; \
	done; \
	# cruft from the tests
	rm -f ./data/mock-system/var/cache/apt/*.bin
	rm -f ./lala.tar.gz
