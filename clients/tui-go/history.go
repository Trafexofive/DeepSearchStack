// Persistent query history. Stored at $XDG_DATA_HOME/dss/history (or
// ~/.local/share/dss/history). One query per line, deduped, capped at 200.
package main

import (
	"bufio"
	"os"
	"path/filepath"
	"strings"
	"sync"
)

const historyCap = 200

type History struct {
	mu    sync.Mutex
	path  string
	items []string
	pos   int // -1 = no nav, else index into items reversed (most recent first)
}

func NewHistory() *History {
	h := &History{path: historyPath(), pos: -1}
	h.load()
	return h
}

func historyPath() string {
	if x := os.Getenv("XDG_DATA_HOME"); x != "" {
		return filepath.Join(x, "dss", "history")
	}
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".local", "share", "dss", "history")
}

func (h *History) load() {
	h.mu.Lock()
	defer h.mu.Unlock()
	f, err := os.Open(h.path)
	if err != nil {
		return
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line != "" {
			h.items = append(h.items, line)
		}
	}
}

func (h *History) Add(q string) {
	q = strings.TrimSpace(q)
	if q == "" {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	// dedupe: remove any prior occurrence
	out := h.items[:0]
	for _, x := range h.items {
		if x != q {
			out = append(out, x)
		}
	}
	h.items = append(out, q)
	if len(h.items) > historyCap {
		h.items = h.items[len(h.items)-historyCap:]
	}
	h.pos = -1
	h.save()
}

func (h *History) save() {
	_ = os.MkdirAll(filepath.Dir(h.path), 0o755)
	tmp := h.path + ".tmp"
	f, err := os.Create(tmp)
	if err != nil {
		return
	}
	w := bufio.NewWriter(f)
	for _, x := range h.items {
		w.WriteString(x)
		w.WriteByte('\n')
	}
	w.Flush()
	f.Close()
	os.Rename(tmp, h.path)
}

// Prev returns the older entry (called on ↑). Empty string when exhausted.
func (h *History) Prev() string {
	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.items) == 0 {
		return ""
	}
	if h.pos < len(h.items)-1 {
		h.pos++
	}
	return h.items[len(h.items)-1-h.pos]
}

// Next returns the newer entry (called on ↓). Empty when back at present.
func (h *History) Next() string {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.pos <= 0 {
		h.pos = -1
		return ""
	}
	h.pos--
	return h.items[len(h.items)-1-h.pos]
}

func (h *History) ResetNav() {
	h.mu.Lock()
	h.pos = -1
	h.mu.Unlock()
}

func (h *History) All() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	out := make([]string, len(h.items))
	copy(out, h.items)
	return out
}
