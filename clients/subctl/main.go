// subctl — Substrate control plane CLI.
//
// Talks to the API gateway over HTTP. No external dependencies beyond
// the Go standard library. Builds to a single static binary.
//
//	subctl status                  Service health
//	subctl workflow list           List workflows
//	subctl workflow run <name>     Execute a workflow
//	subctl workflow seo <topic>    Run seo_content_loop
//	subctl blog generate <topic>   Generate blog post
//	subctl blog stats              Blog stats
//	subctl ingest stats            Ingest stats
//	subctl ingest scan             Trigger feed scan
package main

import "github.com/substrate/subctl/cmd"

func main() {
	cmd.Run()
}
