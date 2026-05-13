// Package cmd implements subctl CLI commands using only the standard library.
package cmd

import (
	"flag"
	"fmt"
	"os"

	"github.com/substrate/subctl/pkg/client"
)

var c *client.Client

func initClient(baseURL string) {
	if c == nil {
		c = client.New(baseURL)
	}
}

// Run dispatches subcommands from os.Args.
func Run() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(1)
	}

	cmd := os.Args[1]
	args := os.Args[2:]

	switch cmd {
	case "status":
		statusCmd(args)
	case "workflow":
		workflowCmd(args)
	case "blog":
		blogCmd(args)
	case "ingest":
		ingestCmd(args)
	case "help", "-h", "--help":
		usage()
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", cmd)
		usage()
		os.Exit(1)
	}
}

func usage() {
	fmt.Print(`subctl — Substrate control plane CLI

Usage:
  subctl status                  Service health dashboard
  subctl workflow list           List available workflows
  subctl workflow run <name>     Execute a workflow
  subctl workflow seo <topic>    Run seo_content_loop
  subctl blog generate <topic>   Generate a blog post
  subctl blog stats              Blog generation statistics
  subctl ingest stats            Ingest pipeline statistics
  subctl ingest scan             Trigger feed scan

Flags:
  -url string   API gateway URL (default "http://localhost:80")
  -k string     API key (JWT bearer token)

Environment:
  SUBSTRATE_URL   API gateway URL

Examples:
  subctl -url http://myhost:8080 status
  subctl workflow run seo_content_loop
  subctl blog generate "Rust async executors"
  SUBSTRATE_URL=http://10.0.0.1:80 subctl status
`)
}

func parseFlags(args []string) (baseURL string, fs *flag.FlagSet) {
	fs = flag.NewFlagSet("subctl", flag.ExitOnError)
	fs.StringVar(&baseURL, "url", "", "API gateway URL (default http://localhost:80)")
	fs.Parse(args)

	if baseURL == "" {
		baseURL = os.Getenv("SUBSTRATE_URL")
	}
	if baseURL == "" {
		baseURL = "http://localhost:80"
	}
	return baseURL, fs
}
