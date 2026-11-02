// dss-tui — modeless terminal client for DeepSearchStack.
//
// No INSERT/NORMAL/COMMAND modes. Just two contexts that the user can see at
// a glance: an input is either focused (typing types) or it isn't (vim keys
// act on the visible list). Root handles tab switching + the help overlay;
// everything else is delegated to the active tab.
//
// Shared key vocabulary across tabs:
//   tab/S-tab/1..7  switch tab
//   j/k             cursor down/up
//   gg/G/C-d/C-u    list/viewer motion
//   Enter           open / reload selected
//   o / y           open URL in browser / yank URL
//   /               focus search input (where applicable)
//   i               focus the tab's primary input
//   r               refresh
//   Esc             blur input (return to vim keys)
//   ? / q           help / quit
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/lipgloss"
)

// ─── Tab interface ─────────────────────────────────────────────────────────

type tabModel interface {
	tea.Model
	Title() string
	SetSize(w, h int)
	// Insert returns true when the tab's input is focused (user is typing).
	// Root uses this to decide whether to capture tab-switching keys.
	Insert() bool
	// StatusBits is rendered in the bottom-left status bar.
	StatusBits() string
}

// Tab-level nav messages (sent by root for global vim ops). Tabs can ignore
// what they don't care about.
type NavMsg struct {
	Op string // "j" "k" "gg" "G" "halfdown" "halfup" "open" "yank" "refresh" "esc" "focus" "blur"
}

// ─── Globals ───────────────────────────────────────────────────────────────

var globalHistory = NewHistory()

// ─── Root model ────────────────────────────────────────────────────────────

const (
	tabAgent = iota
	tabSearch
	tabCrawl
	tabWarehouse
	tabRender
	tabModels
	tabProviders
	numTabs
)

var tabNames = []string{"Agent", "Search", "Crawl", "Warehouse", "Render", "Models", "Providers"}

type rootModel struct {
	tabs   []tabModel
	active int

	// Transient one-line feedback shown in the status bar (yanked, opened,
	// "not in warehouse", etc.). Auto-clears on next key.
	feedback string
	helpOn   bool

	width, height int
	status        string
	client        *Client

	lastG time.Time
}

type healthMsg struct {
	ok  bool
	err string
}

type cmdRanMsg struct{ feedback string }
type switchTabMsg struct{ idx int }
type openSourceMsg struct{ idx int }
type animTick struct{}

func tickEvery() tea.Cmd {
	return tea.Tick(150*time.Millisecond, func(time.Time) tea.Msg { return animTick{} })
}

func newRoot(c *Client) rootModel {
	return rootModel{
		client: c,
		tabs: []tabModel{
			newAgentTab(c),
			newSearchTab(c),
			newCrawlTab(c),
			newWarehouseTab(c),
			newRenderTab(c),
			newModelsTab(c),
			newProvidersTab(c),
		},
	}
}

func (m rootModel) Init() tea.Cmd {
	cmds := []tea.Cmd{tickEvery()}
	cmds = append(cmds, func() tea.Msg {
		err := m.client.Health(context.Background())
		if err != nil {
			return healthMsg{ok: false, err: err.Error()}
		}
		return healthMsg{ok: true}
	})
	for _, t := range m.tabs {
		cmds = append(cmds, t.Init())
	}
	return tea.Batch(cmds...)
}

