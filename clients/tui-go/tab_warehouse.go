package main

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/glamour"
	"github.com/charmbracelet/lipgloss"
)

// Warehouse tab — minimal document browser.
//
// Two panes side-by-side. The left lists rows, the right shows the body of
// the cursored row. Default mode is "recent" (last 50 ingested). Press `/`
// to search (hybrid FTS5+vector). Press `#` to jump by id.
//
// Vim binds:
//   j/k        cursor (auto-loads right pane immediately)
//   gg/G       top/bottom of list (root forwards via NavMsg)
//   Enter      reload current row
//   o          open URL in $BROWSER
//   y          yank URL to clipboard
//   /          focus search input
//   #          focus id input
//   r          refresh recent
//   Esc        blur input + return to recent
type warehouseTab struct {
	client *Client

	queryIn textinput.Model
	idIn    textinput.Model
	rowList viewport.Model
	viewer  viewport.Model
	spinner spinner.Model

	width, height int
	// Source of current rows. "recent" (default) | "hybrid". Search results
	// linger until the user presses Esc or `r` to return to recent.
	source string

	hits   []WarehouseHit
	cursor int
	row    *WarehouseRow
	err    error
	state  agentState

	loadedID int

	// Cached glamour renderer (rebuilt when viewer width changes).
	glamour  *glamour.TermRenderer
	glamourW int
}

type whHitsMsg struct {
	hits   []WarehouseHit
	err    error
	source string
}
type whRowMsg struct {
	row *WarehouseRow
	err error
}

func newWarehouseTab(c *Client) *warehouseTab {
	q := textinput.New()
	q.Placeholder = "search (FTS5 + vector hybrid)…"
	q.Prompt = "/ "
	q.CharLimit = 256

	id := textinput.New()
	id.Placeholder = "row id"
	id.Prompt = "# "
	id.CharLimit = 8
	id.Width = 10

	sp := spinner.New()
	sp.Spinner = spinner.MiniDot
	sp.Style = lipgloss.NewStyle().Foreground(cAccent)

	return &warehouseTab{
		client:  c,
		queryIn: q,
		idIn:    id,
		rowList: viewport.New(0, 0),
		viewer:  viewport.New(0, 0),
		spinner: sp,
		source:  "recent",
	}
}

func (t *warehouseTab) Title() string { return "Warehouse" }

// Insert returns true when an input is focused — root uses this to decide
// whether tab/global keys should be captured.
func (t *warehouseTab) Insert() bool {
	return t.queryIn.Focused() || t.idIn.Focused()
}

func (t *warehouseTab) StatusBits() string {
	if t.queryIn.Focused() {
		return keyStyle.Render("SEARCH") + dimSt.Render("  enter ↵ run  esc cancel")
	}
	if t.idIn.Focused() {
		return keyStyle.Render("ID") + dimSt.Render("  enter ↵ jump  esc cancel")
	}
	if t.state == agentAggregating {
		return t.spinner.View() + dimSt.Render(" loading")
	}
	if t.row != nil {
		return dimSt.Render(fmt.Sprintf("id=%d %dw %s  •  ", t.row.ID, t.row.WordCount, t.row.SourceDomain)) +
			dimSt.Render(fmt.Sprintf("%s %d/%d  •  ", t.source, t.cursor+1, len(t.hits))) +
			dimSt.Render("j/k nav  / search  o open  y yank  r refresh")
	}
	return dimSt.Render(fmt.Sprintf("%s rows=%d  •  ", t.source, len(t.hits))) +
		dimSt.Render("j/k nav  / search  # by-id  r refresh")
}

func (t *warehouseTab) SetSize(w, h int) {
	t.width = w
	t.height = h
	headerH := 3
	footerH := 1
	bodyH := h - headerH - footerH
	if bodyH < 5 {
		bodyH = 5
	}
	leftW := w * 32 / 100
	if leftW < 32 {
		leftW = 32
	}
	rightW := w - leftW - 6
	t.rowList.Width = leftW - 4
	t.rowList.Height = bodyH - 2
	t.viewer.Width = rightW - 4
	t.viewer.Height = bodyH - 2
	if t.viewer.Width > 0 && t.viewer.Width != t.glamourW {
		r, err := glamour.NewTermRenderer(
			glamour.WithAutoStyle(),
			glamour.WithWordWrap(t.viewer.Width-2),
		)
		if err == nil {
			t.glamour = r
			t.glamourW = t.viewer.Width
		}
	}
}

func (t *warehouseTab) Init() tea.Cmd {
	return tea.Batch(textinput.Blink, t.spinner.Tick, t.fetchRecent())
}

