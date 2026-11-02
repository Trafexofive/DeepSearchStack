package main

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

// Live integration tests — require the stack on http://localhost:8083.
// Skip cleanly if the stack is down (so CI without the stack passes).

func baseURL() string {
	if u := os.Getenv("DSS_BASE_URL"); u != "" {
		return u
	}
	return "http://localhost:8083"
}

func TestHealth(t *testing.T) {
	c := NewClient(baseURL())
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := c.Health(ctx); err != nil {
		t.Skipf("stack down: %v", err)
	}
}

func TestModelsCatalog(t *testing.T) {
	c := NewClient(baseURL())
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := c.Health(ctx); err != nil {
		t.Skipf("stack down")
	}
	ms, err := c.Models(ctx)
	if err != nil {
		t.Fatalf("Models: %v", err)
	}
	if len(ms) == 0 {
		t.Fatalf("no models in catalog")
	}
	t.Logf("got %d models across providers", len(ms))
}

func TestProviders(t *testing.T) {
	c := NewClient(baseURL())
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := c.Health(ctx); err != nil {
		t.Skipf("stack down")
	}
	p, err := c.Providers(ctx)
	if err != nil {
		t.Fatalf("Providers: %v", err)
	}
	if len(p) < 5 {
		t.Fatalf("expected ≥5 providers, got %d: %v", len(p), p)
	}
	t.Logf("providers: %v", p)
}

func TestWarehouseListAndStats(t *testing.T) {
	c := NewClient(baseURL())
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := c.Health(ctx); err != nil {
		t.Skipf("stack down")
	}
	hits, err := c.WarehouseList(ctx, 5, "")
	if err != nil {
		t.Fatalf("WarehouseList: %v", err)
	}
	t.Logf("got %d recent rows", len(hits))
	if len(hits) > 0 {
		first := hits[0]
		if first.ID <= 0 || first.URL == "" {
			t.Fatalf("malformed row: %+v", first)
		}
		t.Logf("first row id=%d wc=%d %s", first.ID, first.WordCount, first.SourceDomain)
	}
	s, err := c.WarehouseStats(ctx)
	if err != nil {
		t.Fatalf("WarehouseStats: %v", err)
	}
	if s.TotalEntries <= 0 {
		t.Fatalf("expected warehouse entries, got %d", s.TotalEntries)
	}
	t.Logf("warehouse: %d entries, %.2f MB", s.TotalEntries, s.DBSizeMB)
}

func TestAggregateRealAttribution(t *testing.T) {
	c := NewClient(baseURL())
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	if err := c.Health(ctx); err != nil {
		t.Skipf("stack down")
	}
	resp, err := c.Aggregate(ctx, AggregateReq{
		Query:           "how does kubernetes scheduler work in 2025",
		MaxResults:      15,
		IncludeWH:       true,
		Reconcile:       false,
		EnableScraping:  false,
		EnableSynthesis: false,
	})
	if err != nil {
		t.Fatalf("Aggregate: %v", err)
	}
	if resp.TotalSources == 0 {
		t.Fatalf("zero sources from aggregate")
	}
	// The N1+attribution fix: meta-search hits should NOT all say "searxng".
	srcs := map[string]int{}
	for _, s := range resp.Sources {
		srcs[s.Source]++
	}
	if _, onlySearxng := srcs["searxng"]; onlySearxng && len(srcs) == 1 {
		t.Fatalf("source attribution regressed — every hit labeled 'searxng' (post-fix expected real origins)")
	}
	t.Logf("aggregated %d sources, %d distinct attributions: %v",
		resp.TotalSources, len(srcs), srcs)
}

func TestCrawlEscalation(t *testing.T) {
	c := NewClient(baseURL())
	ctx, cancel := context.WithTimeout(context.Background(), 90*time.Second)
	defer cancel()
	if err := c.Health(ctx); err != nil {
		t.Skipf("stack down")
	}
	r, err := c.Crawl(ctx, CrawlReq{
		URL:               "https://news.ycombinator.com/",
		Timeout:           60,
		BypassCache:       true,
		RenderMode:        "auto",
		EnableOCRFallback: true,
	})
	if err != nil {
		t.Fatalf("Crawl: %v", err)
	}
	if !r.Success {
		t.Fatalf("crawl unsuccessful: %s", r.ErrorMessage)
	}
	if r.ExtractionMethod == "" {
		t.Fatalf("extraction_method missing in response")
	}
	if r.WordCount < 20 {
		t.Fatalf("expected real content from HN, got %d words", r.WordCount)
	}
	// HN homepage should not lead with classic nav junk
	lead := strings.ToLower(strings.TrimSpace(r.Markdown))
	if len(lead) > 120 {
		lead = lead[:120]
	}
	for _, j := range []string{"skip to content", "main menu", "navigation menu"} {
		if strings.Contains(lead, j) {
			t.Fatalf("nav junk in lead: %q", j)
		}
	}
	t.Logf("crawl: method=%s wc=%d blocked=%v escalations=%v",
		r.ExtractionMethod, r.WordCount, r.Blocked, r.Escalations)
}
