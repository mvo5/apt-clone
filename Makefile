
all: test

test:
	set -e; for f in tests/*.py; do \
		PYTHONPATH=. python $$f; \
	done; \
