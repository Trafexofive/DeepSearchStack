package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
)

// ─── ask ───────────────────────────────────────────────────────────────────
// Aggregate + synthesize, stream the answer to stdout.

func runAsk(args []string) {
	fs := flag.NewFlagSet("ask", flag.ExitOnError)
	maxResults := fs.Int("max-results", 12, "max sources to aggregate")
	maxScrape := fs.Int("max-scrape", 6, "max URLs to actually scrape")
	noScrape := fs.Bool("no-scrape", false, "skip scraping (faster, lower quality)")
	noReconcile := fs.Bool("no-reconcile", false, "skip cross-source reconciliation")
	noSynth := fs.Bool("no-synthesis", false, "skip synthesis (print sources + consensus only)")
	noWH := fs.Bool("no-warehouse", false, "exclude warehouse from search")
	providersCSV := fs.String("providers", "", "comma-separated provider whitelist")
	showSources := fs.Bool("show-sources", true, "print source list before the answer")
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: dss ask [flags] <query>\n\n")
		fs.PrintDefaults()
	}
	_ = fs.Parse(args)
	if fs.NArg() == 0 {
		fs.Usage()
		os.Exit(2)
	}
	query := strings.Join(fs.Args(), " ")

	c := newClient()
	ctx, cancel := withTimeout(180)
	defer cancel()

	req := AggregateReq{
		Query:           query,
		MaxResults:      *maxResults,
		IncludeWH:       !*noWH,
		Reconcile:       !*noReconcile,
		EnableScraping:  !*noScrape,
		MaxScrapeURLs:   *maxScrape,
		EnableSynthesis: false, // we synthesize separately so we can stream
	}
	if *providersCSV != "" {
		req.Providers = strings.Split(*providersCSV, ",")
	}

	resp, err := c.Aggregate(ctx, req)
	if err != nil {
		fatal("aggregate: %v", err)
	}

	if gJSON {
		// In JSON mode we return everything in one blob — no streaming.
		// Synthesize blocking and embed in the response.
		if !*noSynth {
			sources := make([]SynthesizeSource, 0, len(resp.Sources))
			for _, s := range resp.Sources {
				sources = append(sources, SynthesizeSource{
					Title: s.Title, URL: s.URL, Description: s.Description, Source: s.Source,
				})
			}
			ctx2, cancel2 := withTimeout(240)
			defer cancel2()
			var buf bytes.Buffer
			full, warn, err := c.SynthesizeStream(ctx2, SynthesizeReq{
				Query: query, Sources: sources,
			}, func(chunk string) { buf.WriteString(chunk) })
			if err != nil {
				resp.Synthesis = full + "\n[error: " + err.Error() + "]"
			} else {
				resp.Synthesis = full
				if warn != "" {
					resp.Synthesis += "\n[warning: " + warn + "]"
				}
			}
		}
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(resp)
		return
	}

	// Pretty output
	if *showSources {
		printSources(resp)
	}

	if *noSynth {
		return
	}

	// Stream synthesis
	printHeader("Answer")
	sources := make([]SynthesizeSource, 0, len(resp.Sources))
	for _, s := range resp.Sources {
		sources = append(sources, SynthesizeSource{
			Title: s.Title, URL: s.URL, Description: s.Description, Source: s.Source,
		})
	}
	ctx2, cancel2 := withTimeout(240)
	defer cancel2()
	_, warn, err := c.SynthesizeStream(ctx2, SynthesizeReq{
		Query: query, Sources: sources,
	}, func(chunk string) {
		fmt.Print(chunk)
		_ = os.Stdout.Sync()
	})
	fmt.Println()
	if warn != "" {
		fmt.Fprintln(os.Stderr, ylw("warning: "+warn))
	}
	if err != nil {
		fatal("synthesis: %v", err)
	}
}