func (m rootModel) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width = msg.Width
		m.height = msg.Height
		for _, t := range m.tabs {
			t.SetSize(msg.Width, msg.Height-4)
		}
	case healthMsg:
		if msg.ok {
			m.status = okStyle.Render("●") + dimSt.Render(" stack ok @ "+m.client.BaseURL)
		} else {
			m.status = errSt.Render("●") + dimSt.Render(" "+msg.err)
		}
	case animTick:
		// Broadcast to tabs that care.
		for i, t := range m.tabs {
			u, _ := t.Update(msg)
			m.tabs[i] = u.(tabModel)
		}
		return m, tickEvery()
	case cmdRanMsg:
		m.feedback = msg.feedback
		return m, nil
	case switchTabMsg:
		if msg.idx >= 0 && msg.idx < numTabs {
			m.active = msg.idx
		}
		return m, nil
	case tea.KeyMsg:
		key := msg.String()
		// Any key dismisses the help overlay.
		if m.helpOn {
			m.helpOn = false
			return m, nil
		}
		// Clear the transient one-line feedback on the next key press.
		if m.feedback != "" {
			m.feedback = ""
		}

		// Tab switching + global helpers fire ONLY when an input isn't
		// receiving keystrokes (so typing a query doesn't jump tabs).
		typing := m.tabs[m.active].Insert()

		// Ctrl-based motion + tab nav work even while typing — they don't
		// collide with text input.
		switch key {
		case "ctrl+c":
			return m, tea.Quit
		case "ctrl+l":
			// Next tab even from inside an input.
			m.active = (m.active + 1) % numTabs
			return m, nil
		case "ctrl+h":
			m.active = (m.active - 1 + numTabs) % numTabs
			return m, nil
		case "ctrl+d":
			if !typing {
				return m.delegate(NavMsg{Op: "halfdown"})
			}
		case "ctrl+u":
			if !typing {
				return m.delegate(NavMsg{Op: "halfup"})
			}
		}

		if !typing {
			switch key {
			case "q":
				return m, tea.Quit
			case "?":
				m.helpOn = true
				return m, nil
			case "tab":
				m.active = (m.active + 1) % numTabs
				return m, nil
			case "shift+tab":
				m.active = (m.active - 1 + numTabs) % numTabs
				return m, nil
			case "1", "2", "3", "4", "5", "6", "7":
				n := int(key[0] - '1')
				if n < numTabs {
					m.active = n
				}
				return m, nil
			case "g":
				// gg motion
				if time.Since(m.lastG) < 600*time.Millisecond {
					m.lastG = time.Time{}
					return m.delegate(NavMsg{Op: "gg"})
				}
				m.lastG = time.Now()
				return m, nil
			case "G":
				return m.delegate(NavMsg{Op: "G"})
			}
		}
	}

	// Key messages stay targeted at the ACTIVE tab (so j/k doesn't move the
	// hidden Warehouse cursor when you're typing on Agent).
	// Non-key messages BROADCAST to all tabs — a tab can fire HTTP Cmds at
	// Init() time and its response (whHitsMsg, agentChunkMsg, etc.) must
	// reach the originating tab regardless of which tab is currently in
	// view. Delivering only to the active tab was THE bug behind "TUI hangs
	// everywhere" — data landed but went to the wrong tab and was dropped.
	if _, isKey := msg.(tea.KeyMsg); isKey {
		updated, cmd := m.tabs[m.active].Update(msg)
		m.tabs[m.active] = updated.(tabModel)
		return m, cmd
	}
	var cmds []tea.Cmd
	for i, tab := range m.tabs {
		updated, cmd := tab.Update(msg)
		m.tabs[i] = updated.(tabModel)
		if cmd != nil {
			cmds = append(cmds, cmd)
		}
	}
	return m, tea.Batch(cmds...)
}

func (m rootModel) delegate(n NavMsg) (tea.Model, tea.Cmd) {
	updated, cmd := m.tabs[m.active].Update(n)
	m.tabs[m.active] = updated.(tabModel)
	return m, cmd
}

func openInBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	default:
		if b := os.Getenv("BROWSER"); b != "" {
			cmd = exec.Command(b, url)
		} else {
			cmd = exec.Command("xdg-open", url)
		}
	}
	_ = cmd.Start()
}

// ─── View ──────────────────────────────────────────────────────────────────

