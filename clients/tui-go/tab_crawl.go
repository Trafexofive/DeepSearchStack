package main

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// Crawl tab — data-quality inspector. URL + render_mode + bypass cache,
// shows extraction_method, escalations, blocked status, word_count, and the
// lead 250 chars with a clean/junk verdict so the operator sees data quality
// at a glance.
type crawlTab struct {
	client *Client

	urlInput textinput.Model
	spinner  spinner.Model
	view     viewport.Model

	width, height int
	state         agentState
	resp          *CrawlResp
	err           error
	elapsed       time.Duration

	mode      int      // 0 auto, 1 fast, 2 browser, 3 ocr
	modes     []string
	bypass    bool
}

type crawlDoneMsg struct {
	resp    *CrawlResp
	err     error
	elapsed time.Duration
}

var navJunk = []string{
	"skip to content", "main menu", "navigation menu",
	"[jump to content", "[skip to", "toggle navigation",
	"sign in", "search code, repositories", "you must be signed in",
	"notifications\n", "fork",
}

func newCrawlTab(c *Client) *crawlTab {
	in := textinput.New()
	in.Placeholder = "https://example.com (Enter to crawl)"
	in.CharLimit = 2048
	in.Prompt = "› "
	sp := spinner.New()
	sp.Spinner = spinner.Dot
	return &crawlTab{
		client:   c,
		urlInput: in,
		spinner:  sp,
		view:     viewport.New(0, 0),
		modes:    []string{"auto", "fast", "browser", "ocr"},
	}
}

func (t *crawlTab) Title() string  { return "Crawl" }
func (t *crawlTab) Insert() bool { return t.urlInput.Focused() && t.state != agentAggregating }
func (t *crawlTab) StatusBits() string { return "" }
func (t *crawlTab) SetSize(w, h int) {
	t.width = w
	t.height = h
	t.view.Width = w - 4
	t.view.Height = h - 11
}
func (t *crawlTab) Init() tea.Cmd {
	t.urlInput.Focus()
	return tea.Batch(textinput.Blink, t.spinner.Tick)
}

func (t *crawlTab) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "enter":
			if t.state == agentIdle || t.state == agentDone {
				u := strings.TrimSpace(t.urlInput.Value())
				if u != "" {
					return t, t.doCrawl(u)
				}
			}
		case "ctrl+m": // cycle render mode
			t.mode = (t.mode + 1) % len(t.modes)
			return t, nil
		case "ctrl+b": // toggle bypass cache
			t.bypass = !t.bypass
			return t, nil
		case "ctrl+r":
			t.state = agentIdle
			t.resp, t.err = nil, nil
			t.urlInput.Focus()
			t.view.SetContent("")
			return t, nil
		case "esc":
			t.urlInput.Blur()
			return t, nil
		}
	case crawlDoneMsg:
		t.state = agentDone
		t.resp = msg.resp
		t.err = msg.err
		t.elapsed = msg.elapsed
		t.renderResult()
		return t, nil
	case spinner.TickMsg:
		var cmd tea.Cmd
		t.spinner, cmd = t.spinner.Update(msg)
		return t, cmd
	}

	var cmds []tea.Cmd
	if t.state == agentIdle {
		var c tea.Cmd
		t.urlInput, c = t.urlInput.Update(msg)
		cmds = append(cmds, c)
	}
	var vc tea.Cmd
	t.view, vc = t.view.Update(msg)
	cmds = append(cmds, vc)
	return t, tea.Batch(cmds...)
}

func (t *crawlTab) doCrawl(u string) tea.Cmd {
	t.state = agentAggregating
	t.resp, t.err = nil, nil
	t.urlInput.Blur()
	mode := t.modes[t.mode]
	bypass := t.bypass
	start := time.Now()
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 240*time.Second)
		defer cancel()
		r, e := t.client.Crawl(ctx, CrawlReq{
			URL:               u,
			Timeout:           90,
			BypassCache:       bypass,
			RenderMode:        mode,
			EnableOCRFallback: true,
		})
		return crawlDoneMsg{resp: r, err: e, elapsed: time.Since(start)}
	}
}