func printSources(resp *AggregateResp) {
	printHeader(fmt.Sprintf("Sources (%d) — %dms",
		resp.TotalSources, resp.ExecutionTimeMS))
	w := termWidth()
	for i, s := range resp.Sources {
		title := s.Title
		if title == "" {
			title = "(no title)"
		}
		prov := s.Source
		if len(prov) > 12 {
			prov = prov[:12]
		}
		idx := fmt.Sprintf("%2d", i+1)
		head := bold(idx) + " " + cyn(fmt.Sprintf("[%-12s]", prov)) + " " +
			truncate(title, w-30)
		fmt.Println(head)
		fmt.Println("    " + dim(truncate(s.URL, w-6)))
		if s.Description != "" {
			fmt.Println("    " + dim(truncate(strings.ReplaceAll(s.Description, "\n", " "), w-6)))
		}
	}
	if len(resp.Consensus) > 0 {
		printHeader(fmt.Sprintf("Consensus (%d)", len(resp.Consensus)))
		for _, cl := range resp.Consensus {
			marker := dim("?")
			switch cl.Quality {
			case "verified":
				marker = grn("✓")
			case "probable":
				marker = ylw("~")
			}
			fmt.Printf("  %s [%.2f] %s\n", marker, cl.Confidence, cl.Claim)
		}
	}
}

// ─── search ────────────────────────────────────────────────────────────────
// Aggregate raw, print sources. No synthesis. Faster than `ask`.

func runSearch(args []string) {
	fs := flag.NewFlagSet("search", flag.ExitOnError)
	maxResults := fs.Int("max-results", 20, "max sources to aggregate")
	noScrape := fs.Bool("no-scrape", true, "skip scraping (default true for speed)")
	noWH := fs.Bool("no-warehouse", false, "exclude warehouse from search")
	providersCSV := fs.String("providers", "", "comma-separated provider whitelist")
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: dss search [flags] <query>\n\n")
		fs.PrintDefaults()
	}
	_ = fs.Parse(args)
	if fs.NArg() == 0 {
		fs.Usage()
		os.Exit(2)
	}
	query := strings.Join(fs.Args(), " ")

	c := newClient()
	ctx, cancel := withTimeout(60)
	defer cancel()

	req := AggregateReq{
		Query:           query,
		MaxResults:      *maxResults,
		IncludeWH:       !*noWH,
		Reconcile:       false,
		EnableScraping:  !*noScrape,
		EnableSynthesis: false,
	}
	if *providersCSV != "" {
		req.Providers = strings.Split(*providersCSV, ",")
	}

	resp, err := c.Aggregate(ctx, req)
	if err != nil {
		fatal("search: %v", err)
	}
	emit(resp, func() { printSources(resp) })
}

// ─── crawl ─────────────────────────────────────────────────────────────────

func runCrawl(args []string) {
	fs := flag.NewFlagSet("crawl", flag.ExitOnError)
	bypassCache := fs.Bool("no-cache", false, "bypass crawler cache")
	mode := fs.String("mode", "auto", "render mode: auto|fast|browser|ocr")
	timeoutS := fs.Int("crawl-timeout", 60, "crawler operation timeout (seconds)")
	bodyOnly := fs.Bool("body", false, "print the markdown body only (no metadata)")
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: dss crawl [flags] <url>\n\n")
		fs.PrintDefaults()
	}
	_ = fs.Parse(args)
	if fs.NArg() != 1 {
		fs.Usage()
		os.Exit(2)
	}

	c := newClient()
	ctx, cancel := withTimeout(*timeoutS + 30)
	defer cancel()
	resp, err := c.Crawl(ctx, CrawlReq{
		URL:         fs.Arg(0),
		BypassCache: *bypassCache,
		RenderMode:  *mode,
		Timeout:     *timeoutS,
	})
	if err != nil {
		fatal("crawl: %v", err)
	}
	if gJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(resp)
		return
	}
	if *bodyOnly {
		fmt.Println(resp.Markdown)
		return
	}
	if !resp.Success {
		fmt.Fprintln(os.Stderr, red(fmt.Sprintf("✗ crawl failed: type=%s msg=%s", resp.ErrorType, resp.ErrorMessage)))
		os.Exit(1)
	}
	printHeader(fmt.Sprintf("Crawled — %s (%dms)", resp.ExtractionMethod, 0))
	fmt.Printf("  %s\n", dim(resp.URL))
	if resp.Title != "" {
		fmt.Printf("  title: %s\n", bold(resp.Title))
	}
	fmt.Printf("  %s\n", dim(fmt.Sprintf("words=%s  domain=%s  method=%s",
		fmtNum(resp.WordCount), resp.SourceDomain, resp.ExtractionMethod)))
	printSeparator()
	fmt.Println(resp.Markdown)
}

