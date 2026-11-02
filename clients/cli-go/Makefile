BIN := dss
BASE ?= http://localhost:8083

.PHONY: build run test clean install

build:
	go build -o $(BIN) ./...

# Quick smoke test against a live stack at $(BASE).
run: build
	./$(BIN) --base-url $(BASE) health

test:
	go test -v -timeout 300s ./...

clean:
	rm -f $(BIN)

install: build
	install -m 0755 $(BIN) ~/.local/bin/$(BIN)
	@echo "installed: ~/.local/bin/$(BIN) — try: dss health"
