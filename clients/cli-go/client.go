// Package main — DSS HTTP client. Single file, thin wrappers around the
// nginx routes. No SDK, no codegen — direct JSON over the real endpoints.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Client struct {
	BaseURL string
	HTTP    *http.Client
	Debug   bool
}

// safeSlice is a panic-proof variant of s[:n] — used in debug log lines that
// truncate response bodies (which may be shorter than the cap).
func safeSlice(s string, n int) string {
	if len(s) < n {
		return s
	}
	return s[:n]
}

func NewClient(base string) *Client {
	return &Client{
		BaseURL: strings.TrimRight(base, "/"),
		// No hard Client.Timeout — that would override the per-call context
		// (a 180s aggregate would silently die at 30s, which is exactly what
		// just happened). Each method passes its own context.WithTimeout
		// matched to the operation:
		//   health:    5s
		//   list/stats/models: 10-15s
		//   crawl: 90s+ (with browser+ocr escalation)
		//   aggregate: 180s (with scraping)
		//   synthesize_stream: 240s
		// Transport still has IdleConnTimeout + ResponseHeaderTimeout so
		// truly stuck connections get evicted without blocking the TUI.
		HTTP: &http.Client{
			Transport: &http.Transport{
				MaxIdleConns:          50,
				MaxIdleConnsPerHost:   10,
				IdleConnTimeout:       30 * time.Second,
				ResponseHeaderTimeout: 30 * time.Second, // headers must arrive in 30s — bodies can take longer
				ExpectContinueTimeout: 1 * time.Second,
				TLSHandshakeTimeout:   10 * time.Second,
			},
		},
	}
}

// dbg logs HTTP traffic when Client.Debug is true. tea.LogToFile sends the
// standard `log` package output to the debug file the user opened in main.
func (c *Client) dbg(format string, args ...any) {
	if c.Debug {
		log.Printf(format, args...)
	}
}

// ─── Aggregate ─────────────────────────────────────────────────────────────

type AggregateReq struct {
	Query           string   `json:"query"`
	MaxResults      int      `json:"max_results"`
	IncludeWH       bool     `json:"include_warehouse"`
	Reconcile       bool     `json:"reconcile"`
	EnableScraping  bool     `json:"enable_scraping"`
	MaxScrapeURLs   int      `json:"max_scrape_urls,omitempty"`
	EnableSynthesis bool     `json:"enable_synthesis"`
	Providers       []string `json:"providers,omitempty"`
}

type AggregateSource struct {
	Title       string   `json:"title"`
	URL         string   `json:"url"`
	Description string   `json:"description"`
	Source      string   `json:"source"`
	Domain      string   `json:"domain"`
	Confidence  float64  `json:"confidence"`
	Summary     string   `json:"summary"`
	Entities    []string `json:"entities"`
}

type AggregateConsensus struct {
	Claim              string   `json:"claim"`
	Confidence         float64  `json:"confidence"`
	SupportingSources  []string `json:"supporting_sources"`
	ConflictingSources []string `json:"conflicting_sources"`
	Quality            string   `json:"quality"`
}

type AggregateResp struct {
	Query           string               `json:"query"`
	DomainsQueried  []string             `json:"domains_queried"`
	TotalSources    int                  `json:"total_sources"`
	Sources         []AggregateSource    `json:"sources"`
	Consensus       []AggregateConsensus `json:"consensus,omitempty"`
	Synthesis       string               `json:"synthesis,omitempty"`
	ExecutionTimeMS int                  `json:"execution_time_ms"`
	FactDBHit       bool                 `json:"fact_db_hit"`
	ScrapedURLs     int                  `json:"scraped_urls"`
	RAGChunks       int                  `json:"rag_chunks"`
	Answer          string               `json:"answer,omitempty"`
}

