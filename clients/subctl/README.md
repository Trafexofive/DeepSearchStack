# subctl — Substrate Control Plane CLI

Single static binary. Talks to the API gateway over HTTP.

## Build

```bash
make build       # → ./subctl
make install     # → /usr/local/bin/subctl
```

## Usage

```bash
# Health dashboard
subctl status

# Workflows
subctl workflow list
subctl workflow run seo_content_loop
subctl workflow seo "WebAssembly component model"

# Blog generation
subctl blog generate "Rust async executors"
subctl blog stats

# Ingest
subctl ingest stats
subctl ingest scan
```

## Configuration

```bash
# Default: http://localhost:80
subctl status

# Custom gateway
subctl -url http://myhost:8080 status

# Environment variable
export SUBSTRATE_URL=http://10.0.0.1:80
subctl status
```

## Dependencies

Zero. Go standard library only.
