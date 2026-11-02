package main

import (
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"github.com/charmbracelet/bubbles/spinner"
	"github.com/charmbracelet/bubbles/textinput"
	"github.com/charmbracelet/bubbles/viewport"
	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// osExec wraps exec.Command so other files can construct *exec.Cmd
// without importing os/exec directly here.
func osExec(name string, args ...string) *exec.Cmd {
	return exec.Command(name, args...)
}

// Agent tab — the headline.
//
// Layout:
//   ┌─ input ──────────────────────────────────────────────────────────────┐
//   │ › <query>                                                             │
//   └───────────────────────────────────────────────────────────────────────┘
//   ┌─ Sources (j/k nav, o open) ─┐ ┌─ Answer (streaming) ─────────────────┐
//   │  1 [arxiv ] Distributed…    │ │ ████ token-by-token from agent       │
//   │ ▶2 [github] consensus-rs…   │ │                                       │
//   │  3 [wiki  ] Raft (consensus)│ │                                       │
//   │  ...                         │ │                                       │
//   └──────────────────────────────┘ └───────────────────────────────────────┘
//
// Vim binds: j/k navigate sources, gg/G/Ctrl+d/u scroll, o open URL,
// y yank URL, Enter (when focused on input) submit, i to enter INSERT,
// Esc back to NORMAL.
type agentTab struct {
	client *Client

	input    textinput.Model
	spinner  spinner.Model
	answer   viewport.Model
	sources  viewport.Model
	width, height int

	// State
	state    agentState
	resp     *AggregateResp
	answerSB strings.Builder
	cursor   int // selected source index
	chunkCh  chan string
	doneCh   chan agentDoneMsg

	// Stream timing
	startedAt time.Time
	firstChunkAt time.Time

	// Focus
	inputFocused bool

	// Right-pane view mode: "answer" (the streaming synthesis) or
	// "warehouse" (the scraped body for the selected source). Press v to
	// toggle. The streaming answer is preserved across mode flips.
	rightPane string // "answer" | "warehouse"
	whRow     *WarehouseRow
}

type agentState int

const (
	agentIdle agentState = iota
	agentAggregating
	agentSynthesizing
	agentDone
	agentError
)

type agentDoneMsg struct {
	full    string
	warning string
	err     error
	elapsed time.Duration
}
type agentChunkMsg string
type agentAggregatedMsg struct {
	resp *AggregateResp
	err  error
}

func newAgentTab(c *Client) *agentTab {
	in := textinput.New()
	in.Placeholder = "press i to focus, type a query, Enter to research, Esc to blur"
	in.CharLimit = 1024
	in.Prompt = "› "
	in.PromptStyle = hlSt
	in.TextStyle = lipgloss.NewStyle().Foreground(cFg)
	// NOT focused on startup. The user must press `i` (or `/`) to focus —
	// otherwise j/k/q/? would land as literal keystrokes in the input box.

	sp := spinner.New()
	sp.Spinner = spinner.MiniDot
	sp.Style = lipgloss.NewStyle().Foreground(cAccent)

	return &agentTab{
		client:       c,
		input:        in,
		spinner:      sp,
		answer:       viewport.New(0, 0),
		sources:      viewport.New(0, 0),
		inputFocused: false,
	}
}

func (t *agentTab) Title() string { return "Agent" }

// Insert tells the root whether the user is typing into a focused input —
// root uses this to decide whether single-letter keys (j, q, ?, …) should
// be treated as global shortcuts or forwarded to the input.
func (t *agentTab) Insert() bool { return t.inputFocused }

func (t *agentTab) IsStreaming() bool {
	return t.state == agentAggregating || t.state == agentSynthesizing
}

func (t *agentTab) SetSize(w, h int) {
	t.width = w
	t.height = h
	leftW := (w - 4) * 4 / 10
	rightW := (w - 4) - leftW - 2
	bodyH := h - 6 // input + status
	t.sources.Width = leftW - 4
	t.sources.Height = bodyH - 2
	t.answer.Width = rightW - 4
	t.answer.Height = bodyH - 2
}

func (t *agentTab) StatusBits() string {
	// Contextual hint comes first — tells the user what they can do RIGHT
	// NOW. Followed by state info (history / sources / streaming).
	if t.inputFocused {
		return keyStyle.Render("INPUT") + dimSt.Render("  enter ↵ submit  esc blur  ↑↓ history")
	}
	switch t.state {
	case agentIdle:
		return dimSt.Render("press ") + keyStyle.Render("i") +
			dimSt.Render(fmt.Sprintf(" to query  •  hist:%d", len(globalHistory.All())))
	case agentAggregating:
		return t.spinner.View() + dimSt.Render(" aggregating providers")
	case agentSynthesizing:
		elapsed := time.Since(t.startedAt).Round(time.Millisecond)
		ttfb := ""
		if !t.firstChunkAt.IsZero() {
			ttfb = fmt.Sprintf(" ttfb:%s", t.firstChunkAt.Sub(t.startedAt).Round(time.Millisecond))
		}
		return t.spinner.View() + dimSt.Render(fmt.Sprintf(" streaming %s%s  •  j/k scroll", elapsed, ttfb))
	case agentDone:
		if t.resp != nil {
			return okStyle.Render("✓") +
				dimSt.Render(fmt.Sprintf(" %d sources  •  j/k scroll  ^n/^p source  o open  v warehouse  i new query",
					t.resp.TotalSources))
		}
		return okStyle.Render("✓ done")
	case agentError:
		return errSt.Render("✗ error") + dimSt.Render("  press i to retry")
	}
	return ""
}

func (t *agentTab) Init() tea.Cmd { return tea.Batch(textinput.Blink, t.spinner.Tick) }

// ─── Root-driven nav messages (NORMAL mode) ─────────────────────────────

func (t *agentTab) handleNav(n NavMsg) tea.Cmd {
	switch n.Op {
	case "focus":
		t.inputFocused = true
		t.input.Focus()
		return textinput.Blink
	case "blur":
		t.inputFocused = false
		t.input.Blur()
	case "j":
		// j scrolls the ANSWER pane (the actual content you're reading).
		// Source list nav is on Ctrl-n / Ctrl-p / arrows.
		t.answer.LineDown(1)
	case "k":
		t.answer.LineUp(1)
	case "gg":
		t.answer.GotoTop()
	case "G":
		t.answer.GotoBottom()
	case "halfdown":
		t.answer.HalfViewDown()
	case "halfup":
		t.answer.HalfViewUp()
	}
	return nil
}

// sourceNext / sourcePrev move the source-list cursor and re-render. Wired
// to Ctrl-n / Ctrl-p (and ↓/↑) so j/k stay free for scrolling the answer.
func (t *agentTab) sourceNext() {
	if t.resp != nil && t.cursor < len(t.resp.Sources)-1 {
		t.cursor++
		t.renderSources()
	}
}
func (t *agentTab) sourcePrev() {
	if t.cursor > 0 {
		t.cursor--
		t.renderSources()
	}
}

func (t *agentTab) reset() {
	t.state = agentIdle
	t.resp = nil
	t.answerSB.Reset()
	t.cursor = 0
	t.input.SetValue("")
	t.input.Focus()
	t.inputFocused = true
	t.answer.SetContent("")
	t.sources.SetContent("")
	t.rightPane = "answer"
	t.whRow = nil
}

// ─── Update ───────────────────────────────────────────────────────────────

func (t *agentTab) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	var cmds []tea.Cmd
	switch msg := msg.(type) {
	case NavMsg:
		return t, t.handleNav(msg)
	case openSourceMsg:
		if t.resp != nil && msg.idx >= 0 && msg.idx < len(t.resp.Sources) {
			go openInBrowser(t.resp.Sources[msg.idx].URL)
			return t, func() tea.Msg {
				return cmdRanMsg{feedback: "opened: " + t.resp.Sources[msg.idx].URL}
			}
		}
		return t, nil
	case tea.KeyMsg:
		k := msg.String()
		// NORMAL keys handled inline so they work when the tab has focus
		// but the input is blurred. The root handles tab switches; here
		// we only act on actionable single-key ops.
		if !t.inputFocused {
			switch k {
			case "j":
				return t, t.handleNav(NavMsg{Op: "j"})
			case "k":
				return t, t.handleNav(NavMsg{Op: "k"})
			case "ctrl+n", "down":
				t.sourceNext()
				return t, nil
			case "ctrl+p", "up":
				t.sourcePrev()
				return t, nil
			case "o":
				if t.resp != nil && t.cursor < len(t.resp.Sources) {
					go openInBrowser(t.resp.Sources[t.cursor].URL)
					return t, func() tea.Msg {
						return cmdRanMsg{feedback: "opened: " + t.resp.Sources[t.cursor].URL}
					}
				}
			case "y":
				if t.resp != nil && t.cursor < len(t.resp.Sources) {
					_ = clipWrite(t.resp.Sources[t.cursor].URL)
					return t, func() tea.Msg { return cmdRanMsg{feedback: "yanked URL"} }
				}
			case "enter":
				if t.resp != nil && t.cursor < len(t.resp.Sources) {
					go openInBrowser(t.resp.Sources[t.cursor].URL)
				}
				return t, nil
			case "v":
				// Toggle: if already in warehouse view, return to the answer.
				// Otherwise, look up the warehouse row for the selected source
				// so the operator can read the actual scraped body.
				if t.rightPane == "warehouse" {
					t.rightPane = "answer"
					t.whRow = nil
					t.renderAnswer()
					return t, func() tea.Msg { return cmdRanMsg{feedback: "← answer"} }
				}
				if t.resp == nil || len(t.resp.Sources) == 0 {
					return t, func() tea.Msg {
						return cmdRanMsg{feedback: "v: no sources yet — run a query first"}
					}
				}
				if t.cursor < len(t.resp.Sources) {
					url := t.resp.Sources[t.cursor].URL
					// Show "looking up" state immediately so user sees feedback.
					t.rightPane = "warehouse-loading"
					t.renderAnswer()
					return t, t.viewWarehouseFor(url)
				}
				return t, nil
			case "i", "a", "/":
				// If the previous query is still in the input, clear it so
				// the next keystroke starts a fresh query.
				if t.state == agentDone || t.state == agentError {
					t.input.SetValue("")
					t.state = agentIdle
				}
				t.inputFocused = true
				t.input.Focus()
				return t, textinput.Blink
			case "r":
				t.reset()
				return t, nil
			case "esc":
				return t, nil
			}
		}
		// Input-focused handling. Esc ALWAYS blurs (so the user can leave
		// the input regardless of stream state). Enter submits when idle.
		if t.inputFocused {
			switch k {
			case "esc":
				t.inputFocused = false
				t.input.Blur()
				return t, nil
			case "enter":
				if t.state == agentIdle {
					q := strings.TrimSpace(t.input.Value())
					if q != "" {
						globalHistory.Add(q)
						return t, t.startResearch(q)
					}
				}
			case "up":
				if t.state == agentIdle {
					if p := globalHistory.Prev(); p != "" {
						t.input.SetValue(p)
						t.input.CursorEnd()
					}
				}
				return t, nil
			case "down":
				if t.state == agentIdle {
					if n := globalHistory.Next(); n != "" {
						t.input.SetValue(n)
						t.input.CursorEnd()
					} else {
						t.input.SetValue("")
					}
				}
				return t, nil
			}
		}
		// fall through — input consumes
	case agentViewWarehouseMsg:
		t.whRow = msg.row
		t.rightPane = "warehouse"
		t.renderAnswer()
		return t, nil
	case agentViewWarehouseErrMsg:
		// Lookup failed: drop loading state, restore the answer view, surface
		// the feedback via the same status-bar channel.
		t.rightPane = "answer"
		t.renderAnswer()
		return t, func() tea.Msg { return cmdRanMsg{feedback: msg.feedback} }
	case agentAggregatedMsg:
		if msg.err != nil {
			t.state = agentError
			t.answerSB.WriteString(errSt.Render("aggregate failed: ") + msg.err.Error())
			t.renderAnswer()
			return t, nil
		}
		t.resp = msg.resp
		t.cursor = 0
		t.state = agentSynthesizing
		t.renderSources()
		return t, t.startSynthesis()
	case agentChunkMsg:
		if t.firstChunkAt.IsZero() {
			t.firstChunkAt = time.Now()
		}
		t.answerSB.WriteString(string(msg))
		t.renderAnswer()
		return t, t.readChunk()
	case agentDoneMsg:
		if msg.err != nil {
			t.state = agentError
			t.answerSB.WriteString("\n\n" + errSt.Render("error: "+msg.err.Error()))
		} else {
			t.state = agentDone
			if msg.warning != "" {
				t.answerSB.WriteString("\n\n" + warnSt.Render("⚠ "+msg.warning))
			}
			t.answerSB.WriteString("\n\n" + dimSt.Render(fmt.Sprintf("synthesis complete in %s",
				msg.elapsed.Round(time.Millisecond))))
		}
		t.renderAnswer()
		return t, nil
	case spinner.TickMsg:
		var c tea.Cmd
		t.spinner, c = t.spinner.Update(msg)
		cmds = append(cmds, c)
	case animTick:
		// Re-render to advance the streaming visual
		if t.IsStreaming() {
			t.renderAnswer()
		}
	}

	// Forward keystrokes to whichever component should own them.
	if t.inputFocused {
		var c tea.Cmd
		t.input, c = t.input.Update(msg)
		cmds = append(cmds, c)
	} else {
		// Let the viewports react to mouse-wheel and unhandled keys.
		var c1, c2 tea.Cmd
		t.answer, c1 = t.answer.Update(msg)
		t.sources, c2 = t.sources.Update(msg)
		cmds = append(cmds, c1, c2)
	}
	return t, tea.Batch(cmds...)
}

