package main

import (
	"fmt"
	"os"
	"strings"
	"time"

	"golang.org/x/term"
)

// ANSI helpers — minimal, no external lipgloss dep. Disabled when --no-color
// is set or when stdout isn't a terminal.

func ansiEnabled() bool {
	if gNoColor {
		return false
	}
	if os.Getenv("NO_COLOR") != "" {
		return false
	}
	return term.IsTerminal(int(os.Stdout.Fd()))
}

func wrap(start, end, s string) string {
	if !ansiEnabled() {
		return s
	}
	return start + s + end
}

func dim(s string) string  { return wrap("\x1b[2m", "\x1b[0m", s) }
func bold(s string) string { return wrap("\x1b[1m", "\x1b[0m", s) }
func red(s string) string  { return wrap("\x1b[31m", "\x1b[0m", s) }
func grn(s string) string  { return wrap("\x1b[32m", "\x1b[0m", s) }
func ylw(s string) string  { return wrap("\x1b[33m", "\x1b[0m", s) }
func cyn(s string) string  { return wrap("\x1b[36m", "\x1b[0m", s) }
func mag(s string) string  { return wrap("\x1b[35m", "\x1b[0m", s) }

// durSec converts seconds → time.Duration. Used by withTimeout.
func durSec(s int) time.Duration { return time.Duration(s) * time.Second }

// printSeparator prints a horizontal rule to fit the terminal.
func printSeparator() {
	w := termWidth()
	fmt.Println(dim(strings.Repeat("─", w)))
}

func termWidth() int {
	w, _, err := term.GetSize(int(os.Stdout.Fd()))
	if err != nil || w < 20 {
		return 80
	}
	if w > 200 {
		return 200
	}
	return w
}

// truncate clamps a string to at most n chars (visible bytes) appending "…".
func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	if n < 2 {
		return s[:n]
	}
	return s[:n-1] + "…"
}

// printHeader emits a styled section header.
func printHeader(s string) {
	fmt.Println()
	fmt.Println(bold(cyn(s)))
}

// fmtBytes / fmtNum — small humanizers.
func fmtNum(n int) string {
	if n < 1000 {
		return fmt.Sprintf("%d", n)
	}
	if n < 1_000_000 {
		return fmt.Sprintf("%.1fk", float64(n)/1000)
	}
	return fmt.Sprintf("%.2fM", float64(n)/1_000_000)
}