// ─── render ────────────────────────────────────────────────────────────────

func runRender(args []string) {
	fs := flag.NewFlagSet("render", flag.ExitOnError)
	screenshot := fs.Bool("screenshot", false, "save a screenshot")
	ocr := fs.Bool("ocr", false, "run OCR on the screenshot")
	autoScroll := fs.Bool("auto-scroll", false, "scroll-to-bottom loop for lazy content")
	timeoutMS := fs.Int("timeout-ms", 25000, "navigation timeout (ms)")
	bodyOnly := fs.Bool("body", false, "print the article body only")
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: dss render [flags] <url>\n\n")
		fs.PrintDefaults()
	}
	_ = fs.Parse(args)
	if fs.NArg() != 1 {
		fs.Usage()
		os.Exit(2)
	}
	c := newClient()
	ctx, cancel := withTimeout(120)
	defer cancel()
	resp, err := c.Render(ctx, RenderReq{
		URL:        fs.Arg(0),
		Screenshot: *screenshot,
		RunOCR:     *ocr,
		AutoScroll: *autoScroll,
		TimeoutMS:  *timeoutMS,
	})
	if err != nil {
		fatal("render: %v", err)
	}
	if gJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(resp)
		return
	}
	if *bodyOnly {
		fmt.Println(resp.ArticleText)
		return
	}
	printHeader("Render")
	fmt.Printf("  %s\n", dim(resp.URL))
	if resp.ArticleTitle != "" {
		fmt.Printf("  title: %s\n", bold(resp.ArticleTitle))
	}
	fmt.Printf("  %s\n", dim(fmt.Sprintf("status=%d html=%dB elapsed=%dms blocked=%v",
		resp.Status, resp.HTMLLength, resp.ElapsedMS, resp.Blocked)))
	if resp.ScreenshotPath != "" {
		fmt.Printf("  screenshot: %s\n", resp.ScreenshotPath)
	}
	printSeparator()
	if resp.ArticleText != "" {
		fmt.Println(resp.ArticleText)
	} else if resp.OCRText != "" {
		fmt.Println(resp.OCRText)
	} else {
		fmt.Println(dim("(no extractable body — check blocked/status fields)"))
	}
}

// ─── ingest (local files) ──────────────────────────────────────────────────

func runIngest(args []string) {
	fs := flag.NewFlagSet("ingest", flag.ExitOnError)
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: dss ingest <file> [file...]\n\n")
		fmt.Fprintf(os.Stderr, "Streams each file to POST /crawl/ingest-file. Supports PDF/DOCX/EPUB/MD/TXT/RTF.\n")
	}
	_ = fs.Parse(args)
	if fs.NArg() == 0 {
		fs.Usage()
		os.Exit(2)
	}
	for _, path := range fs.Args() {
		f, err := os.Open(path)
		if err != nil {
			fmt.Fprintln(os.Stderr, red("skip "+path+": "+err.Error()))
			continue
		}
		req, _ := http.NewRequest("POST", gBaseURL+"/dss/crawl/ingest-file", f)
		req.Header.Set("Content-Type", "application/octet-stream")
		req.Header.Set("X-Filename", trailingFile(path))
		ctx, cancel := withTimeout(180)
		defer cancel()
		req = req.WithContext(ctx)
		r, err := newClient().HTTP.Do(req)
		f.Close()
		if err != nil {
			fmt.Fprintln(os.Stderr, red(path+": "+err.Error()))
			continue
		}
		body, _ := io.ReadAll(r.Body)
		r.Body.Close()
		if r.StatusCode != 200 {
			fmt.Fprintln(os.Stderr, red(fmt.Sprintf("%s: HTTP %d: %s", path, r.StatusCode, string(body))))
			continue
		}
		if gJSON {
			fmt.Println(string(body))
		} else {
			var resp struct {
				ID        int    `json:"id"`
				WordCount int    `json:"word_count"`
				Title     string `json:"title"`
				Extractor string `json:"extractor"`
			}
			_ = json.Unmarshal(body, &resp)
			fmt.Printf("  %s id=%d words=%s extractor=%s — %s\n",
				grn("✓"), resp.ID, fmtNum(resp.WordCount),
				resp.Extractor, truncate(resp.Title, 50))
		}
	}
}