// ─── Commands ─────────────────────────────────────────────────────────────

// viewWarehouseFor fetches the warehouse row matching the URL via the cheap
// /content/by-url lookup (no FTS5 search needed). Replaces the answer pane
// content with the full scraped body so the operator can verify what landed.
func (t *agentTab) viewWarehouseFor(rawURL string) tea.Cmd {
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
		defer cancel()
		row, err := t.client.WarehouseGetByURL(ctx, rawURL)
		if err != nil {
			if err.Error() == "not found" {
				return agentViewWarehouseErrMsg{
					feedback: "not in warehouse: " + shortenURL(rawURL),
				}
			}
			return agentViewWarehouseErrMsg{
				feedback: "warehouse lookup failed: " + err.Error(),
			}
		}
		return agentViewWarehouseMsg{row: row}
	}
}

type agentViewWarehouseErrMsg struct{ feedback string }

// shortenURL trims a URL for status display.
func shortenURL(u string) string {
	if len(u) > 60 {
		return u[:57] + "..."
	}
	return u
}

type agentViewWarehouseMsg struct{ row *WarehouseRow }

func (t *agentTab) startResearch(q string) tea.Cmd {
	t.state = agentAggregating
	t.answerSB.Reset()
	t.resp = nil
	t.cursor = 0
	t.startedAt = time.Now()
	t.firstChunkAt = time.Time{}
	t.input.Blur()
	t.inputFocused = false
	return func() tea.Msg {
		ctx, cancel := context.WithTimeout(context.Background(), 180*time.Second)
		defer cancel()
		resp, err := t.client.Aggregate(ctx, AggregateReq{
			Query:           q,
			MaxResults:      12,
			IncludeWH:       true,
			Reconcile:       true,
			EnableScraping:  true,
			MaxScrapeURLs:   6,
			EnableSynthesis: false,
		})
		return agentAggregatedMsg{resp: resp, err: err}
	}
}

