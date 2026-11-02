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

// Render tab — direct hits on browser-renderer. URL → article extraction
// (trafilatura) + optional OCR (RapidOCR), no warehouse forwarding.
type renderTab struct {
	client *Client

	urlIn   textinput.Model
	view    viewport.Model
	spinner spinner.Model

	width, height int
	state         agentState
	resp          *RenderResp
	err           error
	elapsed       time.Duration

	runOCR     bool
	fullPage   bool
}

type renderDoneMsg struct {
	resp    *RenderResp
	err     error
	elapsed time.Duration
}

func newRenderTab(c *Client) *renderTab {
	in := textinput.New()
	in.Placeholder = "https://example.com"
	in.CharLimit = 2048
	in.Prompt = "› "
	sp := spinner.New()
	sp.Spinner = spinner.Dot
	return &renderTab{
		client:  c,
		urlIn:   in,
		view:    viewport.New(0, 0),
		spinner: sp,
	}
}

func (t *renderTab) Title() string  { return "Render" }
func (t *renderTab) Insert() bool { return t.urlIn.Focused() && t.state != agentAggregating }
func (t *renderTab) StatusBits() string { return "" }
func (t *renderTab) SetSize(w, h int) {
	t.width = w
	t.height = h
	t.view.Width = w - 4
	t.view.Height = h - 11
}
func (t *renderTab) Init() tea.Cmd {
	t.urlIn.Focus()
	return tea.Batch(textinput.Blink, t.spinner.Tick)
}

func (t *renderTab) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.KeyMsg:
		switch msg.String() {
		case "enter":
			if u := strings.TrimSpace(t.urlIn.Value()); u != "" && t.state != agentAggregating {
				return t, t.runRender(u)
			}
		case "ctrl+o":
			t.runOCR = !t.runOCR
			return t, nil
		case "ctrl+f":
			t.fullPage = !t.fullPage
			return t, nil
		case "ctrl+r":
			t.state = agentIdle
			t.resp = nil
			t.err = nil
			t.urlIn.Focus()
			t.view.SetContent("")
			return t, nil
		case "esc":
			t.urlIn.Blur()
			return t, nil
		}
	case renderDoneMsg:
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
		t.urlIn, c = t.urlIn.Update(msg)
		cmds = append(cmds, c)
	}
	var vc tea.Cmd
	t.view, vc = t.view.Update(msg)
	cmds = append(cmds, vc)
	return t, tea.Batch(cmds...)
}

func (t *renderTab) runRender(u string) tea.Cmd {
	t.state = agentAggregating
	t.resp = nil
	t.err = nil
	t.urlIn.Blur()
	runOCR := t.runOCR
	full := t.fullPage
	start := time.Now()
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 240*time.Second)
		defer cancel()
		r, e := t.client.Render(ctx, RenderReq{
			URL:                u,
			Screenshot:         runOCR,
			FullPageScreenshot: full,
			Wait:               "networkidle",
			TimeoutMS:          25000,
			ExtractArticle:     true,
			RunOCR:             runOCR,
		})
		return renderDoneMsg{resp: r, err: e, elapsed: time.Since(start)}
	}
}

func (t *renderTab) renderResult() {
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
	b.WriteString(fmt.Sprintf("final_url      = %s\n", r.FinalURL))
	b.WriteString(fmt.Sprintf("status         = %d\n", r.Status))
	b.WriteString(fmt.Sprintf("html_length    = %d\n", r.HTMLLength))
	if r.Blocked {
		b.WriteString(errStyle.Render(fmt.Sprintf("blocked = true   reason = %s\n", r.BlockReason)))
	}
	b.WriteString(fmt.Sprintf("title          = %q\n", r.ArticleTitle))
	b.WriteString(fmt.Sprintf("author         = %q\n", r.ArticleAuthor))
	b.WriteString(fmt.Sprintf("published      = %q\n", r.ArticlePublished))
	b.WriteString(fmt.Sprintf("elapsed_ms     = %d  (round-trip %s)\n\n", r.ElapsedMS, t.elapsed.Round(time.Millisecond)))

	if r.ArticleText != "" {
		b.WriteString(hlStyle.Render(fmt.Sprintf("── article_text (trafilatura, %d chars) ──\n", len(r.ArticleText))))
		body := r.ArticleText
		if len(body) > 3000 {
			b.WriteString(body[:3000])
			b.WriteString(dimStyle.Render(fmt.Sprintf("\n… %d more chars", len(body)-3000)))
		} else {
			b.WriteString(body)
		}
		b.WriteString("\n\n")
	}
	if r.OCRText != "" {
		b.WriteString(hlStyle.Render(fmt.Sprintf("── ocr_text (RapidOCR, %d chars) ──\n", len(r.OCRText))))
		body := r.OCRText
		if len(body) > 3000 {
			b.WriteString(body[:3000])
			b.WriteString(dimStyle.Render(fmt.Sprintf("\n… %d more chars", len(body)-3000)))
		} else {
			b.WriteString(body)
		}
	}
	t.view.SetContent(b.String())
}

func (t *renderTab) View() string {
	ocrTag := "OFF"
	if t.runOCR {
		ocrTag = warnStyle.Render("ON")
	}
	fpTag := "viewport"
	if t.fullPage {
		fpTag = hlStyle.Render("full-page")
	}
	hdr := fmt.Sprintf("  ocr: %s (ctrl+o)  •  shot: %s (ctrl+f)", ocrTag, fpTag)

	var status string
	switch t.state {
	case agentIdle:
		status = dimStyle.Render("Enter to render  •  ctrl+r reset")
	case agentAggregating:
		status = t.spinner.View() + " rendering…"
	case agentDone:
		if t.err != nil {
			status = errStyle.Render("error")
		} else {
			status = okStyle.Render("✓ done")
		}
	}
	return lipgloss.JoinVertical(lipgloss.Left,
		inputBoxStyle.Width(t.width-4).Render(t.urlIn.View()),
		hdr,
		contentBoxStyle.Width(t.width-4).Height(t.height-11).Render(t.view.View()),
		"  "+status,
	)
}