func trailingFile(path string) string {
	for i := len(path) - 1; i >= 0; i-- {
		if path[i] == '/' || path[i] == '\\' {
			return path[i+1:]
		}
	}
	return path
}

// ─── ingest-site ───────────────────────────────────────────────────────────

func runIngestSite(args []string) {
	fs := flag.NewFlagSet("ingest-site", flag.ExitOnError)
	maxURLs := fs.Int("max-urls", 200, "max URLs to discover")
	concurrency := fs.Int("concurrency", 4, "concurrent crawls")
	sameHost := fs.Bool("same-host", true, "restrict to the same host")
	crawl := fs.Bool("crawl", true, "actually crawl (false = discover only)")
	fs.Usage = func() {
		fmt.Fprintf(os.Stderr, "Usage: dss ingest-site [flags] <url>\n\n")
		fs.PrintDefaults()
	}
	_ = fs.Parse(args)
	if fs.NArg() != 1 {
		fs.Usage()
		os.Exit(2)
	}
	payload := map[string]any{
		"url":            fs.Arg(0),
		"max_urls":       *maxURLs,
		"concurrency":    *concurrency,
		"same_host_only": *sameHost,
		"crawl":          *crawl,
	}
	body, _ := json.Marshal(payload)
	ctx, cancel := withTimeout(600)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST",
		gBaseURL+"/dss/crawl/ingest/site", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	r, err := newClient().HTTP.Do(req)
	if err != nil {
		fatal("ingest-site: %v", err)
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
		EntryURL   string         `json:"entry_url"`
		Discovered int            `json:"discovered"`
		Crawled    int            `json:"crawled"`
		OK         int            `json:"ok"`
		Failed     int            `json:"failed"`
		URLs       []string       `json:"urls"`
		Sources    map[string]int `json:"sources"`
		DurationMS int            `json:"duration_ms"`
	}
	_ = json.Unmarshal(respBody, &resp)
	printHeader(fmt.Sprintf("Site ingest — %s", resp.EntryURL))
	fmt.Printf("  discovered: %d  crawled: %d  ok: %d  failed: %d  took: %dms\n",
		resp.Discovered, resp.Crawled, resp.OK, resp.Failed, resp.DurationMS)
	fmt.Printf("  sources: %v\n", resp.Sources)
	fmt.Println()
	for i, u := range resp.URLs {
		if i >= 20 && len(resp.URLs) > 25 {
			fmt.Printf("  ... (%d more)\n", len(resp.URLs)-i)
			break
		}
		fmt.Printf("  • %s\n", truncate(u, termWidth()-6))
	}
}

// ─── warehouse ─────────────────────────────────────────────────────────────

func runWarehouse(args []string) {
	if len(args) == 0 {
		printWarehouseHelp()
		os.Exit(2)
	}
	sub, rest := args[0], args[1:]
	switch sub {
	case "list":
		runWHList(rest)
	case "search":
		runWHSearch(rest)
	case "hybrid":
		runWHHybrid(rest)
	case "get":
		runWHGet(rest)
	case "by-url":
		runWHByURL(rest)
	case "stats":
		runWHStats(rest)
	case "help", "--help", "-h":
		printWarehouseHelp()
	default:
		fmt.Fprintf(os.Stderr, "dss warehouse: unknown subcommand %q\n", sub)
		printWarehouseHelp()
		os.Exit(2)
	}
}

func printWarehouseHelp() {
	fmt.Fprintf(os.Stderr, "Usage: dss warehouse <subcommand>\n\n")
	fmt.Fprintf(os.Stderr, "  list    [--limit N] [--domain D]      List recent rows\n")
	fmt.Fprintf(os.Stderr, "  search  [--domain D] [--limit N] Q    FTS5 search\n")
	fmt.Fprintf(os.Stderr, "  hybrid  [--limit N] Q                 FTS5 + vector hybrid (RRF)\n")
	fmt.Fprintf(os.Stderr, "  get     <id>                          Get row by id\n")
	fmt.Fprintf(os.Stderr, "  by-url  <url>                         Get row by exact URL\n")
	fmt.Fprintf(os.Stderr, "  stats                                 Warehouse stats\n")
}