func (c *Client) Aggregate(ctx context.Context, req AggregateReq) (*AggregateResp, error) {
	body, _ := json.Marshal(req)
	r, err := http.NewRequestWithContext(ctx, "POST",
		c.BaseURL+"/dss/api/aggregate", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	r.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out AggregateResp
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ─── Synthesize (Research Agent, SSE stream) ──────────────────────────────

type SynthesizeSource struct {
	Title       string `json:"title"`
	URL         string `json:"url"`
	Description string `json:"description"`
	Source      string `json:"source"`
}

type SynthesizeReq struct {
	Query   string             `json:"query"`
	Sources []SynthesizeSource `json:"sources"`
}

// SynthesizeStream POSTs to /dss/agent/synthesize/stream and streams each SSE
// chunk through `onChunk`. Returns the full assembled answer + any warning.
func (c *Client) SynthesizeStream(
	ctx context.Context,
	req SynthesizeReq,
	onChunk func(string),
) (string, string, error) {
	body, _ := json.Marshal(req)
	r, err := http.NewRequestWithContext(ctx, "POST",
		c.BaseURL+"/dss/agent/synthesize/stream", bytes.NewReader(body))
	if err != nil {
		return "", "", err
	}
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Accept", "text/event-stream")
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return "", "", fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var full strings.Builder
	var warning string
	scanner := bufio.NewScanner(resp.Body)
	scanner.Buffer(make([]byte, 0, 1<<20), 1<<22)
	for scanner.Scan() {
		line := scanner.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		payload := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		if payload == "" || payload == "[DONE]" {
			continue
		}
		var ev map[string]any
		if err := json.Unmarshal([]byte(payload), &ev); err != nil {
			// Plain-text chunk fallback
			full.WriteString(payload)
			onChunk(payload)
			continue
		}
		if w, ok := ev["warning"].(string); ok && w != "" {
			warning = w
			continue
		}
		if ch, ok := ev["content"].(string); ok && ch != "" {
			full.WriteString(ch)
			onChunk(ch)
		}
		if done, ok := ev["finished"].(bool); ok && done {
			break
		}
	}
	return full.String(), warning, scanner.Err()
}

// ─── Crawl ────────────────────────────────────────────────────────────────

type CrawlReq struct {
	URL               string `json:"url"`
	Timeout           int    `json:"timeout,omitempty"`
	BypassCache       bool   `json:"bypass_cache,omitempty"`
	RenderMode        string `json:"render_mode,omitempty"`
	EnableOCRFallback bool   `json:"enable_ocr_fallback"`
}

type CrawlResp struct {
	URL              string   `json:"url"`
	Content          string   `json:"content"`
	Markdown         string   `json:"markdown"`
	Title            string   `json:"title"`
	Author           string   `json:"author"`
	Published        string   `json:"published"`
	Language         string   `json:"language"`
	WordCount        int      `json:"word_count"`
	SourceDomain     string   `json:"source_domain"`
	Success          bool     `json:"success"`
	ErrorType        string   `json:"error_type"`
	ErrorMessage     string   `json:"error_message"`
	ExtractionMethod string   `json:"extraction_method"`
	Blocked          bool     `json:"blocked"`
	BlockReason      string   `json:"block_reason"`
	Escalations      []string `json:"escalations"`
	ScreenshotPath   string   `json:"screenshot_path"`
}

func (c *Client) Crawl(ctx context.Context, req CrawlReq) (*CrawlResp, error) {
	if req.Timeout == 0 {
		req.Timeout = 90
	}
	if req.RenderMode == "" {
		req.RenderMode = "auto"
	}
	body, _ := json.Marshal(req)
	r, err := http.NewRequestWithContext(ctx, "POST",
		c.BaseURL+"/dss/crawl/crawl", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	r.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out CrawlResp
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ─── Render (browser-renderer direct) ─────────────────────────────────────

type RenderReq struct {
	URL                string `json:"url"`
	Screenshot         bool   `json:"screenshot"`
	FullPageScreenshot bool   `json:"full_page_screenshot"`
	Wait               string `json:"wait,omitempty"`
	TimeoutMS          int    `json:"timeout_ms,omitempty"`
	ExtractArticle     bool   `json:"extract_article"`
	RunOCR             bool   `json:"run_ocr"`
	SaveScreenshot     bool   `json:"save_screenshot"`
	AutoScroll         bool   `json:"auto_scroll,omitempty"`
	ScrollPasses       int    `json:"scroll_passes,omitempty"`
	ScrollPauseMS      int    `json:"scroll_pause_ms,omitempty"`
}

type RenderResp struct {
	URL              string `json:"url"`
	FinalURL         string `json:"final_url"`
	Status           int    `json:"status"`
	HTMLLength       int    `json:"html_length"`
	Blocked          bool   `json:"blocked"`
	BlockReason      string `json:"block_reason"`
	ArticleText      string `json:"article_text"`
	ArticleTitle     string `json:"article_title"`
	ArticleAuthor    string `json:"article_author"`
	ArticlePublished string `json:"article_published"`
	OCRText          string `json:"ocr_text"`
	ScreenshotPath   string `json:"screenshot_path"`
	ElapsedMS        int    `json:"elapsed_ms"`
}

func (c *Client) Render(ctx context.Context, req RenderReq) (*RenderResp, error) {
	if req.TimeoutMS == 0 {
		req.TimeoutMS = 25000
	}
	body, _ := json.Marshal(req)
	r, err := http.NewRequestWithContext(ctx, "POST",
		c.BaseURL+"/dss/render/render", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	r.Header.Set("Content-Type", "application/json")
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out RenderResp
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ─── Warehouse ────────────────────────────────────────────────────────────

type WarehouseHit struct {
	ID           int    `json:"id"`
	URL          string `json:"url"`
	Title        string `json:"title"`
	Snippet      string `json:"snippet"`
	SourceDomain string `json:"source_domain"`
	WordCount    int    `json:"word_count"`
	IngestedAt   string `json:"ingested_at"`
}

func (c *Client) WarehouseList(ctx context.Context, limit int, domain string) ([]WarehouseHit, error) {
	return c.WarehouseListEx(ctx, limit, domain, "")
}

// WarehouseListEx adds a category filter on top of the basic list. Passing an
// empty string for either domain or category leaves the field unfiltered.
//
// Server caps limit at 100, so we page through under the hood when the caller
// asks for more. Each request returns up to 100; we stop once a short page
// arrives or `limit` results are collected.
func (c *Client) WarehouseListEx(ctx context.Context, limit int, domain, category string) ([]WarehouseHit, error) {
	const pageMax = 100
	out := make([]WarehouseHit, 0, min(limit, pageMax))
	offset := 0
	for len(out) < limit {
		take := limit - len(out)
		if take > pageMax {
			take = pageMax
		}
		u := fmt.Sprintf("%s/dss/warehouse/list?limit=%d&offset=%d",
			c.BaseURL, take, offset)
		if domain != "" {
			u += "&domain=" + url.QueryEscape(domain)
		}
		if category != "" {
			u += "&category=" + url.QueryEscape(category)
		}
		page, err := c.warehouseGetHits(ctx, u)
		if err != nil {
			return nil, err
		}
		out = append(out, page...)
		if len(page) < take {
			break // server returned a short page → no more rows
		}
		offset += len(page)
	}
	return out, nil
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// ─── Hybrid search ────────────────────────────────────────────────────────

type HybridHit struct {
	ID           int     `json:"id"`
	URL          string  `json:"url"`
	Title        string  `json:"title"`
	Snippet      string  `json:"snippet"`
	SourceDomain string  `json:"source_domain"`
	WordCount    int     `json:"word_count"`
	FtsRank      *int    `json:"fts_rank"`
	VecRank      *int    `json:"vec_rank"`
	RrfScore     float64 `json:"rrf_score"`
}

type HybridResp struct {
	Query     string      `json:"query"`
	Hits      []HybridHit `json:"hits"`
	FtsHits   int         `json:"fts_hits"`
	VecHits   int         `json:"vec_hits"`
	Merged    int         `json:"merged"`
	ElapsedMS int         `json:"elapsed_ms"`
}

// HybridSearch runs FTS5 + vector dense + RRF fusion. The single best
// quality lever for warehouse retrieval — exact-keyword + semantic in one.
func (c *Client) HybridSearch(ctx context.Context, q string, limit int) (*HybridResp, error) {
	u := fmt.Sprintf("%s/dss/api/search/hybrid?q=%s&limit=%d",
		c.BaseURL, url.QueryEscape(q), limit)
	r, _ := http.NewRequestWithContext(ctx, "GET", u, nil)
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out HybridResp
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

func (c *Client) WarehouseSearch(ctx context.Context, q, domain string, limit int) ([]WarehouseHit, error) {
	u := fmt.Sprintf("%s/dss/warehouse/search?q=%s&limit=%d",
		c.BaseURL, url.QueryEscape(q), limit)
	if domain != "" {
		u += "&domain=" + url.QueryEscape(domain)
	}
	return c.warehouseGetHits(ctx, u)
}

func (c *Client) warehouseGetHits(ctx context.Context, u string) ([]WarehouseHit, error) {
	t0 := time.Now()
	c.dbg("GET %s", u)
	r, err := http.NewRequestWithContext(ctx, "GET", u, nil)
	if err != nil {
		c.dbg("  build_err: %v", err)
		return nil, err
	}
	resp, err := c.HTTP.Do(r)
	if err != nil {
		c.dbg("  do_err elapsed=%s: %v", time.Since(t0), err)
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		c.dbg("  HTTP %d body=%s", resp.StatusCode, safeSlice(string(b), 200))
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out []WarehouseHit
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		c.dbg("  decode_err: %v", err)
		return nil, err
	}
	c.dbg("  → %d hits in %s", len(out), time.Since(t0))
	return out, nil
}

type WarehouseRow struct {
	ID           int     `json:"id"`
	URL          string  `json:"url"`
	Title        string  `json:"title"`
	Markdown     string  `json:"markdown"`
	Content      string  `json:"content"`
	Author       string  `json:"author"`
	Published    string  `json:"published"`
	Language     string  `json:"language"`
	WordCount    int     `json:"word_count"`
	SourceDomain string  `json:"source_domain"`
	IngestedAt   string  `json:"ingested_at"`
	Tags         []string `json:"tags"`
}

func (c *Client) WarehouseGet(ctx context.Context, id int) (*WarehouseRow, error) {
	u := fmt.Sprintf("%s/dss/warehouse/content/%d", c.BaseURL, id)
	r, _ := http.NewRequestWithContext(ctx, "GET", u, nil)
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 404 {
		return nil, errors.New("not found")
	}
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out WarehouseRow
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

// WarehouseGetByURL fetches the warehouse row whose url_hash matches the
// passed URL. Returns ErrNotFound (errors.New("not found")) when the URL
// isn't archived. Used by the Agent tab's `v` shortcut so we don't have to
// FTS5-search by URL fragments.
func (c *Client) WarehouseGetByURL(ctx context.Context, rawURL string) (*WarehouseRow, error) {
	u := fmt.Sprintf("%s/dss/warehouse/content/by-url?url=%s",
		c.BaseURL, url.QueryEscape(rawURL))
	r, _ := http.NewRequestWithContext(ctx, "GET", u, nil)
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == 404 {
		return nil, errors.New("not found")
	}
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out WarehouseRow
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

type WarehouseStats struct {
	TotalEntries int                      `json:"total_entries"`
	TotalWords   int                      `json:"total_words"`
	Domains      []map[string]any         `json:"domains"`
	DBSizeMB     float64                  `json:"db_size_mb"`
}

func (c *Client) WarehouseStats(ctx context.Context) (*WarehouseStats, error) {
	r, _ := http.NewRequestWithContext(ctx, "GET",
		c.BaseURL+"/dss/warehouse/stats", nil)
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(b))
	}
	var out WarehouseStats
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ─── Catalog ─────────────────────────────────────────────────────────────

type Model struct {
	ID            string `json:"id"`
	Provider      string `json:"provider"`
	OwnedBy       string `json:"owned_by"`
	ContextLength int    `json:"context_length"`
}

func (c *Client) Models(ctx context.Context) ([]Model, error) {
	r, _ := http.NewRequestWithContext(ctx, "GET",
		c.BaseURL+"/dss/api/providers", nil)
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	var w struct{ Models []Model `json:"models"` }
	if err := json.NewDecoder(resp.Body).Decode(&w); err != nil {
		return nil, err
	}
	return w.Models, nil
}

func (c *Client) Providers(ctx context.Context) (map[string]string, error) {
	r, _ := http.NewRequestWithContext(ctx, "GET",
		c.BaseURL+"/dss/gateway/providers", nil)
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	out := map[string]string{}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}
	return out, nil
}

func (c *Client) Health(ctx context.Context) error {
	r, _ := http.NewRequestWithContext(ctx, "GET", c.BaseURL+"/health", nil)
	resp, err := c.HTTP.Do(r)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	return nil
}
