package cmd

import (
	"fmt"
	"os"
)

func blogCmd(args []string) {
	baseURL, fs := parseFlags(args)

	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" {
		fmt.Print(`Usage:
  subctl blog generate <topic>   Generate a blog post
  subctl blog stats               Blog generation statistics

Examples:
  subctl blog generate "What is WebAssembly?"
  subctl blog stats
`)
		return
	}

	sub := args[0]
	rest := args[1:]

	initClient(baseURL)

	switch sub {
	case "generate", "gen":
		blogGenerate(rest)
	case "stats", "stat":
		blogStats()
	default:
		fmt.Fprintf(os.Stderr, "unknown blog subcommand: %s\n", sub)
		os.Exit(1)
	}
	_ = fs
}

func blogGenerate(args []string) {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "usage: subctl blog generate <topic>")
		os.Exit(1)
	}
	topic := args[0]

	fmt.Printf("▶ Generating blog post: %s\n", topic)
	fmt.Println("  (calling blog_generator via DeepSeek — ~30-45s)\n")

	result, err := c.GenerateBlog(topic, "", "", 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("ID:       %s\n", result.ID)
	fmt.Printf("Model:    %s\n", result.Model)
	fmt.Printf("Tokens:   %d\n", result.Usage.TotalTokens)
	fmt.Printf("Cost:     $%.6f\n", result.CostUSD)
	fmt.Printf("Duration: %dms\n", result.DurationMs)
	fmt.Printf("Content:  %d chars\n\n", len(result.Content))

	// Print first 300 chars as preview
	preview := result.Content
	if len(preview) > 300 {
		preview = preview[:300] + "..."
	}
	fmt.Println(preview)
}

func blogStats() {
	stats, err := c.BlogStats()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Blog Generator Statistics\n")
	fmt.Printf("─────────────────────────\n")
	fmt.Printf("Generations:  %d\n", stats.TotalGenerations)
	fmt.Printf("Total tokens: %d\n", stats.TotalTokens)
	fmt.Printf("Total cost:   $%.6f\n", stats.TotalCostUSD)
	fmt.Printf("Avg duration: %.0fms\n", stats.AvgDurationMs)
}