func runWHList(args []string) {
	fs := flag.NewFlagSet("warehouse list", flag.ExitOnError)
	limit := fs.Int("limit", 30, "max rows")
	domain := fs.String("domain", "", "filter by domain")
	category := fs.String("category", "", "filter by category (doc|paper|news|...)")
	_ = fs.Parse(args)
	c := newClient()
	ctx, cancel := withTimeout(15)
	defer cancel()
	hits, err := c.WarehouseListEx(ctx, *limit, *domain, *category)
	if err != nil {
		fatal("list: %v", err)
	}
	emit(hits, func() { printWHHits(hits) })
}

func runWHSearch(args []string) {
	fs := flag.NewFlagSet("warehouse search", flag.ExitOnError)
	domain := fs.String("domain", "", "filter by domain")
	limit := fs.Int("limit", 20, "max hits")
	_ = fs.Parse(args)
	if fs.NArg() == 0 {
		fatal("warehouse search: query required")
	}
	q := strings.Join(fs.Args(), " ")
	c := newClient()
	ctx, cancel := withTimeout(15)
	defer cancel()
	hits, err := c.WarehouseSearch(ctx, q, *domain, *limit)
	if err != nil {
		fatal("search: %v", err)
	}
	emit(hits, func() { printWHHits(hits) })
}

func runWHHybrid(args []string) {
	fs := flag.NewFlagSet("warehouse hybrid", flag.ExitOnError)
	limit := fs.Int("limit", 20, "max hits")
	_ = fs.Parse(args)
	if fs.NArg() == 0 {
		fatal("warehouse hybrid: query required")
	}
	q := strings.Join(fs.Args(), " ")
	c := newClient()
	ctx, cancel := withTimeout(25)
	defer cancel()
	resp, err := c.HybridSearch(ctx, q, *limit)
	if err != nil {
		fatal("hybrid: %v", err)
	}
	if gJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(resp)
		return
	}
	printHeader(fmt.Sprintf("Hybrid — q=%q  hits=%d", q, len(resp.Hits)))
	w := termWidth()
	for i, h := range resp.Hits {
		badges := ""
		if h.FtsRank != nil {
			badges += fmt.Sprintf("[fts#%d] ", *h.FtsRank)
		}
		if h.VecRank != nil {
			badges += fmt.Sprintf("[vec#%d] ", *h.VecRank)
		}
		title := h.Title
		if title == "" {
			title = "(no title)"
		}
		fmt.Printf("  %s  %s  %s\n",
			bold(fmt.Sprintf("%2d", i+1)),
			cyn(fmt.Sprintf("id=%-4d %sw", h.ID, fmtNum(h.WordCount))),
			truncate(title, w-25),
		)
		if h.URL != "" {
			fmt.Printf("      %s\n", dim(truncate(h.URL, w-6)))
		}
		if badges != "" {
			fmt.Printf("      %s\n", dim(badges))
		}
	}
}

func runWHGet(args []string) {
	fs := flag.NewFlagSet("warehouse get", flag.ExitOnError)
	bodyOnly := fs.Bool("body", false, "print markdown body only")
	_ = fs.Parse(args)
	if fs.NArg() != 1 {
		fatal("warehouse get: id required")
	}
	id := atoiOrDie(fs.Arg(0))
	c := newClient()
	ctx, cancel := withTimeout(10)
	defer cancel()
	row, err := c.WarehouseGet(ctx, id)
	if err != nil {
		fatal("get: %v", err)
	}
	if gJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(row)
		return
	}
	if *bodyOnly {
		fmt.Println(row.Markdown)
		return
	}
	printWHRow(row)
}

func runWHByURL(args []string) {
	fs := flag.NewFlagSet("warehouse by-url", flag.ExitOnError)
	bodyOnly := fs.Bool("body", false, "print markdown body only")
	_ = fs.Parse(args)
	if fs.NArg() != 1 {
		fatal("warehouse by-url: url required")
	}
	c := newClient()
	ctx, cancel := withTimeout(10)
	defer cancel()
	row, err := c.WarehouseGetByURL(ctx, fs.Arg(0))
	if err != nil {
		fatal("by-url: %v", err)
	}
	if gJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(row)
		return
	}
	if *bodyOnly {
		fmt.Println(row.Markdown)
		return
	}
	printWHRow(row)
}

