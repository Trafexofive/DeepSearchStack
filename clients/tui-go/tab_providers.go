package main

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// Providers tab — search-gateway provider registry. Shows which providers
// are enabled (the orchestrator pulls from these); meta-search ones are
// labeled so the operator knows hits get re-attributed to real origins.
type providersTab struct {
	client  *Client
	view    viewport.Model
	spinner spinner.Model
	width, height int
	state   agentState
	provs   map[string]string
	err     error
}

type provsMsg struct {
	provs map[string]string
	err   error
}

func newProvidersTab(c *Client) *providersTab {
	sp := spinner.New()
	sp.Spinner = spinner.Dot
	return &providersTab{client: c, view: viewport.New(0, 0), spinner: sp}
}

func (t *providersTab) Title() string  { return "Providers" }
func (t *providersTab) Insert() bool { return false }
func (t *providersTab) StatusBits() string { return "" }
func (t *providersTab) SetSize(w, h int) {
	t.width = w
	t.height = h
	t.view.Width = w - 4
	t.view.Height = h - 7
}

func (t *providersTab) Init() tea.Cmd {
	t.state = agentAggregating
	return tea.Batch(t.spinner.Tick, func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		p, err := t.client.Providers(ctx)
		return provsMsg{provs: p, err: err}
	})
}

func (t *providersTab) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case provsMsg:
		t.state = agentDone
		t.provs = msg.provs
		t.err = msg.err
		t.renderResult()
	case spinner.TickMsg:
		var cmd tea.Cmd
		t.spinner, cmd = t.spinner.Update(msg)
		return t, cmd
	case tea.KeyMsg:
		if msg.String() == "ctrl+r" {
			return t, t.Init()
		}
	}
	var vc tea.Cmd
	t.view, vc = t.view.Update(msg)
	return t, vc
}

func (t *providersTab) renderResult() {
	var b strings.Builder
	if t.err != nil {
		b.WriteString(errStyle.Render("error: " + t.err.Error()))
		t.view.SetContent(b.String())
		return
	}
	metaChannels := map[string]bool{"searxng": true, "yacy": true, "duckduckgo": true}
	keys := make([]string, 0, len(t.provs))
	for k := range t.provs {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	b.WriteString(hlStyle.Render(fmt.Sprintf("%d providers registered\n\n", len(keys))))
	for _, k := range keys {
		status := t.provs[k]
		tag := ""
		if metaChannels[k] {
			tag = dimStyle.Render("  (meta-search channel; hits re-attributed to real origin)")
		}
		marker := okStyle.Render("●")
		if status != "enabled" {
			marker = errStyle.Render("○")
		}
		b.WriteString(fmt.Sprintf("  %s  %-20s  %s%s\n", marker, k, dimStyle.Render(status), tag))
	}
	t.view.SetContent(b.String())
}

func (t *providersTab) View() string {
	var status string
	switch t.state {
	case agentAggregating:
		status = t.spinner.View() + " fetching providers…"
	case agentDone:
		if t.err != nil {
			status = errStyle.Render("error")
		} else {
			status = okStyle.Render(fmt.Sprintf("✓ %d providers", len(t.provs))) + dimStyle.Render("  •  ctrl+r refresh")
		}
	}
	return lipgloss.JoinVertical(lipgloss.Left,
		contentBoxStyle.Width(t.width-4).Height(t.height-7).Render(t.view.View()),
		"  "+status,
	)
}
