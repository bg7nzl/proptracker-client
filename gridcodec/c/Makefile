CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -Wpedantic -std=c99

.PHONY: test clean

test: test_gridcodec test_embedded
	@echo ""
	@echo "=== Running default mode tests ==="
	./test_gridcodec
	@echo ""
	@echo "=== Running embedded mode tests ==="
	./test_embedded

test_gridcodec: test_gridcodec.c gridcodec.h
	$(CC) $(CFLAGS) -o $@ $<

test_embedded: test_embedded.c gridcodec.h
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f test_gridcodec test_embedded