func (t *crawlTab) renderResult() {
	if t.err != nil {
		t.view.SetContent(errStyle.Render("error: " + t.err.Error()))
		return
	}
	if t.resp == nil {
		return
	}
	r := t.resp
	var b strings.Builder

	color := okStyle
	if r.ExtractionMethod == "browser" {
		color = hlStyle
	}
	if r.ExtractionMethod == "ocr" {
		color = warnStyle
	}

	b.WriteString(color.Render(fmt.Sprintf("extraction_method = %s", r.ExtractionMethod)))
	b.WriteString(fmt.Sprintf("   elapsed = %s\n", t.elapsed.Round(time.Millisecond)))
	b.WriteString(fmt.Sprintf("escalations    = %v\n", r.Escalations))
	if r.Blocked {
		b.WriteString(errStyle.Render(fmt.Sprintf("blocked = true   reason = %s\n", r.BlockReason)))
	}
	b.WriteString(fmt.Sprintf("title          = %q\n", r.Title))
	b.WriteString(fmt.Sprintf("author         = %q\n", r.Author))
	b.WriteString(fmt.Sprintf("published      = %q\n", r.Published))
	b.WriteString(fmt.Sprintf("language       = %q\n", r.Language))
	b.WriteString(fmt.Sprintf("word_count     = %d\n", r.WordCount))
	b.WriteString(fmt.Sprintf("markdown chars = %d\n", len(r.Markdown)))
	b.WriteString("\n")

	lead := strings.TrimSpace(r.Markdown)
	if len(lead) > 250 {
		lead = lead[:250]
	}
	lo := strings.ToLower(lead)
	if len(lo) > 120 {
		lo = lo[:120]
	}
	junk := ""
	for _, j := range navJunk {
		if strings.Contains(lo, j) {
			junk = j
			break
		}
	}
	if junk != "" {
		b.WriteString(warnStyle.Render("⚠ data-quality: lead contains nav junk → " + junk))
	} else {
		b.WriteString(okStyle.Render("✓ clean lead (no nav-junk markers)"))
	}
	b.WriteString("\n\n" + hlStyle.Render("── first 250 chars ──\n"))
	b.WriteString(lead)
	b.WriteString("\n\n" + hlStyle.Render("── full markdown (truncated to 200 lines) ──\n"))
	lines := strings.Split(r.Markdown, "\n")
	limit := 200
	if len(lines) < limit {
		limit = len(lines)
	}
	for i := 0; i < limit; i++ {
		b.WriteString(lines[i])
		b.WriteString("\n")
	}
	if len(lines) > 200 {
		b.WriteString(dimStyle.Render(fmt.Sprintf("\n… %d more lines", len(lines)-200)))
	}
	t.view.SetContent(b.String())
}

func (t *crawlTab) View() string {
	mode := t.modes[t.mode]
	bypass := "OFF"
	if t.bypass {
		bypass = warnStyle.Render("ON")
	}
	hdr := fmt.Sprintf("  mode: %s  •  ctrl+m cycle  •  bypass cache: %s  •  ctrl+b toggle",
		hlStyle.Render(mode), bypass)

	var status string
	switch t.state {
	case agentIdle:
		status = dimStyle.Render("Enter to crawl  •  ctrl+r reset")
	case agentAggregating:
		status = t.spinner.View() + " crawling…"
	case agentDone:
		if t.err != nil {
			status = errStyle.Render("error")
		} else {
			status = okStyle.Render("✓ done")
		}
	}

	return lipgloss.JoinVertical(lipgloss.Left,
		inputBoxStyle.Width(t.width-4).Render(t.urlInput.View()),
		hdr,
		contentBoxStyle.Width(t.width-4).Height(t.height-11).Render(t.view.View()),
		"  "+status,
	)
}
