# subctl — Substrate control plane CLI
# Build: make build
# Install: make install (→ /usr/local/bin)

.PHONY: build install clean

build:
	go build -ldflags="-s -w" -o subctl .

install: build
	cp subctl /usr/local/bin/subctl

clean:
	rm -f subctl
