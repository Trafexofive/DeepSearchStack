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

// Search tab — aggregate without LLM. Inspect the raw fan-out, source
// attribution (post-fix: meta-search hits show their real origin), domain
// breakdown, consensus claims.
type searchTab struct {
	client  *Client
	input   textinput.Model
	spinner spinner.Model
	view    viewport.Model

	width, height int
	state         agentState
	resp          *AggregateResp
	err           error
	elapsed       time.Duration
}

type searchDoneMsg struct {
	resp    *AggregateResp
	err     error
	elapsed time.Duration
}

func newSearchTab(c *Client) *searchTab {
	in := textinput.New()
	in.Placeholder = "query (enter to aggregate)…"
	in.CharLimit = 512
	in.Prompt = "› "
	sp := spinner.New()
	sp.Spinner = spinner.Dot
	return &searchTab{client: c, input: in, spinner: sp, view: viewport.New(0, 0)}
}

func (t *searchTab) Title() string  { return "Search" }
func (t *searchTab) Insert() bool { return t.input.Focused() && t.state != agentAggregating }
func (t *searchTab) StatusBits() string { return "" }

func (t *searchTab) SetSize(w, h int) {
	t.width = w
	t.height = h
	t.view.Width = w - 4
	t.view.Height = h - 9
}

func (t *searchTab) Init() tea.Cmd {
	t.input.Focus()
	return tea.Batch(textinput.Blink, t.spinner.Tick)
}

func (t *searchTab) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		if msg.Type == tea.KeyEnter && t.state == agentIdle {
			q := strings.TrimSpace(t.input.Value())
			if q != "" {
				t.state = agentAggregating
				t.resp, t.err = nil, nil
				start := time.Now()
				t.input.Blur()
				return t, func() tea.Msg {
					ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
					defer cancel()
					r, e := t.client.Aggregate(ctx, AggregateReq{
						Query:           q,
						MaxResults:      20,
						IncludeWH:       true,
						Reconcile:       true,
						EnableScraping:  false,
						EnableSynthesis: false,
					})
					return searchDoneMsg{resp: r, err: e, elapsed: time.Since(start)}
				}
			}
		}
		if msg.String() == "ctrl+r" {
			t.state = agentIdle
			t.resp = nil
			t.err = nil
			t.input.Focus()
			t.view.SetContent("")
			return t, nil
		}
		if msg.String() == "esc" {
			t.input.Blur()
			return t, nil
		}
	case searchDoneMsg:
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
		t.input, c = t.input.Update(msg)
		cmds = append(cmds, c)
	}
	var vc tea.Cmd
	t.view, vc = t.view.Update(msg)
	cmds = append(cmds, vc)
	return t, tea.Batch(cmds...)
}

func (t *searchTab) renderResult() {
	var b strings.Builder
	if t.err != nil {
		b.WriteString(errStyle.Render("error: " + t.err.Error()))
		t.view.SetContent(b.String())
		return
	}
	if t.resp == nil {
		return
	}
	r := t.resp
	b.WriteString(hlStyle.Render(fmt.Sprintf("query=%q  total=%d  domains=%v  elapsed=%s  fact_db_hit=%v\n\n",
		r.Query, r.TotalSources, r.DomainsQueried, t.elapsed.Round(time.Millisecond), r.FactDBHit)))

	// Source breakdown by origin (post-fix this is the real domain count)
	srcCount := map[string]int{}
	chCount := map[string]int{}
	for _, s := range r.Sources {
		srcCount[s.Source]++
		for _, e := range s.Entities {
			if strings.HasPrefix(e, "via:") {
				chCount[strings.TrimPrefix(e, "via:")]++
			}
		}
	}
	b.WriteString(hlStyle.Render("─ Source breakdown ─\n"))
	for src, n := range srcCount {
		b.WriteString(fmt.Sprintf("  %-32s × %d\n", src, n))
	}
	if len(chCount) > 0 {
		b.WriteString("\n" + dimStyle.Render("  meta-search channels: "))
		var parts []string
		for ch, n := range chCount {
			parts = append(parts, fmt.Sprintf("%s×%d", ch, n))
		}
		b.WriteString(strings.Join(parts, "  "))
		b.WriteString("\n")
	}

	b.WriteString("\n" + hlStyle.Render(fmt.Sprintf("─ Sources (%d) ─\n", len(r.Sources))))
	for i, s := range r.Sources {
		b.WriteString(fmt.Sprintf("  [%d] %s  ", i+1, hlStyle.Render(s.Source)))
		b.WriteString(dimStyle.Render(fmt.Sprintf("(%s, %.2f)", s.Domain, s.Confidence)))
		b.WriteString("\n      " + s.Title)
		b.WriteString("\n      " + dimStyle.Render(s.URL) + "\n")
	}

	if len(r.Consensus) > 0 {
		b.WriteString("\n" + hlStyle.Render(fmt.Sprintf("─ Consensus (%d claims) ─\n", len(r.Consensus))))
		for _, c := range r.Consensus {
			m := dimStyle.Render("?")
			switch c.Quality {
			case "verified":
				m = okStyle.Render("✓")
			case "probable":
				m = warnStyle.Render("~")
			}
			b.WriteString(fmt.Sprintf("  %s [%.2f] %s %s\n", m, c.Confidence, c.Claim, dimStyle.Render(fmt.Sprintf("%v", c.SupportingSources))))
		}
	}
	t.view.SetContent(b.String())
}

func (t *searchTab) View() string {
	var status string
	switch t.state {
	case agentIdle:
		status = dimStyle.Render("Enter to aggregate  •  ctrl+r reset")
	case agentAggregating:
		status = t.spinner.View() + " aggregating across providers…"
	case agentDone:
		if t.err != nil {
			status = errStyle.Render("error")
		} else {
			status = okStyle.Render("✓ done") + dimStyle.Render("  •  ctrl+r new query")
		}
	}
	return lipgloss.JoinVertical(lipgloss.Left,
		inputBoxStyle.Width(t.width-4).Render(t.input.View()),
		contentBoxStyle.Width(t.width-4).Height(t.height-9).Render(t.view.View()),
		"  "+status,
	)
}
