package main

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// Models tab — inference catalog: providers, model ids, context lengths.
type modelsTab struct {
	client  *Client
	view    viewport.Model
	spinner spinner.Model
	width, height int
	state    agentState
	models   []Model
	err      error
}

type modelsMsg struct {
	models []Model
	err    error
}

func newModelsTab(c *Client) *modelsTab {
	sp := spinner.New()
	sp.Spinner = spinner.Dot
	return &modelsTab{client: c, view: viewport.New(0, 0), spinner: sp}
}

func (t *modelsTab) Title() string  { return "Models" }
func (t *modelsTab) Insert() bool { return false }
func (t *modelsTab) StatusBits() string { return "" }
func (t *modelsTab) SetSize(w, h int) {
	t.width = w
	t.height = h
	t.view.Width = w - 4
	t.view.Height = h - 7
}

func (t *modelsTab) Init() tea.Cmd {
	t.state = agentAggregating
	return tea.Batch(t.spinner.Tick, func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		ms, err := t.client.Models(ctx)
		return modelsMsg{models: ms, err: err}
	})
}

func (t *modelsTab) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case modelsMsg:
		t.state = agentDone
		t.models = msg.models
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

func (t *modelsTab) renderResult() {
	var b strings.Builder
	if t.err != nil {
		b.WriteString(errStyle.Render("error: " + t.err.Error()))
		t.view.SetContent(b.String())
		return
	}
	byProv := map[string][]Model{}
	for _, m := range t.models {
		byProv[m.Provider] = append(byProv[m.Provider], m)
	}
	b.WriteString(hlStyle.Render(fmt.Sprintf("%d models across %d providers\n\n", len(t.models), len(byProv))))
	for prov, ms := range byProv {
		b.WriteString(hlStyle.Render("[" + prov + "]\n"))
		for _, m := range ms {
			b.WriteString(fmt.Sprintf("  %-40s  ctx=%-9d  by %s\n", m.ID, m.ContextLength, dimStyle.Render(m.OwnedBy)))
		}
		b.WriteString("\n")
	}
	t.view.SetContent(b.String())
}

func (t *modelsTab) View() string {
	var status string
	switch t.state {
	case agentAggregating:
		status = t.spinner.View() + " fetching catalog…"
	case agentDone:
		if t.err != nil {
			status = errStyle.Render("error")
		} else {
			status = okStyle.Render(fmt.Sprintf("✓ %d models", len(t.models))) + dimStyle.Render("  •  ctrl+r refresh")
		}
	}
	return lipgloss.JoinVertical(lipgloss.Left,
		contentBoxStyle.Width(t.width-4).Height(t.height-7).Render(t.view.View()),
		"  "+status,
	)
}