// ─── Updates ────────────────────────────────────────────────────────────────

func (t *warehouseTab) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {

	case NavMsg:
		return t, t.handleNav(msg)

	case whHitsMsg:
		t.state = agentDone
		t.err = msg.err
		t.hits = msg.hits
		t.cursor = 0
		t.source = msg.source
		t.renderRowList()
		if msg.err != nil {
			t.viewer.SetContent(errSt.Render("fetch failed: ") + msg.err.Error())
			return t, nil
		}
		if len(t.hits) > 0 {
			return t, t.loadRow(t.hits[0].ID)
		}
		t.viewer.SetContent(dimSt.Render("  (no rows — try `/` to search, or `r` to refresh)"))
		return t, nil

	case whRowMsg:
		t.state = agentDone
		t.err = msg.err
		t.row = msg.row
		t.renderViewer()
		return t, nil

	case spinner.TickMsg:
		var cmd tea.Cmd
		t.spinner, cmd = t.spinner.Update(msg)
		return t, cmd

	case tea.KeyMsg:
		k := msg.String()

		// Query input owns keys when focused.
		if t.queryIn.Focused() {
			switch k {
			case "esc":
				t.queryIn.Blur()
				t.queryIn.SetValue("")
				return t, t.fetchRecent()
			case "enter":
				q := strings.TrimSpace(t.queryIn.Value())
				t.queryIn.Blur()
				if q == "" {
					return t, t.fetchRecent()
				}
				return t, t.fetchHybrid(q)
			}
			var c tea.Cmd
			t.queryIn, c = t.queryIn.Update(msg)
			return t, c
		}
		if t.idIn.Focused() {
			switch k {
			case "esc":
				t.idIn.Blur()
				t.idIn.SetValue("")
				return t, nil
			case "enter":
				v := strings.TrimSpace(t.idIn.Value())
				t.idIn.Blur()
				if id, err := strconv.Atoi(v); err == nil {
					return t, t.loadRow(id)
				}
				return t, nil
			}
			var c tea.Cmd
			t.idIn, c = t.idIn.Update(msg)
			return t, c
		}

		// NORMAL — vim-style.
		switch k {
		case "j", "down":
			if t.cursor < len(t.hits)-1 {
				t.cursor++
				t.renderRowList()
				return t, t.loadRow(t.hits[t.cursor].ID)
			}
		case "k", "up":
			if t.cursor > 0 {
				t.cursor--
				t.renderRowList()
				return t, t.loadRow(t.hits[t.cursor].ID)
			}
		case "g":
			if t.cursor != 0 && len(t.hits) > 0 {
				t.cursor = 0
				t.renderRowList()
				return t, t.loadRow(t.hits[0].ID)
			}
		case "G":
			if len(t.hits) > 0 {
				t.cursor = len(t.hits) - 1
				t.renderRowList()
				return t, t.loadRow(t.hits[t.cursor].ID)
			}
		case "enter":
			if t.cursor < len(t.hits) {
				return t, t.loadRow(t.hits[t.cursor].ID)
			}
		case "o":
			if t.cursor < len(t.hits) {
				go openInBrowser(t.hits[t.cursor].URL)
				return t, func() tea.Msg {
					return cmdRanMsg{feedback: "opened: " + t.hits[t.cursor].URL}
				}
			}
		case "y":
			if t.cursor < len(t.hits) {
				_ = clipWrite(t.hits[t.cursor].URL)
				return t, func() tea.Msg { return cmdRanMsg{feedback: "yanked URL"} }
			}
		case "r":
			return t, t.fetchRecent()
		case "/":
			t.queryIn.Focus()
			return t, textinput.Blink
		case "#":
			t.idIn.Focus()
			return t, textinput.Blink
		case "esc":
			// Esc in normal returns to recent (clears search) if a search is up.
			if t.source != "recent" {
				return t, t.fetchRecent()
			}
		}

		// Anything else: forward to the viewer for scroll.
		var c tea.Cmd
		t.viewer, c = t.viewer.Update(msg)
		return t, c
	}

	// Other messages — propagate to viewports for animation/window-resize.
	var c1, c2 tea.Cmd
	t.viewer, c1 = t.viewer.Update(msg)
	t.rowList, c2 = t.rowList.Update(msg)
	return t, tea.Batch(c1, c2)
}

func (t *warehouseTab) handleNav(n NavMsg) tea.Cmd {
	switch n.Op {
	case "gg":
		t.viewer.GotoTop()
	case "G":
		t.viewer.GotoBottom()
	case "halfdown":
		t.viewer.HalfViewDown()
	case "halfup":
		t.viewer.HalfViewUp()
	}
	return nil
}