func (m rootModel) View() string {
	// Header: title + numbered tabs.
	var pills []string
	for i, n := range tabNames {
		s := tabStyle.Render(fmt.Sprintf("%d %s", i+1, n))
		if i == m.active {
			s = tabActive.Render(fmt.Sprintf("%d %s", i+1, n))
		}
		pills = append(pills, s)
	}
	header := lipgloss.JoinHorizontal(lipgloss.Top,
		titleStyle.Render(" DSS "),
		lipgloss.JoinHorizontal(lipgloss.Top, pills...),
	)

	body := m.tabs[m.active].View()

	// Status bar: tab bits • feedback • health • help hint.
	// No modal pill — the active tab's status text says what's going on.
	left := m.tabs[m.active].StatusBits()
	right := helpHint.Render("? help  q quit")

	feedback := ""
	if m.feedback != "" {
		feedback = warnSt.Render(m.feedback)
	}

	gap := m.width - lipgloss.Width(left) - lipgloss.Width(m.status) -
		lipgloss.Width(feedback) - lipgloss.Width(right) - 6
	if gap < 1 {
		gap = 1
	}
	statusLine := lipgloss.JoinHorizontal(lipgloss.Top,
		left, "  ", feedback, strings.Repeat(" ", gap), m.status, "  ", right,
	)
	bottom := statusStyle.Render(statusLine)

	out := lipgloss.JoinVertical(lipgloss.Left, header, body, bottom)
	if m.helpOn {
		box := overlayBox.Render(helpOverlayBody())
		return lipgloss.Place(m.width, m.height, lipgloss.Center, lipgloss.Center, box,
			lipgloss.WithWhitespaceChars(" "))
	}
	return out
}

func helpOverlayBody() string {
	sec := func(t string) string { return hlSt.Render(t) }
	row := func(k, d string) string {
		return keyStyle.Render(fmt.Sprintf("%-14s", k)) + dimSt.Render(d)
	}
	return strings.Join([]string{
		sec("DSS TUI — keys (any key dismisses)"),
		"",
		sec("Switch tab"),
		row("tab / S-tab", "next / prev"),
		row("ctrl+l / ^h", "next / prev (even while typing)"),
		row("1..7", "jump to tab N"),
		"",
		sec("Move"),
		row("j / k", "Agent: scroll answer  •  Warehouse: cursor"),
		row("ctrl+n / ^p", "Agent: next/prev source"),
		row("↓ / ↑", "same as ctrl+n / ctrl+p"),
		row("g g / G", "top / bottom"),
		row("ctrl+d/u", "half-page"),
		"",
		sec("Act on selection"),
		row("Enter", "open / reload"),
		row("o", "open URL in $BROWSER"),
		row("y", "yank URL to clipboard"),
		row("v", "Agent: peek warehouse body for source"),
		"",
		sec("Input boxes"),
		row("i", "focus the tab's primary input"),
		row("/", "Warehouse: focus search"),
		row("#", "Warehouse: jump-by-id"),
		row("Enter", "submit"),
		row("Esc", "blur input (back to vim keys)"),
		row("↑ / ↓", "history (Agent)"),
		"",
		sec("Global"),
		row("r", "refresh"),
		row("?", "this help"),
		row("q / ^C", "quit"),
	}, "\n")
}

func main() {
	base := flag.String("base", envOr("DSS_BASE_URL", "http://localhost:8083"), "DSS nginx base URL")
	debug := flag.Bool("debug", envOr("DSS_TUI_DEBUG", "") != "", "Write every message + HTTP call to /tmp/dss-tui.log")
	noAlt := flag.Bool("no-alt", envOr("DSS_TUI_NO_ALT", "") != "", "Disable alt-screen (helps in some terminals)")
	flag.Parse()

	if *debug {
		f, err := tea.LogToFile("/tmp/dss-tui.log", "dss-tui")
		if err == nil {
			defer f.Close()
			log.Printf("─── dss-tui starting, base=%s ───", *base)
		}
	}

	client := NewClient(*base)
	client.Debug = *debug

	opts := []tea.ProgramOption{tea.WithMouseAllMotion()}
	if !*noAlt {
		opts = append(opts, tea.WithAltScreen())
	}
	p := tea.NewProgram(newRoot(client), opts...)
	if _, err := p.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "fatal:", err)
		os.Exit(1)
	}
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
