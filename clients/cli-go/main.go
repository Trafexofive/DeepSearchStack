// dss — Command-line client for DeepSearchStack.
//
// Designed to match (and where useful, exceed) the TUI's surface from the
// shell. Every command speaks JSON when piped (or with --json), pretty
// columns when on a terminal. Streaming endpoints stream to stdout.
//
// Usage examples:
//
//   dss ask "what is byzantine fault tolerance"      # agent: aggregate + synthesize, streams answer
//   dss search "consensus algorithms"                # aggregate raw, prints sources
//   dss crawl https://example.com                    # crawl one URL
//   dss render https://example.com --screenshot      # browser-renderer
//   dss ingest paper.pdf book.epub                   # ingest local files
//   dss ingest-site https://simonwillison.net        # discover via sitemap + ingest
//   dss warehouse list --limit 30 --domain wiki     # list rows
//   dss warehouse search "raft consensus"            # FTS5 search
//   dss warehouse hybrid "raft consensus"            # FTS5 + vector RRF
//   dss warehouse get 142                            # get row by id
//   dss warehouse by-url https://en.wikipedia.org/.. # get row by url
//   dss warehouse stats                              # warehouse stats
//   dss models                                       # list LLM models
//   dss providers                                    # list search providers
//   dss health                                       # health probe
//
// Global flags (before the subcommand):
//   --base-url URL    DSS nginx base (default $DSS_BASE_URL or http://localhost:8083)
//   --json            machine-readable JSON output
//   --no-color        disable ANSI colors
//   --timeout SECS    override default per-call timeout
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
)

// Global state shared across subcommands. Set by parseGlobalFlags() before
// dispatch.
var (
	gBaseURL = envOr("DSS_BASE_URL", "http://localhost:8083")
	gJSON    = false
	gNoColor = false
	gTimeout = 0 // 0 = use per-command default
)

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// All subcommands. Each takes the remaining args after the subcommand name.
type cmd struct {
	name    string
	summary string
	run     func(args []string)
}

var commands []cmd

// init wires up the command table after-the-fact to avoid a Go initialization
// cycle (the help command needs to reference the table that contains it).
func init() {
	commands = []cmd{
		{"ask", "Agent query — aggregate + synthesize, stream answer", runAsk},
		{"search", "Aggregate raw sources (no synthesis)", runSearch},
		{"crawl", "Crawl a single URL", runCrawl},
		{"render", "Render a URL via browser-renderer (stealth+OCR)", runRender},
		{"ingest", "Ingest local files into the warehouse", runIngest},
		{"ingest-site", "Discover + ingest a site via sitemap/RSS (sync)", runIngestSite},
		{"jobs", "Async ingest jobs (list/get/queue-site/queue-urls)", runJobs},
		{"watch", "Add an RSS/Atom feed to be polled periodically", runWatch},
		{"watches", "List, force-poll, or remove watched feeds", runWatches},
		{"warehouse", "Warehouse ops (list/search/hybrid/get/by-url/stats)", runWarehouse},
		{"models", "List inference-gateway LLM models", runModels},
		{"providers", "List search providers", runProviders},
		{"health", "Probe stack health", runHealth},
		{"help", "Show this help", runHelp},
	}
}

func main() {
	args := os.Args[1:]
	args = parseGlobalFlags(args)
	if len(args) == 0 {
		printRootHelp()
		os.Exit(1)
	}
	sub := args[0]
	rest := args[1:]
	for _, c := range commands {
		if c.name == sub {
			c.run(rest)
			return
		}
	}
	fmt.Fprintf(os.Stderr, "dss: unknown command %q\n\n", sub)
	printRootHelp()
	os.Exit(2)
}

// parseGlobalFlags walks the prefix args looking for global flags. Stops on
// the first non-flag token (the subcommand). Returns args from that point on.
// We do this manually so subcommands can re-use stdlib flag.NewFlagSet on
// their own args without interference.
func parseGlobalFlags(args []string) []string {
	i := 0
	for i < len(args) {
		a := args[i]
		switch {
		case a == "--":
			return args[i+1:]
		case a == "--json":
			gJSON = true
			i++
		case a == "--no-color":
			gNoColor = true
			i++
		case a == "--base-url":
			if i+1 >= len(args) {
				fatal("--base-url requires a value")
			}
			gBaseURL = strings.TrimRight(args[i+1], "/")
			i += 2
		case strings.HasPrefix(a, "--base-url="):
			gBaseURL = strings.TrimRight(strings.TrimPrefix(a, "--base-url="), "/")
			i++
		case a == "--timeout":
			if i+1 >= len(args) {
				fatal("--timeout requires SECONDS")
			}
			gTimeout = atoiOrDie(args[i+1])
			i += 2
		case a == "--help", a == "-h":
			printRootHelp()
			os.Exit(0)
		default:
			// Subcommand reached — stop parsing globals.
			return args[i:]
		}
	}
	return args[i:]
}

func atoiOrDie(s string) int {
	n := 0
	for _, r := range s {
		if r < '0' || r > '9' {
			fatal("invalid number: %s", s)
		}
		n = n*10 + int(r-'0')
	}
	return n
}

func fatal(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "dss: "+format+"\n", args...)
	os.Exit(1)
}

func printRootHelp() {
	fmt.Fprintf(os.Stderr, "dss — DeepSearchStack CLI\n\n")
	fmt.Fprintf(os.Stderr, "Usage: dss [GLOBAL_FLAGS] <command> [args]\n\n")
	fmt.Fprintf(os.Stderr, "Commands:\n")
	for _, c := range commands {
		fmt.Fprintf(os.Stderr, "  %-14s %s\n", c.name, c.summary)
	}
	fmt.Fprintf(os.Stderr, "\nGlobal flags:\n")
	fmt.Fprintf(os.Stderr, "  --base-url URL    DSS nginx base (default %s)\n", gBaseURL)
	fmt.Fprintf(os.Stderr, "  --json            machine-readable JSON output\n")
	fmt.Fprintf(os.Stderr, "  --no-color        disable ANSI colors\n")
	fmt.Fprintf(os.Stderr, "  --timeout SECS    override default per-call timeout\n")
	fmt.Fprintf(os.Stderr, "\nRun  dss <command> --help  for command-specific flags.\n")
}

func runHelp(args []string) {
	if len(args) == 0 {
		printRootHelp()
		return
	}
	for _, c := range commands {
		if c.name == args[0] {
			c.run([]string{"--help"})
			return
		}
	}
	fmt.Fprintf(os.Stderr, "dss: unknown command %q\n", args[0])
	os.Exit(2)
}

// newClient builds a configured SDK client honoring global flags.
func newClient() *Client {
	c := NewClient(gBaseURL)
	if os.Getenv("DSS_DEBUG") != "" {
		c.Debug = true
	}
	return c
}

// emit writes JSON to stdout when --json is set, or hands off to the pretty
// callback otherwise. Subcommands call this at their final output step.
func emit(v any, pretty func()) {
	if gJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(v)
		return
	}
	pretty()
}

// withTimeout returns a ctx + cancel honoring --timeout if set, else the
// passed default.
func withTimeout(defaultSec int) (context.Context, context.CancelFunc) {
	secs := defaultSec
	if gTimeout > 0 {
		secs = gTimeout
	}
	return context.WithTimeout(context.Background(), durSec(secs))
}