// ─── Fetchers ───────────────────────────────────────────────────────────────

func (t *warehouseTab) fetchRecent() tea.Cmd {
	t.state = agentAggregating
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()
		hits, err := t.client.WarehouseList(ctx, 50, "")
		return whHitsMsg{hits: hits, err: err, source: "recent"}
	}
}

func (t *warehouseTab) fetchHybrid(q string) tea.Cmd {
	t.state = agentAggregating
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
		defer cancel()
		hr, err := t.client.HybridSearch(ctx, q, 30)
		if err != nil {
			return whHitsMsg{err: err, source: "hybrid:" + q}
		}
		hits := make([]WarehouseHit, 0, len(hr.Hits))
		for _, h := range hr.Hits {
			badges := ""
			if h.FtsRank != nil {
				badges += fmt.Sprintf("[fts#%d] ", *h.FtsRank)
			}
			if h.VecRank != nil {
				badges += fmt.Sprintf("[vec#%d] ", *h.VecRank)
			}
			snip := h.Snippet
			if snip == "" {
				snip = "(no snippet)"
			}
			hits = append(hits, WarehouseHit{
				ID: h.ID, URL: h.URL, Title: h.Title,
				Snippet:      badges + snip,
				SourceDomain: h.SourceDomain, WordCount: h.WordCount,
			})
		}
		return whHitsMsg{hits: hits, err: nil, source: "hybrid:" + q}
	}
}

func (t *warehouseTab) loadRow(id int) tea.Cmd {
	if id == t.loadedID && t.row != nil {
		// Already loaded; no-op (cheap re-render).
		return nil
	}
	t.state = agentAggregating
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		row, err := t.client.WarehouseGet(ctx, id)
		return whRowMsg{row: row, err: err}
	}
}

// ─── Rendering ──────────────────────────────────────────────────────────────

func (t *warehouseTab) renderRowList() {
	var b strings.Builder
	if t.err != nil {
		b.WriteString(errSt.Render("error: ") + t.err.Error() + "\n\n")
		b.WriteString(dimSt.Render("  press r to retry"))
		t.rowList.SetContent(b.String())
		return
	}
	if t.state == agentAggregating && len(t.hits) == 0 {
		b.WriteString(t.spinner.View() + dimSt.Render(" loading "+t.source+"…"))
		t.rowList.SetContent(b.String())
		return
	}
	if len(t.hits) == 0 {
		b.WriteString(dimSt.Render("  (no rows)"))
		t.rowList.SetContent(b.String())
		return
	}
	for i, h := range t.hits {
		marker := "  "
		if i == t.cursor {
			marker = keyStyle.Render("▶ ")
		}
		domain := h.SourceDomain
		if len(domain) > 14 {
			domain = domain[:13] + "…"
		}
		title := h.Title
		if title == "" {
			title = "(no title)"
		}
		titleMax := t.rowList.Width - 28
		if titleMax < 20 {
			titleMax = 20
		}
		if len(title) > titleMax {
			title = title[:titleMax-1] + "…"
		}
		domainStyle := classifyDomainStyle(h.SourceDomain)
		line := fmt.Sprintf("%s%-4d %s  %s",
			marker, h.ID,
			dimSt.Render(fmt.Sprintf("w%-5d", h.WordCount)),
			title,
		)
		line2 := fmt.Sprintf("        %s", domainStyle.Render(domain))
		if i == t.cursor {
			selStyle := lipgloss.NewStyle().Background(lipgloss.Color("#2a2a37"))
			b.WriteString(selStyle.Width(t.rowList.Width).Render(line) + "\n")
			b.WriteString(selStyle.Width(t.rowList.Width).Render(line2) + "\n")
		} else {
			b.WriteString(line + "\n" + line2 + "\n")
		}
	}
	t.rowList.SetContent(b.String())
	t.scrollListToCursor()
}

func (t *warehouseTab) scrollListToCursor() {
	cursorY := t.cursor * 2
	if cursorY < t.rowList.YOffset {
		t.rowList.YOffset = cursorY
	} else if cursorY >= t.rowList.YOffset+t.rowList.Height-1 {
		t.rowList.YOffset = cursorY - t.rowList.Height + 2
		if t.rowList.YOffset < 0 {
			t.rowList.YOffset = 0
		}
	}
}

