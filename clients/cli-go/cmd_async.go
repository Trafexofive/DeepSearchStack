package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// ─── jobs ──────────────────────────────────────────────────────────────────
// Async ingest jobs (queue/list/follow). Sub-commands:
//   dss jobs              # list recent jobs
//   dss jobs <id>         # get one job by id
//   dss jobs queue-site <url>  [--max-urls N --concurrency N]
//   dss jobs queue-urls  <url>... [--concurrency N]
//   dss jobs follow <id>  # tail the progress until done

func runJobs(args []string) {
	if len(args) == 0 {
		runJobsList(nil)
		return
	}
	// Flags first → treat as list flags (`dss jobs --status done`).
	if strings.HasPrefix(args[0], "-") {
		runJobsList(args)
		return
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "list":
		runJobsList(rest)
	case "get":
		runJobsGet(rest)
	case "queue-site":
		runJobsQueueSite(rest)
	case "queue-urls":
		runJobsQueueURLs(rest)
	case "follow":
		runJobsFollow(rest)
	default:
		// numeric → shorthand for `get N`
		if isAllDigits(sub) {
			runJobsGet(args)
			return
		}
		fmt.Fprintf(os.Stderr, "dss jobs: unknown subcommand %q\n", sub)
		os.Exit(2)
	}
}

func isAllDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return false
		}
	}
	return true
}

func runJobsList(args []string) {
	fs := flag.NewFlagSet("jobs list", flag.ExitOnError)
	limit := fs.Int("limit", 30, "max jobs")
	status := fs.String("status", "", "filter (queued|running|done|failed)")
	_ = fs.Parse(args)
	u := fmt.Sprintf("%s/dss/crawl/ingest-jobs?limit=%d", gBaseURL, *limit)
	if *status != "" {
		u += "&status=" + *status
	}
	ctx, cancel := withTimeout(10)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", u, nil)
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("jobs list: %v", err)
	}
	defer r.Body.Close()
	body, _ := io.ReadAll(r.Body)
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(body))
	}
	if gJSON {
		fmt.Println(string(body))
		return
	}
	var resp struct {
		Jobs []map[string]any `json:"jobs"`
	}
	_ = json.Unmarshal(body, &resp)
	printHeader(fmt.Sprintf("Ingest jobs (%d)", len(resp.Jobs)))
	for _, j := range resp.Jobs {
		colorStatus := dim(asString(j["status"]))
		switch asString(j["status"]) {
		case "queued":
			colorStatus = ylw("queued")
		case "running":
			colorStatus = cyn("running")
		case "done":
			colorStatus = grn("done")
		case "failed":
			colorStatus = red("failed")
		}
		entry := asString(j["entry_url"])
		if entry == "" {
			entry = fmt.Sprintf("[%s urls]", asString(j["kind"]))
		}
		fmt.Printf("  %s  %s  %s  %s\n",
			bold(fmt.Sprintf("#%-3d", asInt(j["id"]))),
			colorStatus,
			dim(fmt.Sprintf("done=%d/%d ok=%d fail=%d",
				asInt(j["completed"]), asInt(j["discovered"]),
				asInt(j["ok"]), asInt(j["failed"]))),
			truncate(entry, termWidth()-50),
		)
	}
}

func runJobsGet(args []string) {
	if len(args) == 0 {
		fatal("dss jobs <id>")
	}
	id := atoiOrDie(args[0])
	includeURLs := false
	for _, a := range args[1:] {
		if a == "--urls" {
			includeURLs = true
		}
	}
	u := fmt.Sprintf("%s/dss/crawl/ingest-jobs/%d", gBaseURL, id)
	if includeURLs {
		u += "?include_urls=true"
	}
	ctx, cancel := withTimeout(10)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", u, nil)
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("jobs get: %v", err)
	}
	defer r.Body.Close()
	body, _ := io.ReadAll(r.Body)
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(body))
	}
	if gJSON {
		fmt.Println(string(body))
		return
	}
	var j map[string]any
	_ = json.Unmarshal(body, &j)
	printHeader(fmt.Sprintf("Job #%d", asInt(j["id"])))
	fmt.Printf("  status:      %s\n", j["status"])
	fmt.Printf("  kind:        %s\n", j["kind"])
	if e := asString(j["entry_url"]); e != "" {
		fmt.Printf("  entry_url:   %s\n", e)
	}
	fmt.Printf("  progress:    %d / %d  (ok=%d failed=%d)\n",
		asInt(j["completed"]), asInt(j["discovered"]),
		asInt(j["ok"]), asInt(j["failed"]))
	if err := asString(j["error"]); err != "" {
		fmt.Printf("  error:       %s\n", red(err))
	}
}