func (t *agentTab) startSynthesis() tea.Cmd {
	if t.resp == nil {
		return nil
	}
	t.chunkCh = make(chan string, 64)
	t.doneCh = make(chan agentDoneMsg, 1)
	srcs := make([]SynthesizeSource, 0, len(t.resp.Sources))
	for _, s := range t.resp.Sources {
		srcs = append(srcs, SynthesizeSource{
			Title: s.Title, URL: s.URL, Description: s.Description, Source: s.Source,
		})
	}
	req := SynthesizeReq{Query: t.resp.Query, Sources: srcs}
	start := time.Now()
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 240*time.Second)
		defer cancel()
		full, warning, err := t.client.SynthesizeStream(ctx, req, func(ch string) {
			t.chunkCh <- ch
		})
		close(t.chunkCh)
		t.doneCh <- agentDoneMsg{full: full, warning: warning, err: err, elapsed: time.Since(start)}
	}()
	return t.readChunk()
}

func (t *agentTab) readChunk() tea.Cmd {
	return func() tea.Msg {
		ch, ok := <-t.chunkCh
		if !ok {
			return <-t.doneCh
		}
		return agentChunkMsg(ch)
	}
}

// ─── Rendering ────────────────────────────────────────────────────────────

func (t *agentTab) renderSources() {
	var b strings.Builder
	if t.resp == nil {
		b.WriteString(dimSt.Render("  no sources yet — Enter a query"))
		t.sources.SetContent(b.String())
		return
	}
	for i, s := range t.resp.Sources {
		marker := "  "
		if i == t.cursor {
			marker = keyStyle.Render("▶ ")
		}
		ds := styleForDomain(s.Domain)
		src := s.Source
		if len(src) > 14 {
			src = src[:14]
		}
		title := s.Title
		maxW := t.sources.Width - 22
		if maxW < 20 {
			maxW = 20
		}
		if len(title) > maxW {
			title = title[:maxW-1] + "…"
		}
		line := fmt.Sprintf("%s%2d %s %s", marker, i+1, ds.Render(fmt.Sprintf("[%-12s]", src)), title)
		if i == t.cursor {
			line = lipgloss.NewStyle().Background(lipgloss.Color("#2a2a37")).Render(line)
		}
		b.WriteString(line + "\n")
	}
	// Consensus footer
	if len(t.resp.Consensus) > 0 {
		b.WriteString("\n" + hlSt.Render(fmt.Sprintf("─ Consensus (%d) ─\n", len(t.resp.Consensus))))
		for _, c := range t.resp.Consensus {
			marker := dimSt.Render("?")
			switch c.Quality {
			case "verified":
				marker = okStyle.Render("✓")
			case "probable":
				marker = warnSt.Render("~")
			}
			b.WriteString(fmt.Sprintf("  %s [%.2f] %s\n", marker, c.Confidence, c.Claim))
		}
	}
	t.sources.SetContent(b.String())
}

