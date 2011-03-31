
all: test

test:
	set -e; for f in *.py; do \
		PYTHONPATH=.. python $$f; \
	done; \
	# cruft from the tests
	rm -f ./data/mock-system/var/cache/apt/*.bin
	rm -f ./lala.tar.gz
