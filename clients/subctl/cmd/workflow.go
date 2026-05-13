package cmd

import (
	"fmt"
	"os"
)

func workflowCmd(args []string) {
	baseURL, fs := parseFlags(args)

	if len(args) == 0 || args[0] == "-h" || args[0] == "--help" {
		fmt.Print(`Usage:
  subctl workflow list           List available workflows
  subctl workflow run <name>     Execute a workflow
  subctl workflow seo <topic>    Run seo_content_loop

Examples:
  subctl workflow list
  subctl workflow run seo_content_loop
  subctl workflow seo "Rust async executors"
`)
		return
	}

	sub := args[0]
	rest := args[1:]

	initClient(baseURL)

	switch sub {
	case "list":
		workflowList()
	case "run":
		workflowRun(rest)
	case "seo":
		workflowSEO(rest)
	default:
		fmt.Fprintf(os.Stderr, "unknown workflow subcommand: %s\n", sub)
		os.Exit(1)
	}
	_ = fs // used in parseFlags
}

func workflowList() {
	workflows, err := c.ListWorkflows()
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("%-25s %8s %5s  %s\n", "NAME", "VERSION", "STEPS", "DESCRIPTION")
	fmt.Println("─────────────────────────────────────────────────────────────────────")
	for _, w := range workflows {
		desc := Truncate(w.Description, 50)
		fmt.Printf("%-25s %8s %5d  %s\n", w.Name, w.Version, w.Steps, desc)
	}
	fmt.Printf("\n%d workflows available\n", len(workflows))
}

func workflowRun(args []string) {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "usage: subctl workflow run <name>")
		os.Exit(1)
	}
	name := args[0]
	params := map[string]interface{}{
		"topic":   "test topic",
		"keyword": "test",
	}

	fmt.Printf("▶ Running workflow: %s\n", name)
	fmt.Println("  (this may take 60-120s — workflow steps call LLMs)\n")

	result, err := c.ExecuteWorkflow(name, params)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Workflow: %s  Status: %s\n", result.Workflow, Emoji(result.Status))
	for _, step := range result.Steps {
		errStr := ""
		if step.Error != "" {
			errStr = fmt.Sprintf("  error: %s", Truncate(step.Error, 40))
		}
		fmt.Printf("  %-12s %-10s %5dms%s\n", step.StepID, Emoji(step.Status), step.DurationMs, errStr)
	}
}

func workflowSEO(args []string) {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "usage: subctl workflow seo <topic>")
		os.Exit(1)
	}
	topic := args[0]
	params := map[string]interface{}{
		"topic":   topic,
		"keyword": topic,
		"tone":    "technical",
	}

	fmt.Printf("▶ Running seo_content_loop: %s\n", topic)
	fmt.Println("  research → outline → generate → audit → publish\n")

	result, err := c.ExecuteWorkflow("seo_content_loop", params)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("Workflow: %s  Status: %s\n", result.Workflow, Emoji(result.Status))
	for _, step := range result.Steps {
		errStr := ""
		if step.Error != "" {
			errStr = fmt.Sprintf("  error: %s", Truncate(step.Error, 40))
		}
		output := ""
		if step.Status == "completed" {
			switch step.StepID {
			case "research":
				output = "research notes"
			case "outline", "generate":
				if m, ok := step.Output.(map[string]interface{}); ok {
					if content, ok := m["content"].(string); ok {
						output = fmt.Sprintf("%d chars", len(content))
					}
				}
			case "publish":
				output = "done"
			}
		}
		fmt.Printf("  %-12s %-10s %5dms  %s%s\n", step.StepID, Emoji(step.Status), step.DurationMs, output, errStr)
	}
}
