# ======================================================================================
# Makefile - The Master Control Program
# ======================================================================================
# "The distance between thought and action, minimized."

# --- Cosmetics ---
RED     := \033[0;31m
GREEN   := \033[0;32m
YELLOW  := \033[1;33m
BLUE    := \033[0;34m
PURPLE  := \033[0;35m
CYAN    := \033[0;36m
GRAY    := \033[0;90m
BOLD    := \033[1m
NC      := \033[0m

# --- Configuration ---
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

ENV_FILE := infra/env/.dev.env
ENV_TEMPLATE := infra/env/.env.template

-include $(ENV_FILE)
PROJECT_NAME ?= deepsearch-stack

STACK ?= full
COMPOSE_DIR := infra
NETWORK_NAME := deepsearch_net

# Auto-detect compose file
ifeq ($(STACK),full)
    COMPOSE_FILE := $(COMPOSE_DIR)/docker-compose.yml
else
    COMPOSE_FILE := $(COMPOSE_DIR)/docker-compose.$(STACK).yml
endif

COMPOSE_PROJECT := $(PROJECT_NAME)-$(STACK)
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) -p $(COMPOSE_PROJECT)

# Service parameter (optional, applies to single service)
service ?=
SERVICE_FLAG := $(if $(service),$(service),)

.DEFAULT_GOAL := help
.PHONY: help validate-stack validate-service env-check setup up down restart stop logs ps status build rebuild clean fclean prune shell exec health list-stacks create-networks full full-down full-restart light light-down light-restart test test-down test-restart

# ======================================================================================
# VALIDATION HELPERS
# ======================================================================================

validate-stack:
	@if [ ! -f "$(COMPOSE_FILE)" ]; then \
		echo -e "$(RED)✖ Stack '$(STACK)' not found: $(COMPOSE_FILE)$(NC)"; \
		echo -e "$(YELLOW)Available stacks:$(NC)"; \
		ls -1 $(COMPOSE_DIR)/docker-compose*.yml | sed 's|$(COMPOSE_DIR)/docker-compose\.||; s|\.yml||' | sed 's/^/  - /'; \
		exit 1; \
	fi

validate-service: validate-stack
	@if [ -n "$(service)" ]; then \
		if ! $(COMPOSE) config --services 2>/dev/null | grep -q "^$(service)$$"; then \
			echo -e "$(RED)✖ Service '$(service)' not found in stack '$(STACK)'$(NC)"; \
			echo -e "$(YELLOW)Available services:$(NC)"; \
			$(COMPOSE) config --services 2>/dev/null | sed 's/^/  - /'; \
			exit 1; \
		fi; \
	fi

env-check:
	@if [ ! -f "$(ENV_FILE)" ]; then \
		echo -e "$(YELLOW)⚠  Environment file not found: $(ENV_FILE)$(NC)"; \
		if [ -f "$(ENV_TEMPLATE)" ]; then \
			echo -e "$(BLUE)Creating from template...$(NC)"; \
			cp $(ENV_TEMPLATE) $(ENV_FILE); \
			echo -e "$(GREEN)✅ Created $(ENV_FILE) - please review and update$(NC)"; \
		else \
			echo -e "$(RED)✖ No template found. Create $(ENV_FILE) manually.$(NC)"; \
			exit 1; \
		fi; \
	else \
		echo -e "$(GREEN)✅ Environment file exists: $(ENV_FILE)$(NC)"; \
	fi

# ======================================================================================
# CORE OPERATIONS
# ======================================================================================

setup: env-check create-networks
	@echo -e "$(GREEN)✅ Setup complete$(NC)"

create-networks:
	@echo -e "$(BLUE)🌐 Creating necessary networks...$(NC)"
	@docker network create $(NETWORK_NAME) 2>/dev/null || echo -e "$(GRAY)  Network $(NETWORK_NAME) already exists$(NC)"
	@echo -e "$(GREEN)✅ Networks ready.$(NC)"

up: validate-service setup
	@echo -e "$(BLUE)🚀 Starting stack: $(STACK)$(NC)"
	@$(COMPOSE) up -d $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Stack running$(NC)"
	@$(MAKE) --no-print-directory list-stacks

down: validate-stack
	@echo -e "$(YELLOW)🛑 Stopping stack: $(STACK)$(NC)"
	@$(COMPOSE) down $(if $(service),--remove-orphans,)
	@echo -e "$(GREEN)✅ Stack stopped$(NC)"
	@$(MAKE) --no-print-directory list-stacks

restart: validate-service
	@echo -e "$(BLUE)♻️  Restarting: $(STACK)$(if $(service), [$(service)],)$(NC)"
	@$(COMPOSE) restart $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Restart complete$(NC)"

stop: validate-service
	@echo -e "$(YELLOW)⏸️  Stopping: $(STACK)$(if $(service), [$(service)],)$(NC)"
	@$(COMPOSE) stop $(SERVICE_FLAG)

start: validate-service
	@echo -e "$(BLUE)▶️  Starting: $(STACK)$(if $(service), [$(service)],)$(NC)"
	@$(COMPOSE) start $(SERVICE_FLAG)

# ======================================================================================
# BUILD & REBUILD
# ======================================================================================

build: validate-service
	@echo -e "$(BLUE)🔨 Building: $(STACK)$(if $(service), [$(service)],)$(NC)"
	@$(COMPOSE) build $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Build complete$(NC)"

rebuild: validate-service
	@echo -e "$(BLUE)🔨 Rebuilding (no-cache): $(STACK)$(if $(service), [$(service)],)$(NC)"
	@$(COMPOSE) build --no-cache $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Rebuild complete$(NC)"

re: build restart

rere: rebuild restart

# ======================================================================================
# MONITORING
# ======================================================================================

logs: validate-service
	@$(COMPOSE) logs -f --tail=100 $(SERVICE_FLAG)

ps status: validate-service
	@if [ -n "$(service)" ]; then \
		$(COMPOSE) ps $(service); \
	else \
		echo -e "$(CYAN)📊 System Status Report:$(NC)"; \
		$(COMPOSE) ps -a; \
	fi

shell: validate-service
	@if [ -z "$(service)" ]; then \
		echo -e "$(RED)✖ Usage: make shell STACK=$(STACK) service=<name>$(NC)"; \
		echo -e "$(YELLOW)Available services:$(NC)"; \
		$(COMPOSE) config --services | sed 's/^/  - /'; \
		exit 1; \
	fi
	@$(COMPOSE) exec $(service) sh

exec: validate-service
	@if [ -z "$(service)" ] || [ -z "$(cmd)" ]; then \
		echo -e "$(RED)✖ Usage: make exec STACK=$(STACK) service=<name> cmd=\"<command>\"$(NC)"; \
		exit 1; \
	fi
	@$(COMPOSE) exec $(service) $(cmd)

health: validate-stack
	@echo -e "$(CYAN)🏥 Health Check:$(NC)"
	@$(COMPOSE) ps --format json | jq -r '.[] | "\(.Service): \(.State) - \(.Health)"'

# ======================================================================================
# CLEANUP
# ======================================================================================

clean: validate-stack
	@echo -e "$(YELLOW)🧹 Cleaning stack: $(STACK)$(NC)"
	@$(COMPOSE) down --remove-orphans
	@echo -e "$(GREEN)✅ Clean complete$(NC)"

fclean: validate-stack
	@echo -e "$(RED)🧹 Full clean (including volumes): $(STACK)$(NC)"
	@$(COMPOSE) down --volumes --remove-orphans
	@echo -e "$(GREEN)✅ Full clean complete$(NC)"

prune: fclean
	@echo -e "$(RED)🧹 System prune (WARNING: affects all Docker resources)$(NC)"
	@read -p "Continue? [y/N] " -n 1 -r; echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker system prune -af --volumes; \
		echo -e "$(GREEN)✅ System pruned$(NC)"; \
	else \
		echo -e "$(GRAY)Cancelled$(NC)"; \
	fi

# ======================================================================================
# STACK DASHBOARD
# ======================================================================================

list-stacks:
	@echo -e "\n$(PURPLE)╔══════════════════════════════════════════════════════════════════════════════╗$(NC)"; \
	echo -e "$(PURPLE)║$(NC)                    $(BOLD)$(CYAN)🧩 Docker Stack Status Dashboard$(NC)                    $(PURPLE)║$(NC)"; \
	echo -e "$(PURPLE)╚══════════════════════════════════════════════════════════════════════════════╝$(NC)\n"; \
	total_stacks=0; total_running=0; total_unhealthy=0; total_offline=0; \
	for f in $(COMPOSE_DIR)/docker-compose*.yml; do \
		stack_name="<unknown>"; \
		if [[ "$$f" == "$(COMPOSE_DIR)/docker-compose.yml" ]]; then stack_name="full"; \
		else stack_name=$$(basename "$$f" .yml | sed 's/docker-compose\.//'); fi; \
		project_name="$(PROJECT_NAME)-$$stack_name"; \
		running_cnt=$$(docker ps -q --filter "status=running" --filter "label=com.docker.compose.project=$$project_name" 2>/dev/null | wc -l); \
		total_cnt=$$(docker ps -a -q --filter "label=com.docker.compose.project=$$project_name" 2>/dev/null | wc -l); \
		unhealthy_cnt=$$(docker ps -q --filter "health=unhealthy" --filter "label=com.docker.compose.project=$$project_name" 2>/dev/null | wc -l); \
		total_stacks=$$((total_stacks + 1)); \
		if [ "$$running_cnt" -gt 0 ]; then \
			uptime=$$(docker ps --filter "status=running" --filter "label=com.docker.compose.project=$$project_name" --format "{{.Status}}" | head -n 1 | sed 's/Up //; s/ ago//; s/ ([^)]*)//'); \
			if [ "$$unhealthy_cnt" -gt 0 ]; then \
				total_unhealthy=$$((total_unhealthy + 1)); \
				printf "$(RED)● %-18s$(NC) $(RED)%-11s$(NC) [%2d/%2d running]  ⏱  %s\n" "$$stack_name" "UNHEALTHY" "$$running_cnt" "$$total_cnt" "$$uptime"; \
			elif [ "$$running_cnt" -eq "$$total_cnt" ]; then \
				total_running=$$((total_running + 1)); \
				printf "$(GREEN)● %-18s$(NC) $(GREEN)%-11s$(NC) [%2d/%2d running]  ⏱  %s\n" "$$stack_name" "OPERATIONAL" "$$running_cnt" "$$total_cnt" "$$uptime"; \
			else \
				printf "$(YELLOW)● %-18s$(NC) $(YELLOW)%-11s$(NC) [%2d/%2d running]  ⏱  %s\n" "$$stack_name" "DEGRADED" "$$running_cnt" "$$total_cnt" "$$uptime"; \
			fi; \
			services_list=$$(docker ps --filter "label=com.docker.compose.project=$$project_name" --format "{{.Names}}" 2>/dev/null | sort); \
			service_count=$$(echo "$$services_list" | wc -l); \
			current_service=0; \
			echo "$$services_list" | while IFS= read -r service_name; do \
				current_service=$$((current_service + 1)); \
				prefix="├──"; [ "$$current_service" -eq "$$service_count" ] && prefix="└──"; \
				status=$$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$$service_name" 2>/dev/null || echo "error"); \
				status_color="$(GRAY)"; dot="$(GRAY)○$(NC)"; label="UNKNOWN"; \
				if [[ "$$status" == "healthy" ]]; then status_color="$(GREEN)"; dot="$(GREEN)●$(NC)"; label="HEALTHY"; \
				elif [[ "$$status" == "unhealthy" ]]; then status_color="$(RED)"; dot="$(RED)●$(NC)"; label="UNHEALTHY"; \
				elif [[ "$$status" == "running" ]]; then status_color="$(YELLOW)"; dot="$(YELLOW)●$(NC)"; label="RUNNING"; \
				elif [[ "$$status" == "exited" ]]; then status_color="$(RED)"; dot="$(RED)●$(NC)"; label="EXITED"; fi; \
				service_name_clean=$$(echo "$$service_name" | sed "s/$$project_name-//; s/-[0-9]*$$//"); \
				printf "     %s %-25s %b%-10s$(NC) %b\n" "$$prefix" "$$service_name_clean" "$$status_color" "$$label" "$$dot"; \
			done; \
			echo ""; \
		else \
			if [ "$$total_cnt" -gt 0 ]; then \
				total_offline=$$((total_offline + 1)); \
				printf "$(RED)● %-18s$(NC) $(RED)%-11s$(NC) [%2d/%2d stopped]\n\n" "$$stack_name" "STOPPED" "$$running_cnt" "$$total_cnt"; \
			else \
				printf "$(GRAY)○ %-18s$(NC) $(GRAY)%-11s$(NC) [no containers]\n\n" "$$stack_name" "OFFLINE"; \
			fi; \
		fi; \
	done; \
	echo -e "$(PURPLE)──────────────────────────────────────────────────────────────────────────────$(NC)"; \
	echo -e " $(BOLD)Summary:$(NC)  $(GREEN)✔ $$total_running running$(NC),  $(RED)✖ $$total_unhealthy unhealthy$(NC),  $(GRAY)○ $$total_offline offline$(NC),  total: $$total_stacks"; \
	echo -e "$(PURPLE)──────────────────────────────────────────────────────────────────────────────$(NC)\n"; \
	echo -e " Legend:  $(GREEN)●$(GRAY)=Healthy  $(YELLOW)●$(GRAY)=Degraded  $(RED)●$(GRAY)=Unhealthy  $(GRAY)○$(GRAY)=Offline$(NC)\n"

# ======================================================================================
# HELP
# ======================================================================================

help:
	@echo -e "$(BLUE)========================================================================="
	@echo -e " Makefile - The Master Control Program"
	@echo -e "=========================================================================$(NC)"
	@echo -e "$(CYAN)\"The distance between thought and action, minimized.\"$(NC)"
	@echo ""
	@echo -e "$(YELLOW)Usage: make [target] STACK=<name> [service=<name>]$(NC)"
	@echo ""
	@echo -e "$(GREEN)Core Operations:$(NC)"
	@echo -e "  up                   - Start stack (all services or specific service=)"
	@echo -e "  down                 - Stop and remove stack"
	@echo -e "  restart              - Restart stack or service"
	@echo -e "  stop/start           - Stop/start without removing"
	@echo -e "  build                - Build images (cached)"
	@echo -e "  rebuild              - Build images (no-cache)"
	@echo -e "  re/rere              - Build and restart (cached/no-cache)"
	@echo ""
	@echo -e "$(GREEN)Monitoring:$(NC)"
	@echo -e "  logs                 - Follow logs (all or service=)"
	@echo -e "  ps/status            - Show container status"
	@echo -e "  list-stacks          - Dashboard of all stacks"
	@echo -e "  health               - Health check report"
	@echo -e "  ping                 - Quick HTTP health on every service (via nginx)"
	@echo -e "  errors               - Last ERROR/Exception lines across the stack"
	@echo -e "  stats                - docker stats scoped to this stack"
	@echo ""
	@echo -e "$(GREEN)Utilities:$(NC)"
	@echo -e "  shell service=<name> - Interactive shell in container"
	@echo -e "  exec service=<name> cmd=\"<cmd>\" - Execute command"
	@echo -e "  audit/todo/versions  - Repo info at a glance"
	@echo -e "  check-deps/env-diff  - Tooling + env file sanity"
	@echo -e "  reboot               - down + up"
	@echo ""
	@echo -e "$(GREEN)SDK + TUI (DSS-specific QOL — at the bottom of this file):$(NC)"
	@echo -e "  tui                  - Launch the DeepSearchStack TUI"
	@echo -e "  tui-test             - Headless TUI smoke test"
	@echo -e "  tui-screenshot       - Save TUI screenshot to svg"
	@echo -e "  sdk-test             - Full SDK test suite (17 tests)"
	@echo -e "  sdk-test-unit        - SDK unit tests only (no stack required)"
	@echo -e "  sdk-install          - pip install SDK + TUI deps"
	@echo -e "  sdk-repl             - Drop into a Python REPL with the SDK loaded"
	@echo -e "  curl-catalog         - List 18 models in the inference catalog"
	@echo -e "  curl-warehouse       - GET /dss/warehouse/stats"
	@echo -e "  curl-llm             - One-shot LLM call (default model)"
	@echo -e "  db-shell/db-stats/db-backup  - PostgreSQL shortcuts"
	@echo -e "  redis-cli            - redis CLI"
	@echo -e "  reset-{vectors,warehouse,cache,hashes}  - Wipe individual stores (no volume loss)"
	@echo -e "  shell-web/shell-llm/shell-db/...   - Per-service shell aliases (no service= typing)"
	@echo -e "  logs-web/logs-llm/logs-agent/...   - Per-service log aliases"
	@echo -e "  e2e                  - sdk-test + tui-test (full E2E)"
	@echo -e "  snapshot             - tui-screenshot + versions (for bug reports)"
	@echo ""
	@echo -e "$(GREEN)Cleanup:$(NC)"
	@echo -e "  clean                - Stop and remove containers"
	@echo -e "  fclean               - Clean + remove volumes"
	@echo -e "  prune                - Full system prune (interactive)"
	@echo ""
	@echo -e "$(YELLOW)Examples:$(NC)"
	@echo -e "  make up STACK=full"
	@echo -e "  make logs STACK=full service=deepsearch"
	@echo -e "  make restart STACK=full service=search-agent"
	@echo -e "  make shell STACK=full service=inference-gateway"
	@echo -e "  make tui                      # launch the TUI"
	@echo -e "  make ping                     # health check all services"
	@echo -e "  make errors                   # find recent errors in logs"
	@echo -e "  make reset-vectors            # wipe the vector store, keep volumes"
	@echo ""
	@echo -e "$(GRAY)All operations support STACK= and service= parameters$(NC)"
	@echo -e "$(BLUE)=========================================================================$(NC)"

# ======================================================================================
# DSS-SPECIFIC SHORTCUTS
# ======================================================================================

full:
	@$(MAKE) up STACK=full

full-down:
	@$(MAKE) down STACK=full

full-restart:
	@$(MAKE) restart STACK=full

light:
	@$(MAKE) up STACK=light

light-down:
	@$(MAKE) down STACK=light

light-restart:
	@$(MAKE) restart STACK=light

test:
	@$(MAKE) up STACK=test

test-down:
	@$(MAKE) down STACK=test

test-restart:
	@$(MAKE) restart STACK=test

# ======================================================================================
# REPO-SPECIFIC QOL  (DSS-only — keep above repo-agnostic)
# ======================================================================================
# Each rule below assumes a DSS context (services known, ports known,
# SDK at sdk/python, audit doc at docs/audit/viability-2026-06-05.md).
# If you copy this Makefile to a new project, these become dead code
# and you can drop them.
# ======================================================================================

# --- SDK + TUI ----------------------------------------------------------

SDK_DIR     := sdk/python
TUI_DIR     := $(SDK_DIR)/tui
AUDIT_DOC   := docs/audit/viability-2026-06-05.md
TODO_DOC    := docs/TODO.md

tui:
	@if ! $(COMPOSE) ps --status running 2>/dev/null | grep -q web-api; then \
		echo -e "$(RED)✖ web-api is not running. Run: make up STACK=full$(NC)"; \
		exit 1; \
	fi
	@cd $(TUI_DIR) && python3 app.py $(TUI_FLAGS)

tui-test:
	@echo -e "$(BLUE)🧪 Running TUI smoke test (needs stack up)$(NC)"
	@python3 $(TUI_DIR)/test_app.py

tui-screenshot:
	@echo -e "$(BLUE)📸 Capturing TUI screenshot (headless)$(NC)"
	@python3 -c "import asyncio, sys; sys.path.insert(0, '$(TUI_DIR)'); \
		from app import DeepSearchTUI; \
		async def m(): \
			from pathlib import Path; \
			t = DeepSearchTUI(); \
			async with t.run_test() as p: await p.pause(); \
			Path('$(TUI_DIR)/screenshot.svg').write_text(t.export_screenshot(title='DeepSearchStack TUI')); \
			print('saved $(TUI_DIR)/screenshot.svg'); \
		asyncio.run(m())"

sdk-install:
	@echo -e "$(BLUE)📦 Installing SDK + TUI dependencies$(NC)"
	@pip install --quiet --break-system-packages -r $(SDK_DIR)/requirements.txt 2>/dev/null \
		|| pip install --quiet -r $(SDK_DIR)/requirements.txt
	@echo -e "$(GREEN)✅ SDK ready at $(SDK_DIR)$(NC)"

sdk-test:
	@echo -e "$(BLUE)🧪 Running SDK unit + integration tests$(NC)"
	@python3 $(SDK_DIR)/tests/test_deepsearch.py

sdk-test-unit:
	@echo -e "$(BLUE)🧪 Running SDK unit tests only (no stack required)$(NC)"
	@python3 $(SDK_DIR)/tests/test_deepsearch.py --unit

sdk-repl:
	@cd $(SDK_DIR) && python3 -c "from deepsearch import DeepSearchClient; \
		print('SDK ready. Use: c = DeepSearchClient(); c.<TAB>'); \
		import code; code.interact(local=globals())"

# --- Stack info / quick health -----------------------------------------

ping:                                            # quick health check on every port
	@echo -e "$(CYAN)🏓 Pinging all services (via nginx + direct)$(NC)"; \
	ok=0; fail=0; \
	for url in \
		"http://localhost:8083/health                 web-api" \
		"http://localhost:8083/dss/gateway/health     search-gateway" \
		"http://localhost:8083/dss/agent/health       search-agent" \
		"http://localhost:8083/dss/vectors/health     vector-store" \
		"http://localhost:8005/health                 inference-gateway" \
		"http://localhost:8083/dss/warehouse/health   knowledge-warehouse" \
		"http://localhost:8083/dss/crawl/health       crawler" \
		"http://localhost:8080/health                 proxy-rotator" \
	; do \
		u=$$(echo $$url | awk '{print $$1}'); \
		n=$$(echo $$url | awk '{print $$2}'); \
		if curl -sS -m 2 -o /dev/null -w '%{http_code}' $$u | grep -qE '^(2|3)'; then \
			printf "  $(GREEN)●$(NC) %-22s %s\n" $$n $$u; ok=$$((ok+1)); \
		else \
			printf "  $(RED)●$(NC) %-22s %s\n" $$n $$u; fail=$$((fail+1)); \
		fi; \
	done; \
	echo -e "  $(GREEN)$$ok up$(NC), $(RED)$$fail down$(NC)"

audit:
	@if [ -f $(AUDIT_DOC) ]; then \
		echo -e "$(CYAN)📋 Latest audit: $(AUDIT_DOC)$(NC)"; \
		grep -E '^##|CRITICAL|HIGH|MEDIUM|LOW' $(AUDIT_DOC) | head -30; \
	else \
		echo -e "$(YELLOW)No audit doc at $(AUDIT_DOC)$(NC)"; \
	fi

todo:
	@if [ -f $(TODO_DOC) ]; then \
		echo -e "$(CYAN)📋 TODO headlines:$(NC)"; \
		grep -E '^#|^- \[' $(TODO_DOC) | head -20; \
	else \
		echo -e "$(YELLOW)No TODO doc at $(TODO_DOC)$(NC)"; \
	fi

versions:
	@echo -e "$(CYAN)🔖 Versions$(NC)"; \
	echo "  docker:  $$(docker --version 2>/dev/null | sed -E 's/^Docker version ([^,]+).*/\1/')"; \
	echo "  compose: $$(docker compose version --short 2>/dev/null || docker compose version 2>/dev/null | awk '{print $$NF}')"; \
	echo "  python:  $$(python3 --version 2>&1 | awk '{print $$2}')"; \
	if $(COMPOSE) ps web-api 2>/dev/null | grep -q web-api; then \
		$(COMPOSE) ps --format '  {{.Service}}: {{.Image}}' 2>/dev/null; \
	else \
		echo "  (stack not running)"; \
	fi

env-diff:
	@if [ -f infra/env/.dev.env ] && [ -f .env.example ]; then \
		diff -u infra/env/.dev.env .env.example | head -50 || true; \
	else \
		echo -e "$(YELLOW)Missing one of: infra/env/.dev.env or .env.example$(NC)"; \
	fi

check-deps:                                     # verify required CLI tools exist
	@echo -e "$(CYAN)🔧 Checking required tools$(NC)"; \
	for tool in docker curl jq python3 pip3; do \
		if command -v $$tool >/dev/null 2>&1; then \
			printf "  $(GREEN)✔$(NC) %s\n" $$tool; \
		else \
			printf "  $(RED)✖$(NC) %s (missing)\n" $$tool; \
		fi; \
	done

# --- Per-service shortcuts (no STACK/service= typing) -------------------

shell-web:    service=web-api          ; $(MAKE) --no-print-directory shell service=web-api
shell-search: service=search-gateway   ; $(MAKE) --no-print-directory shell service=search-gateway
shell-agent:  service=search-agent     ; $(MAKE) --no-print-directory shell service=search-agent
shell-llm:    service=inference-gateway ; $(MAKE) --no-print-directory shell service=inference-gateway
shell-vec:    service=vector-store     ; $(MAKE) --no-print-directory shell service=vector-store
shell-wh:     service=knowledge-warehouse ; $(MAKE) --no-print-directory shell service=knowledge-warehouse
shell-crawl:  service=crawler          ; $(MAKE) --no-print-directory shell service=crawler
shell-db:     service=postgres         ; $(MAKE) --no-print-directory shell service=postgres
shell-redis:  service=redis            ; $(MAKE) --no-print-directory shell service=redis

logs-web:    service=web-api           ; $(MAKE) --no-print-directory logs service=web-api
logs-search: service=search-gateway    ; $(MAKE) --no-print-directory logs service=search-gateway
logs-agent:  service=search-agent      ; $(MAKE) --no-print-directory logs service=search-agent
logs-llm:    service=inference-gateway ; $(MAKE) --no-print-directory logs service=inference-gateway
logs-vec:    service=vector-store      ; $(MAKE) --no-print-directory logs service=vector-store
logs-wh:     service=knowledge-warehouse ; $(MAKE) --no-print-directory logs service=knowledge-warehouse
logs-crawl:  service=crawler           ; $(MAKE) --no-print-directory logs service=crawler
logs-db:     service=postgres          ; $(MAKE) --no-print-directory logs service=postgres

restart-web:    service=web-api          ; $(MAKE) --no-print-directory restart service=web-api
restart-search: service=search-gateway   ; $(MAKE) --no-print-directory restart service=search-gateway
restart-agent:  service=search-agent     ; $(MAKE) --no-print-directory restart service=search-agent
restart-llm:    service=inference-gateway ; $(MAKE) --no-print-directory restart service=inference-gateway

.PHONY: shell-web shell-search shell-agent shell-llm shell-vec shell-wh shell-crawl shell-db shell-redis
.PHONY: logs-web logs-search logs-agent logs-llm logs-vec logs-wh logs-crawl logs-db
.PHONY: restart-web restart-search restart-agent restart-llm
.PHONY: tui tui-test tui-screenshot sdk-install sdk-test sdk-test-unit sdk-repl
.PHONY: ping audit todo versions env-diff check-deps

# --- Quick API curls (most common debug) -------------------------------

curl-catalog:
	@curl -sS http://localhost:8083/dss/api/providers | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d[\"models\"])} models'); [print(f'  {m[\"id\"]:35} {m[\"provider\"]}') for m in d['models']]"

curl-warehouse:
	@curl -sS 'http://localhost:8083/dss/warehouse/stats' | python3 -m json.tool

curl-warehouse-search:
	@curl -sS 'http://localhost:8083/dss/warehouse/search?q=python&limit=5' | python3 -m json.tool

curl-search-providers:
	@curl -sS 'http://localhost:8083/dss/gateway/providers/registered' | python3 -m json.tool

curl-llm:
	@curl -sS -X POST http://localhost:8005/v1/chat/completions \
		-H 'Content-Type: application/json' \
		-d '{"model":"virtual/free-coder","messages":[{"role":"user","content":"Reply: OK"}],"stream":false}' \
		| python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('content') or d.get('raw_response',{}).get('choices',[{}])[0].get('message',{}).get('content',''))"

curl-vector:
	@curl -sS -X POST http://localhost:8083/dss/vectors/query \
		-H 'Content-Type: application/json' \
		-d '{"namespace":"default","query":"test","top_k":3}' | python3 -m json.tool

.PHONY: curl-catalog curl-warehouse curl-warehouse-search curl-search-providers curl-llm curl-vector

# --- Database / volume shortcuts ---------------------------------------

db-shell:                                       # psql into the warehouse DB
	@$(COMPOSE) exec postgres psql -U dss_user -d warehouse

db-stats:
	@$(COMPOSE) exec postgres psql -U dss_user -d warehouse -c "\
		SELECT 'warehouse' AS db, COUNT(*) AS rows FROM pages \
		UNION ALL SELECT 'warehouse_fts', COUNT(*) FROM pages_fts;"

db-backup:                                      # dump warehouse + vectors DB
	@mkdir -p backups
	@$(COMPOSE) exec -T postgres pg_dump -U dss_user warehouse > backups/warehouse-$$(date +%F-%H%M).sql
	@echo -e "$(GREEN)✅ backups/warehouse-$$(date +%F-%H%M).sql$(NC)"

redis-cli:                                      # redis CLI in the redis container
	@$(COMPOSE) exec redis redis-cli

.PHONY: db-shell db-stats db-backup redis-cli

# --- Reset / wipe individual data stores (no volume unmount) ----------

reset-vectors:                                  # wipe the vector store
	@$(COMPOSE) exec vector-store sh -c 'rm -f /app/data/documents/* /app/data/index/* /app/data/chroma.sqlite3' 2>/dev/null || true
	@$(COMPOSE) restart vector-store
	@echo -e "$(GREEN)✅ vector store reset$(NC)"

reset-warehouse:                                # truncate warehouse tables
	@$(COMPOSE) exec postgres psql -U dss_user -d warehouse -c "TRUNCATE pages, pages_fts;"
	@echo -e "$(GREEN)✅ warehouse truncated$(NC)"

reset-cache:                                    # wipe crawler cache
	@$(COMPOSE) exec crawler sh -c 'rm -rf /app/cache/*' 2>/dev/null || true
	@echo -e "$(GREEN)✅ crawler cache wiped$(NC)"

reset-hashes:                                   # clear web-api seen-hashes (forces re-embed)
	@$(COMPOSE) exec web-api sh -c 'rm -f /app/data/hashes.json /app/data/hashes.json.bak' 2>/dev/null || true
	@$(COMPOSE) restart web-api
	@echo -e "$(GREEN)✅ web-api hashes cleared$(NC)"

.PHONY: reset-vectors reset-warehouse reset-cache reset-hashes

# --- Stack maintenance -------------------------------------------------

reboot:                                         # full restart: down, up
	@$(MAKE) --no-print-directory down
	@$(MAKE) --no-print-directory up

stats:                                          # docker stats scoped to this stack
	@docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" \
		$(shell docker ps --filter "label=com.docker.compose.project=$(COMPOSE_PROJECT)" --format '{{.Names}}' 2>/dev/null) 2>/dev/null \
		|| docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}"

clear-logs:                                     # truncate log files of running services
	@echo -e "$(YELLOW)🧹 Truncating logs of running services$(NC)"; \
	for s in $$($(COMPOSE) ps --services 2>/dev/null); do \
		$(COMPOSE) exec -T $$s sh -c 'truncate -s 0 /proc/1/fd/1 2>/dev/null; true' >/dev/null 2>&1 || true; \
	done; \
	echo -e "$(GRAY)  (container logs go to json driver; use 'make logs-clear' to drop journal)$(NC)"

errors:                                         # last 50 ERROR/Exception lines across the stack
	@services=$$($(COMPOSE) ps --services 2>/dev/null || true); \
	if [ -z "$$services" ]; then echo -e "$(GRAY)  (stack not running)$(NC)"; exit 0; fi; \
	for s in $$services; do \
		hits=$$($(COMPOSE) logs --no-color --tail=200 $$s 2>/dev/null | grep -E -i 'error|exception|traceback|failed' | tail -5 || true); \
		if [ -n "$$hits" ]; then \
			echo -e "  $(RED)● $$s$(NC)"; \
			echo "$$hits" | sed 's/^/    /'; \
		fi; \
	done; \
	echo -e "$(GRAY)  (only services with hits shown)$(NC)"; \
	true

git-status:                                     # short git status of the working tree
	@git -C $(CURDIR) status --short
	@echo "---"
	@git -C $(CURDIR) log --oneline -5

.PHONY: reboot stats clear-logs errors git-status

# --- Misc dev workflows -----------------------------------------------

e2e: sdk-test tui-test                         # full E2E: SDK + TUI against live stack
	@echo -e "$(GREEN)✅ E2E suite passed$(NC)"

persistence-test:                               # verify data survives down + up
	@echo -e "$(BLUE)💾 Running persistence E2E test$(NC)"
	@bash tests/persistence/test_e2e_persistence.sh

snapshot:                                       # capture TUI screenshot + version info
	@$(MAKE) --no-print-directory tui-screenshot
	@$(MAKE) --no-print-directory versions | tee $(TUI_DIR)/snapshot.txt
	@echo -e "$(GREEN)✅ snapshot saved$(NC)"

.PHONY: e2e persistence-test snapshot