func runJobsQueueSite(args []string) {
	fs := flag.NewFlagSet("jobs queue-site", flag.ExitOnError)
	maxURLs := fs.Int("max-urls", 200, "max URLs to discover")
	concurrency := fs.Int("concurrency", 4, "concurrent crawls")
	sameHost := fs.Bool("same-host", true, "restrict to the same host")
	_ = fs.Parse(args)
	if fs.NArg() != 1 {
		fatal("dss jobs queue-site <url>")
	}
	payload := map[string]any{
		"url":            fs.Arg(0),
		"max_urls":       *maxURLs,
		"concurrency":    *concurrency,
		"same_host_only": *sameHost,
		"crawl":          true,
	}
	body, _ := json.Marshal(payload)
	ctx, cancel := withTimeout(30)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST",
		gBaseURL+"/dss/crawl/ingest/site/async", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("queue-site: %v", err)
	}
	defer r.Body.Close()
	respBody, _ := io.ReadAll(r.Body)
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(respBody))
	}
	if gJSON {
		fmt.Println(string(respBody))
		return
	}
	var resp struct {
		JobID    int    `json:"job_id"`
		Status   string `json:"status"`
		EntryURL string `json:"entry_url"`
	}
	_ = json.Unmarshal(respBody, &resp)
	fmt.Printf("%s queued job %s %s\n",
		grn("✓"), bold(fmt.Sprintf("#%d", resp.JobID)),
		dim("("+resp.EntryURL+")"))
	fmt.Printf("  follow: %s\n", dim(fmt.Sprintf("dss jobs follow %d", resp.JobID)))
}

func runJobsQueueURLs(args []string) {
	fs := flag.NewFlagSet("jobs queue-urls", flag.ExitOnError)
	concurrency := fs.Int("concurrency", 4, "concurrent crawls")
	_ = fs.Parse(args)
	if fs.NArg() == 0 {
		fatal("dss jobs queue-urls <url> [url...]")
	}
	payload := map[string]any{
		"urls":            fs.Args(),
		"concurrency":     *concurrency,
		"source_provider": "urls-ingest",
	}
	body, _ := json.Marshal(payload)
	ctx, cancel := withTimeout(30)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST",
		gBaseURL+"/dss/crawl/ingest/urls/async", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("queue-urls: %v", err)
	}
	defer r.Body.Close()
	respBody, _ := io.ReadAll(r.Body)
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(respBody))
	}
	if gJSON {
		fmt.Println(string(respBody))
		return
	}
	var resp struct {
		JobID  int    `json:"job_id"`
		Status string `json:"status"`
	}
	_ = json.Unmarshal(respBody, &resp)
	fmt.Printf("%s queued job %s — %d URLs\n",
		grn("✓"), bold(fmt.Sprintf("#%d", resp.JobID)), fs.NArg())
	fmt.Printf("  follow: %s\n", dim(fmt.Sprintf("dss jobs follow %d", resp.JobID)))
}

func runJobsFollow(args []string) {
	if len(args) == 0 {
		fatal("dss jobs follow <id>")
	}
	id := atoiOrDie(args[0])
	prevCompleted := -1
	for {
		ctx, cancel := withTimeout(8)
		req, _ := http.NewRequestWithContext(ctx,
			"GET", fmt.Sprintf("%s/dss/crawl/ingest-jobs/%d", gBaseURL, id), nil)
		r, err := newClient().HTTP.Do(req)
		cancel()
		if err != nil {
			fatal("follow: %v", err)
		}
		body, _ := io.ReadAll(r.Body)
		r.Body.Close()
		if r.StatusCode != 200 {
			fatal("HTTP %d: %s", r.StatusCode, string(body))
		}
		var j map[string]any
		_ = json.Unmarshal(body, &j)
		status := asString(j["status"])
		done := asInt(j["completed"])
		total := asInt(j["discovered"])
		ok := asInt(j["ok"])
		failed := asInt(j["failed"])
		if done != prevCompleted || prevCompleted < 0 {
			prevCompleted = done
			line := fmt.Sprintf("[%s] %d/%d  ok=%d failed=%d",
				status, done, total, ok, failed)
			fmt.Printf("\r%s%s", strings.Repeat(" ", 60), "\r")
			fmt.Print(line)
			_ = os.Stdout.Sync()
		}
		if status == "done" || status == "failed" {
			fmt.Println()
			if status == "failed" {
				fmt.Println(red("failed: " + asString(j["error"])))
				os.Exit(1)
			}
			return
		}
		time.Sleep(1500 * time.Millisecond)
	}
}

func asString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}
func asInt(v any) int {
	switch x := v.(type) {
	case float64:
		return int(x)
	case int:
		return x
	}
	return 0
}

// ─── watch / watches ───────────────────────────────────────────────────────

