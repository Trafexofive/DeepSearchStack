package cmd

import (
	"fmt"
	"os"
)

func ingestCmd(args []string) {
	baseURL, fs := parseFlags(args)

	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" {
		fmt.Print(`Usage:
  subctl ingest stats            Ingest pipeline statistics
  subctl ingest scan              Trigger manual feed scan

Examples:
  subctl ingest stats
  subctl ingest scan
`)
		return
	}

	sub := args[0]
	initClient(baseURL)

	switch sub {
	case "stats", "stat":
		ingestStats()
	case "scan":
		ingestScan()
	default:
		fmt.Fprintf(os.Stderr, "unknown ingest subcommand: %s\n", sub)
		os.Exit(1)
	}
	_ = fs
}

func ingestStats() {
	stats, err := c.IngestStats()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Ingest Pipeline\n")
	fmt.Printf("───────────────\n")
	fmt.Printf("Feeds configured: %d\n", stats.FeedsConfigured)
	fmt.Printf("Feeds watched:    %d\n", stats.FeedsWatched)
	fmt.Printf("Entries detected: %d\n", stats.EntriesDetected)
	fmt.Printf("Posts generated:  %d\n", stats.PostsGenerated)
	fmt.Printf("Drafts stored:    %d\n", stats.DraftsCount)
	fmt.Printf("Errors:           %d\n", stats.Errors)
	if stats.LastScan != "" {
		fmt.Printf("Last scan:        %s\n", stats.LastScan)
	}
}

func ingestScan() {
	fmt.Println("▶ Triggering feed scan...")
	result, err := c.ScanFeeds()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
	scanned := result["scanned"]
	fmt.Printf("Scanned %v feeds — check 'subctl ingest stats' for results\n", scanned)
}
