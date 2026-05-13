// Package client provides an HTTP client for the Substrate API gateway.
// Talks JSON over HTTP. Handles auth headers, timeouts, and response parsing.
package client

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// Client is a typed HTTP client for the Substrate API gateway.
type Client struct {
	BaseURL    string
	HTTPClient *http.Client
	APIKey     string
}

// New creates a new client targeting a Substrate API gateway.
func New(baseURL string) *Client {
	return &Client{
		BaseURL: baseURL,
		HTTPClient: &http.Client{
			Timeout: 120 * time.Second,
		},
	}
}

// WithTimeout sets a custom request timeout.
func (c *Client) WithTimeout(d time.Duration) *Client {
	c.HTTPClient.Timeout = d
	return c
}

// WithAPIKey sets a JWT bearer token for authenticated requests.
func (c *Client) WithAPIKey(key string) *Client {
	c.APIKey = key
	return c
}

// Get performs a GET request and unmarshals the JSON response into v.
func (c *Client) Get(path string, v interface{}) error {
	return c.do("GET", path, nil, v)
}

// Post performs a POST request with a JSON body and unmarshals the response into v.
func (c *Client) Post(path string, body, v interface{}) error {
	return c.do("POST", path, body, v)
}

func (c *Client) do(method, path string, body, v interface{}) error {
	url := c.BaseURL + path

	var reqBody io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return fmt.Errorf("marshal request: %w", err)
		}
		reqBody = bytes.NewReader(data)
	}

	req, err := http.NewRequest(method, url, reqBody)
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	if c.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.APIKey)
	}

	resp, err := c.HTTPClient.Do(req)
	if err != nil {
		return fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respData, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("read response: %w", err)
	}

	if resp.StatusCode >= 400 {
		return fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(respData))
	}

	if v != nil {
		if err := json.Unmarshal(respData, v); err != nil {
			return fmt.Errorf("unmarshal response: %w\n%s", err, string(respData))
		}
	}
	return nil
}

// ─── Typed response types ──────────────────────────────────────────────────

// HealthResponse is the aggregate health check from /health.
type HealthResponse struct {
	Status   string            `json:"status"`
	Version  string            `json:"version"`
	Services map[string]string `json:"services"`
}

// WorkflowInfo is a workflow manifest summary.
type WorkflowInfo struct {
	Name        string `json:"name"`
	Version     string `json:"version"`
	Description string `json:"description"`
	Steps       int    `json:"steps"`
}

// WorkflowListResponse wraps the list of workflows.
type WorkflowListResponse struct {
	Workflows []WorkflowInfo `json:"workflows"`
}

// StepResult is one step in a workflow execution.
type StepResult struct {
	StepID     string `json:"step_id"`
	Status     string `json:"status"`
	Output     any    `json:"output"`
	Error      string `json:"error"`
	DurationMs int    `json:"duration_ms"`
}

// WorkflowResult is the result of a workflow execution.
type WorkflowResult struct {
	Workflow string       `json:"workflow"`
	Status   string       `json:"status"`
	Steps    []StepResult `json:"steps"`
}

// GenerateResponse is a blog generation result.
type GenerateResponse struct {
	ID         string `json:"id"`
	Topic      string `json:"topic"`
	Model      string `json:"model"`
	Content    string `json:"content"`
	CostUSD    float64 `json:"cost_usd"`
	DurationMs int    `json:"duration_ms"`
	Usage      struct {
		TotalTokens int `json:"total_tokens"`
	} `json:"usage"`
}

// BlogStatsResponse is blog generator aggregate stats.
type BlogStatsResponse struct {
	TotalGenerations int     `json:"total_generations"`
	TotalTokens      int     `json:"total_tokens"`
	TotalCostUSD     float64 `json:"total_cost_usd"`
	AvgDurationMs    float64 `json:"avg_duration_ms"`
}

// IngestStatsResponse is ingest pipeline statistics.
type IngestStatsResponse struct {
	FeedsWatched    int     `json:"feeds_watched"`
	EntriesDetected int     `json:"entries_detected"`
	PostsGenerated  int     `json:"posts_generated"`
	PostsPublished  int     `json:"posts_published"`
	LastScan        string  `json:"last_scan"`
	Errors          int     `json:"errors"`
	FeedsConfigured int     `json:"feeds_configured"`
	DraftsCount     int     `json:"drafts_count"`
}

// Health fetches aggregate health from the API gateway.
func (c *Client) Health() (*HealthResponse, error) {
	var h HealthResponse
	if err := c.Get("/health", &h); err != nil {
		return nil, err
	}
	return &h, nil
}

// ListWorkflows returns available workflow manifests.
func (c *Client) ListWorkflows() ([]WorkflowInfo, error) {
	var w WorkflowListResponse
	if err := c.Get("/api/workflows", &w); err != nil {
		return nil, err
	}
	return w.Workflows, nil
}

// ExecuteWorkflow triggers a workflow and blocks until completion.
func (c *Client) ExecuteWorkflow(name string, params map[string]interface{}) (*WorkflowResult, error) {
	body := map[string]interface{}{
		"workflow": name,
		"params":   params,
	}
	c2 := c.WithTimeout(300 * time.Second) // workflows can take 2-3 min
	var w WorkflowResult
	if err := c2.Post("/api/workflows/execute", body, &w); err != nil {
		return nil, err
	}
	return &w, nil
}

// GenerateBlog generates a blog post.
func (c *Client) GenerateBlog(topic, model, style string, maxTokens int) (*GenerateResponse, error) {
	if model == "" {
		model = "deepseek-chat"
	}
	if style == "" {
		style = "technical"
	}
	if maxTokens == 0 {
		maxTokens = 2048
	}
	body := map[string]interface{}{
		"topic":      topic,
		"model":      model,
		"style":      style,
		"max_tokens": maxTokens,
	}
	var g GenerateResponse
	if err := c.Post("/api/blog/generate", body, &g); err != nil {
		return nil, err
	}
	return &g, nil
}

// BlogStats fetches blog generation statistics.
func (c *Client) BlogStats() (*BlogStatsResponse, error) {
	var s BlogStatsResponse
	if err := c.Get("/api/blog/stats", &s); err != nil {
		return nil, err
	}
	return &s, nil
}

// IngestStats fetches ingest pipeline statistics.
func (c *Client) IngestStats() (*IngestStatsResponse, error) {
	var s IngestStatsResponse
	if err := c.Get("/api/ingest/stats", &s); err != nil {
		return nil, err
	}
	return &s, nil
}

// ScanFeeds triggers a manual ingest scan of all feeds.
func (c *Client) ScanFeeds() (map[string]interface{}, error) {
	var result map[string]interface{}
	if err := c.Post("/api/ingest/scan", map[string]string{}, &result); err != nil {
		return nil, err
	}
	return result, nil
}