func classifyDomainStyle(d string) lipgloss.Style {
	d = strings.ToLower(d)
	switch {
	case strings.Contains(d, "github") || strings.Contains(d, "gitlab"):
		return domainCode
	case strings.Contains(d, "wikipedia"):
		return domainEnc
	case strings.Contains(d, "arxiv") || strings.Contains(d, "doi.org") ||
		strings.Contains(d, "pubmed") || strings.HasSuffix(d, ".edu"):
		return domainAcad
	case strings.Contains(d, "stackoverflow") || strings.Contains(d, "stackexchange"):
		return domainQA
	case strings.Contains(d, "reddit") || strings.Contains(d, "hackernews") ||
		strings.Contains(d, "ycombinator"):
		return domainSoc
	case strings.Contains(d, "archive.org") || strings.Contains(d, "gutenberg"):
		return domainEnc
	case d == "" || strings.Contains(d, "warehouse") || strings.Contains(d, "vector_store"):
		return domainInt
	default:
		return domainWeb
	}
}

func (t *warehouseTab) renderViewer() {
	if t.err != nil {
		t.viewer.SetContent(errSt.Render("error: " + t.err.Error()))
		return
	}
	r := t.row
	if r == nil {
		t.viewer.SetContent(dimSt.Render("  select a row (j/k) — content auto-loads on the right"))
		return
	}
	t.loadedID = r.ID

	var b strings.Builder
	b.WriteString(hlSt.Render(fmt.Sprintf("id=%d  domain=%s  word_count=%d\n",
		r.ID, r.SourceDomain, r.WordCount)))
	b.WriteString(dimSt.Render(r.URL) + "\n")
	if r.Title != "" {
		b.WriteString(fmt.Sprintf("title:    %s\n", r.Title))
	}
	meta := []string{}
	if r.Author != "" {
		meta = append(meta, "author="+r.Author)
	}
	if r.Published != "" {
		meta = append(meta, "published="+r.Published)
	}
	if r.Language != "" {
		meta = append(meta, "lang="+r.Language)
	}
	if r.IngestedAt != "" {
		meta = append(meta, "ingested="+r.IngestedAt[:19])
	}
	if len(meta) > 0 {
		b.WriteString(dimSt.Render(strings.Join(meta, "  •  ")) + "\n")
	}
	if len(r.Tags) > 0 {
		b.WriteString(dimSt.Render(fmt.Sprintf("tags: %v", r.Tags)) + "\n")
	}
	b.WriteString("\n" + hlSt.Render(strings.Repeat("─", t.viewer.Width-2)) + "\n\n")
	body := r.Markdown
	if t.glamour != nil {
		if rendered, err := t.glamour.Render(body); err == nil {
			body = rendered
		}
	}
	b.WriteString(body)
	t.viewer.SetContent(b.String())
	t.viewer.GotoTop()
}

// ─── View ──────────────────────────────────────────────────────────────────

func (t *warehouseTab) View() string {
	// Refuse to render the body before WindowSizeMsg has set t.width.
	if t.width < 40 || t.height < 8 {
		return dimSt.Render("  initializing…")
	}
	// Header: search bar OR hint line.
	var header string
	switch {
	case t.queryIn.Focused():
		box := inputBoxInsert
		header = box.Width(t.width - 4).Render(t.queryIn.View())
	case t.idIn.Focused():
		box := inputBoxInsert
		header = box.Width(20).Render(t.idIn.View())
	default:
		modeIndicator := hlSt.Render(t.source)
		header = dimSt.Render(fmt.Sprintf(
			"  %s   /  search   #  by-id   j/k  nav   enter  reload   o  open   y  yank   r  refresh",
			modeIndicator,
		))
	}

	leftW := t.width * 32 / 100
	if leftW < 32 {
		leftW = 32
	}
	rightW := t.width - leftW - 6

	leftLabel := dimSt.Render(fmt.Sprintf(" rows (%d) ", len(t.hits)))
	rightLabel := dimSt.Render(" content ")

	leftBoxStyle := contentBox
	rightBoxStyle := contentBox
	if !t.Insert() && t.row == nil {
		leftBoxStyle = focusBox
	} else if !t.Insert() {
		rightBoxStyle = focusBox
	}

	bodyH := t.height - 5
	if bodyH < 5 {
		bodyH = 5
	}

	left := lipgloss.JoinVertical(lipgloss.Left,
		leftLabel,
		leftBoxStyle.Width(leftW-2).Height(bodyH-1).Render(t.rowList.View()),
	)
	right := lipgloss.JoinVertical(lipgloss.Left,
		rightLabel,
		rightBoxStyle.Width(rightW).Height(bodyH-1).Render(t.viewer.View()),
	)
	body := lipgloss.JoinHorizontal(lipgloss.Top, left, " ", right)

	return lipgloss.JoinVertical(lipgloss.Left, header, body)
}