func (t *agentTab) renderAnswer() {
	// Mode toggle: warehouse view replaces the answer pane with the stored body.
	if t.rightPane == "warehouse-loading" {
		t.answer.SetContent(t.spinner.View() +
			dimSt.Render(" fetching warehouse row for selected source…"))
		return
	}
	if t.rightPane == "warehouse" && t.whRow != nil {
		r := t.whRow
		var b strings.Builder
		b.WriteString(hlSt.Render(fmt.Sprintf("WAREHOUSE VIEW — id=%d  wc=%d  %s\n",
			r.ID, r.WordCount, r.SourceDomain)))
		b.WriteString(dimSt.Render(r.URL) + "\n")
		if r.Title != "" {
			b.WriteString("title: " + r.Title + "\n")
		}
		b.WriteString(dimSt.Render("press v again to return to the answer") + "\n")
		b.WriteString(strings.Repeat("─", 60) + "\n\n")
		b.WriteString(r.Markdown)
		t.answer.SetContent(b.String())
		t.answer.GotoTop()
		return
	}

	body := t.answerSB.String()
	if body == "" {
		switch t.state {
		case agentIdle:
			body = "\n  " + hlSt.Render("Welcome to DSS Agent") + "\n\n" +
				dimSt.Render("  i  ") + "focus query input\n" +
				dimSt.Render("     ") + "type your question and press Enter\n\n" +
				dimSt.Render("  Then:\n") +
				dimSt.Render("  j/k    ") + "scroll this answer pane\n" +
				dimSt.Render("  ^n/^p  ") + "next/prev source (or ↓/↑)\n" +
				dimSt.Render("  o      ") + "open cursored source URL\n" +
				dimSt.Render("  v      ") + "view warehouse body for source\n" +
				dimSt.Render("  y      ") + "yank URL\n\n" +
				dimSt.Render("  tab/^l/^h") + "  switch tab    " + dimSt.Render("?") + " help    " + dimSt.Render("q") + " quit"
		case agentAggregating:
			body = t.spinner.View() + dimSt.Render(" fanning out across providers, scraping, reconciling…")
		case agentSynthesizing:
			body = t.spinner.View() + dimSt.Render(" waiting for the first token…")
		}
	}
	if t.state == agentSynthesizing {
		if t.tickEven() {
			body = body + dimSt.Render("█")
		} else {
			body = body + " "
		}
	}
	t.answer.SetContent(body)
	if t.IsStreaming() {
		t.answer.GotoBottom()
	}
}