func runWHStats(args []string) {
	c := newClient()
	ctx, cancel := withTimeout(15)
	defer cancel()
	st, err := c.WarehouseStats(ctx)
	if err != nil {
		fatal("stats: %v", err)
	}
	if gJSON {
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(st)
		return
	}
	printHeader("Warehouse stats")
	fmt.Printf("  entries:        %s\n", fmtNum(st.TotalEntries))
	fmt.Printf("  total words:    %s\n", fmtNum(st.TotalWords))
	fmt.Printf("  db size:        %.1f MB\n", st.DBSizeMB)
	if len(st.Domains) > 0 {
		printHeader("Top domains")
		for i, d := range st.Domains {
			if i >= 15 {
				break
			}
			name, _ := d["domain"].(string)
			cnt, _ := d["count"].(float64)
			fmt.Printf("  %-32s %s\n", truncate(name, 32), fmtNum(int(cnt)))
		}
	}
}

func printWHHits(hits []WarehouseHit) {
	if len(hits) == 0 {
		fmt.Println(dim("  (no rows)"))
		return
	}
	w := termWidth()
	for i, h := range hits {
		title := h.Title
		if title == "" {
			title = "(no title)"
		}
		fmt.Printf("  %s  %s  %s\n",
			bold(fmt.Sprintf("%2d", i+1)),
			cyn(fmt.Sprintf("id=%-4d %sw %-22s",
				h.ID, fmtNum(h.WordCount),
				truncate(h.SourceDomain, 22))),
			truncate(title, w-50),
		)
		if h.URL != "" {
			fmt.Printf("      %s\n", dim(truncate(h.URL, w-6)))
		}
	}
}

func printWHRow(r *WarehouseRow) {
	printHeader(fmt.Sprintf("Row %d", r.ID))
	fmt.Printf("  url:        %s\n", r.URL)
	if r.Title != "" {
		fmt.Printf("  title:      %s\n", bold(r.Title))
	}
	if r.Author != "" {
		fmt.Printf("  author:     %s\n", r.Author)
	}
	if r.Published != "" {
		fmt.Printf("  published:  %s\n", r.Published)
	}
	fmt.Printf("  %s\n", dim(fmt.Sprintf("words=%s  domain=%s  lang=%s  ingested=%s",
		fmtNum(r.WordCount), r.SourceDomain, r.Language, r.IngestedAt)))
	printSeparator()
	fmt.Println(r.Markdown)
}

// ─── models / providers / health ──────────────────────────────────────────

func runModels(args []string) {
	c := newClient()
	ctx, cancel := withTimeout(10)
	defer cancel()
	models, err := c.Models(ctx)
	if err != nil {
		fatal("models: %v", err)
	}
	emit(models, func() {
		printHeader(fmt.Sprintf("Models (%d)", len(models)))
		for _, m := range models {
			fmt.Printf("  %s  %s\n", cyn(fmt.Sprintf("[%-10s]", m.Provider)), m.ID)
		}
	})
}

func runProviders(args []string) {
	c := newClient()
	ctx, cancel := withTimeout(10)
	defer cancel()
	ps, err := c.Providers(ctx)
	if err != nil {
		fatal("providers: %v", err)
	}
	emit(ps, func() {
		printHeader(fmt.Sprintf("Search providers (%d)", len(ps)))
		for name, status := range ps {
			tag := grn(status)
			if status != "ready" && status != "ok" {
				tag = ylw(status)
			}
			fmt.Printf("  %-20s %s\n", name, tag)
		}
	})
}

func runHealth(args []string) {
	c := newClient()
	ctx, cancel := withTimeout(5)
	defer cancel()
	err := c.Health(ctx)
	if gJSON {
		out := map[string]any{"ok": err == nil}
		if err != nil {
			out["error"] = err.Error()
		}
		enc := json.NewEncoder(os.Stdout)
		enc.SetIndent("", "  ")
		_ = enc.Encode(out)
	} else {
		if err != nil {
			fmt.Println(red("✗ unhealthy: " + err.Error()))
			os.Exit(1)
		}
		fmt.Println(grn("✓ stack ok @ ") + gBaseURL)
	}
}

// quiet the unused-import linter — url is used via the SDK.
var _ = url.QueryEscape
