package cmd

import (
	"fmt"
	"os"
	"sort"
	"strings"
)

func statusCmd(args []string) {
	baseURL, _ := parseFlags(args)
	initClient(baseURL)

	h, err := c.Health()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Substrate %s — %s\n\n", h.Version, statusEmoji(h.Status))

	// Sort service names for consistent output
	names := make([]string, 0, len(h.Services))
	for name := range h.Services {
		names = append(names, name)
	}
	sort.Strings(names)

	healthy := 0
	for _, name := range names {
		state := h.Services[name]
		icon := "●"
		color := "\033[32m" // green
		if state != "healthy" {
			color = "\033[31m" // red
		} else {
			healthy++
		}
		fmt.Printf("  %s%s %-16s \033[0m%s\n", color, icon, name, state)
	}

	fmt.Printf("\n%d/%d healthy\n", healthy, len(names))
}

func statusEmoji(status string) string {
	switch status {
	case "ok":
		return "\033[32m●\033[0m"
	case "degraded":
		return "\033[33m◐\033[0m"
	default:
		return "\033[31m○\033[0m"
	}
}

// Emoji returns a single emoji status icon (without ANSI).
func Emoji(status string) string {
	switch status {
	case "completed", "healthy", "ok":
		return "✅"
	case "failed":
		return "❌"
	case "skipped":
		return "⏭️"
	default:
		return "●"
	}
}

// Truncate returns s truncated to maxLen with "..." suffix.
func Truncate(s string, maxLen int) string {
	s = strings.TrimSpace(strings.ReplaceAll(s, "\n", " "))
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen-3] + "..."
}