func (t *agentTab) tickEven() bool {
	// crude blinker tied to time (no global tick coupling needed at the tab level)
	return time.Now().UnixMilli()/350%2 == 0
}

// ─── View ────────────────────────────────────────────────────────────────

func (t *agentTab) View() string {
	// Refuse to render the body before we know the terminal size. The first
	// render fires before WindowSizeMsg arrives — with width=0 the layout
	// math yields negative numbers and lipgloss draws minimum-size boxes
	// (the "tiny squares" bug). Show a single line until size is known.
	if t.width < 40 || t.height < 8 {
		return dimSt.Render("  initializing…")
	}

	// Input
	inputView := t.input.View()
	box := inputBox
	if t.inputFocused {
		box = inputBoxInsert
	}
	header := box.Width(t.width - 4).Render(inputView)

	// Body: split sources | answer
	leftW := (t.width - 4) * 4 / 10
	rightW := (t.width - 4) - leftW - 2
	bodyH := t.height - 6
	if bodyH < 3 {
		bodyH = 3
	}

	leftBox := contentBox
	rightBox := contentBox
	if t.inputFocused {
		// nothing selected
	} else if t.IsStreaming() {
		rightBox = focusBox
	} else if t.state == agentDone {
		leftBox = focusBox
	}

	left := lipgloss.JoinVertical(lipgloss.Left,
		dimSt.Render(fmt.Sprintf(" sources (%d) ", func() int {
			if t.resp == nil {
				return 0
			}
			return len(t.resp.Sources)
		}())),
		leftBox.Width(leftW - 2).Height(bodyH - 1).Render(t.sources.View()),
	)
	right := lipgloss.JoinVertical(lipgloss.Left,
		dimSt.Render(" answer "),
		rightBox.Width(rightW - 2).Height(bodyH - 1).Render(t.answer.View()),
	)

	body := lipgloss.JoinHorizontal(lipgloss.Top, left, " ", right)

	return lipgloss.JoinVertical(lipgloss.Left, header, body)
}

// ─── Clipboard (best-effort) ─────────────────────────────────────────────

func clipWrite(s string) error {
	for _, args := range [][]string{
		{"xclip", "-selection", "clipboard"},
		{"wl-copy"},
		{"pbcopy"},
	} {
		c := osExec(args[0], args[1:]...)
		c.Stdin = strings.NewReader(s)
		if err := c.Run(); err == nil {
			return nil
		}
	}
	return fmt.Errorf("no clipboard tool")
}
