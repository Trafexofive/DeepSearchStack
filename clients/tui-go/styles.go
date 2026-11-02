package main

import "github.com/charmbracelet/lipgloss"

// Palette — kanagawa-ish, terminal-readable, not eye-stabbing.
var (
	cBg       = lipgloss.Color("#1f1f28")
	cFg       = lipgloss.Color("#dcd7ba")
	cMuted    = lipgloss.Color("#727169")
	cDim      = lipgloss.Color("#54546d")
	cPrimary  = lipgloss.Color("#7aa89f")
	cAccent   = lipgloss.Color("#7fb4ca")
	cOK       = lipgloss.Color("#98bb6c")
	cWarn     = lipgloss.Color("#dca561")
	cErr      = lipgloss.Color("#e46876")
	cMagenta  = lipgloss.Color("#957fb8")
	cYellow   = lipgloss.Color("#e6c384")
	cInsert   = lipgloss.Color("#76946a")
	cNormal   = lipgloss.Color("#7e9cd8")
	cCommand  = lipgloss.Color("#e6c384")

	// Tab pills.
	tabStyle = lipgloss.NewStyle().Foreground(cMuted).Padding(0, 2)
	tabActive = lipgloss.NewStyle().Bold(true).
			Foreground(lipgloss.Color("#1f1f28")).Background(cPrimary).Padding(0, 2)

	titleStyle = lipgloss.NewStyle().Bold(true).Foreground(cAccent).Padding(0, 1)

	// Status line.
	statusStyle = lipgloss.NewStyle().Foreground(cMuted).Padding(0, 1)
	helpHint    = lipgloss.NewStyle().Foreground(cDim)

	// Text styles.
	okStyle  = lipgloss.NewStyle().Foreground(cOK).Bold(true)
	warnSt   = lipgloss.NewStyle().Foreground(cWarn).Bold(true)
	errSt    = lipgloss.NewStyle().Foreground(cErr).Bold(true)
	dimSt    = lipgloss.NewStyle().Foreground(cDim)
	mutedSt  = lipgloss.NewStyle().Foreground(cMuted)
	hlSt     = lipgloss.NewStyle().Foreground(cAccent).Bold(true)
	keyStyle = lipgloss.NewStyle().Foreground(cYellow).Bold(true)

	// Boxes.
	inputBox = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(cPrimary).Padding(0, 1)
	inputBoxInsert = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(cInsert).Padding(0, 1)
	contentBox = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(cDim).Padding(0, 1)
	focusBox = lipgloss.NewStyle().
			Border(lipgloss.RoundedBorder()).
			BorderForeground(cAccent).Padding(0, 1)
	overlayBox = lipgloss.NewStyle().
			Border(lipgloss.ThickBorder()).
			BorderForeground(cMagenta).
			Background(cBg).Foreground(cFg).Padding(1, 2)

	// Source domain pills.
	domainAcad = lipgloss.NewStyle().Foreground(cAccent)
	domainCode = lipgloss.NewStyle().Foreground(cMagenta)
	domainEnc  = lipgloss.NewStyle().Foreground(cYellow)
	domainQA   = lipgloss.NewStyle().Foreground(cWarn)
	domainWeb  = lipgloss.NewStyle().Foreground(cPrimary)
	domainSoc  = lipgloss.NewStyle().Foreground(cOK)
	domainInt  = lipgloss.NewStyle().Foreground(cMuted)
)

// Compat aliases — older tab files use these names. Keep them as thin
// references so we don't have to rewrite every tab today.
var (
	errStyle        = errSt
	warnStyle       = warnSt
	dimStyle        = dimSt
	hlStyle         = hlSt
	inputBoxStyle   = inputBox
	contentBoxStyle = contentBox
)

func styleForDomain(d string) lipgloss.Style {
	switch d {
	case "academic":
		return domainAcad
	case "code":
		return domainCode
	case "encyclopedia":
		return domainEnc
	case "q_and_a":
		return domainQA
	case "social", "social_news":
		return domainSoc
	case "internal", "warehouse", "unknown":
		return domainInt
	default:
		return domainWeb
	}
}