func runWatch(args []string) {
	fs := flag.NewFlagSet("watch", flag.ExitOnError)
	name := fs.String("name", "", "human label for the feed")
	every := fs.Int("every", 3600, "poll interval seconds (60-86400)")
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: dss watch [--name X] [--every SECS] <feed-url>\n")
	}
	_ = fs.Parse(args)
	if fs.NArg() != 1 {
		fs.Usage()
		os.Exit(2)
	}
	payload := map[string]any{
		"feed_url":     fs.Arg(0),
		"name":         *name,
		"interval_sec": *every,
	}
	body, _ := json.Marshal(payload)
	ctx, cancel := withTimeout(10)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST",
		gBaseURL+"/dss/warehouse/watch/feeds", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("watch: %v", err)
	}
	defer r.Body.Close()
	respBody, _ := io.ReadAll(r.Body)
	if r.StatusCode == 409 {
		fmt.Fprintln(os.Stderr, ylw("already watched"))
		os.Exit(1)
	}
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(respBody))
	}
	if gJSON {
		fmt.Println(string(respBody))
		return
	}
	var resp struct {
		ID          int    `json:"id"`
		FeedURL     string `json:"feed_url"`
		IntervalSec int    `json:"interval_sec"`
	}
	_ = json.Unmarshal(respBody, &resp)
	fmt.Printf("%s watching %s — id=%d every=%ds\n",
		grn("✓"), resp.FeedURL, resp.ID, resp.IntervalSec)
}

func runWatches(args []string) {
	if len(args) == 0 {
		runWatchesList(nil)
		return
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "list":
		runWatchesList(rest)
	case "poll":
		runWatchesPoll(rest)
	case "rm", "remove":
		runWatchesRemove(rest)
	default:
		fmt.Fprintf(os.Stderr, "dss watches: list|poll <id>|rm <id>\n")
		os.Exit(2)
	}
}

func runWatchesList(args []string) {
	ctx, cancel := withTimeout(10)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET",
		gBaseURL+"/dss/warehouse/watch/feeds", nil)
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("watches: %v", err)
	}
	defer r.Body.Close()
	body, _ := io.ReadAll(r.Body)
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(body))
	}
	if gJSON {
		fmt.Println(string(body))
		return
	}
	var resp struct {
		Feeds []map[string]any `json:"feeds"`
	}
	_ = json.Unmarshal(body, &resp)
	printHeader(fmt.Sprintf("Watched feeds (%d)", len(resp.Feeds)))
	for _, f := range resp.Feeds {
		every := asInt(f["interval_sec"])
		lastStatus := asString(f["last_status"])
		if lastStatus == "" {
			lastStatus = dim("(never polled)")
		}
		fmt.Printf("  %s  every %ds  %s\n",
			bold(fmt.Sprintf("#%-2d", asInt(f["id"]))), every, lastStatus)
		fmt.Printf("      %s\n", asString(f["feed_url"]))
		if n := asString(f["name"]); n != "" {
			fmt.Printf("      name: %s\n", dim(n))
		}
		fmt.Printf("      %s\n", dim(fmt.Sprintf("polls=%d  new=%d  ingested=%d",
			asInt(f["total_polls"]), asInt(f["total_new_entries"]),
			asInt(f["total_ingested"]))))
	}
}

func runWatchesPoll(args []string) {
	if len(args) == 0 {
		fatal("dss watches poll <id>")
	}
	id := atoiOrDie(args[0])
	ctx, cancel := withTimeout(45)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST",
		fmt.Sprintf("%s/dss/warehouse/watch/feeds/%d/poll-now", gBaseURL, id), nil)
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("poll: %v", err)
	}
	defer r.Body.Close()
	body, _ := io.ReadAll(r.Body)
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(body))
	}
	if gJSON {
		fmt.Println(string(body))
		return
	}
	var resp map[string]any
	_ = json.Unmarshal(body, &resp)
	fmt.Printf("%s status=%s  new=%d  queued=%d\n",
		grn("✓"), asString(resp["status"]),
		asInt(resp["new_entries"]), asInt(resp["queued"]))
}

func runWatchesRemove(args []string) {
	if len(args) == 0 {
		fatal("dss watches rm <id>")
	}
	id := atoiOrDie(args[0])
	ctx, cancel := withTimeout(10)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "DELETE",
		fmt.Sprintf("%s/dss/warehouse/watch/feeds/%d", gBaseURL, id), nil)
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("remove: %v", err)
	}
	defer r.Body.Close()
	if r.StatusCode == 404 {
		fatal("feed not found")
	}
	body, _ := io.ReadAll(r.Body)
	if r.StatusCode != 200 {
		fatal("HTTP %d: %s", r.StatusCode, string(body))
	}
	fmt.Printf("%s removed feed #%d\n", grn("✓"), id)
}
