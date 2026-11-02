BIN := dss-tui
BASE ?= http://localhost:8083

.PHONY: build run test clean install

build:
	go build -o $(BIN) .

run: build
	./$(BIN) -base $(BASE)

test:
	go test -v -timeout 300s .

clean:
	rm -f $(BIN)

install: build
	install -m 0755 $(BIN) ~/.local/bin/$(BIN)
	@echo "installed: ~/.local/bin/$(BIN)"
