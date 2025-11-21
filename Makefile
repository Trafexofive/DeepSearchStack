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
PROJECT_NAME ?= deepsearch

STACK ?= core
COMPOSE_DIR := infra
NETWORK_NAME := deepsearch-net

# Auto-detect compose file
ifeq ($(STACK),full)
    COMPOSE_FILE := $(COMPOSE_DIR)/docker-compose.yml
else ifeq ($(STACK),gemini)
    COMPOSE_FILE := $(COMPOSE_DIR)/docker-compose.gemini.yml
else
    COMPOSE_FILE := $(COMPOSE_DIR)/docker-compose.$(STACK).yml
endif

COMPOSE_PROJECT := $(PROJECT_NAME)-$(STACK)
COMPOSE := docker compose -f $(COMPOSE_FILE) --env-file $(ENV_FILE) -p $(COMPOSE_PROJECT)

# Service parameter (optional, applies to single service)
service ?=
SERVICE_FLAG := $(if $(service),$(service),)

.DEFAULT_GOAL := help
.PHONY: help validate-stack validate-service env-check setup up down restart stop logs ps status build rebuild clean fclean prune shell exec health list-stacks create-networks bench bench-load bench-stress bench-all

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
	@$(COMPOSE) down --remove-orphans
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
# BENCHMARKING
# ======================================================================================
bench:
	@echo -e "$(CYAN)========================================================="
	@echo -e "     DeepSearchStack - Realistic Business Intelligence Benchmark"
	@echo -e "=========================================================$(NC)"
	@echo -e "$(YELLOW)This benchmark simulates a complete business intelligence workflow:$(NC)"
	@echo -e "$(YELLOW)Goal → Ingest → Aggregate → Transform → Report → Validate$(NC)"
	@echo ""
	@echo -e "$(GREEN)Running realistic business intelligence pipeline...$(NC)"
	python benchmarks/realistic/business_intelligence_bench.py

bench-load:
	@echo -e "$(CYAN)========================================================="
	@echo -e "     DeepSearchStack - Load Benchmark Suite"
	@echo -e "=========================================================$(NC)"
	@echo -e "$(YELLOW)Running concurrent load tests...$(NC)"
	@echo -e "$(GREEN)Load benchmark not implemented yet - create benchmarks/load/concurrent_load_test.py$(NC)"

bench-stress:
	@echo -e "$(CYAN)========================================================="
	@echo -e "     DeepSearchStack - Stress Benchmark Suite" 
	@echo -e "=========================================================$(NC)"
	@echo -e "$(YELLOW)Running stress tests...$(NC)"
	@echo -e "$(GREEN)Stress benchmark not implemented yet - create benchmarks/stress/stress_test.py$(NC)"

bench-all: bench bench-load bench-stress
	@echo -e "$(GREEN)✅ All benchmark suites completed!$(NC)"

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
	@echo ""
	@echo -e "$(GREEN)Testing:$(NC)"
	@echo -e "  bench                - Run realistic business intelligence benchmark"
	@echo -e "  bench-load           - Run load tests (not implemented)"
	@echo -e "  bench-stress         - Run stress tests (not implemented)"
	@echo -e "  bench-all            - Run all benchmark suites"
	@echo ""
	@echo -e "$(GREEN)Utilities:$(NC)"
	@echo -e "  shell service=<name> - Interactive shell in container"
	@echo -e "  exec service=<name> cmd=\"<cmd>\" - Execute command"
	@echo ""
	@echo -e "$(GREEN)Cleanup:$(NC)"
	@echo -e "  clean                - Stop and remove containers"
	@echo -e "  fclean               - Clean + remove volumes"
	@echo -e "  prune                - Full system prune (interactive)"
	@echo ""
	@echo -e "$(YELLOW)Examples:$(NC)"
	@echo -e "  make up STACK=gemini"
	@echo -e "  make logs STACK=gemini service=deepsearch"
	@echo -e "  make restart STACK=gemini service=llm-gateway"
	@echo -e "  make down STACK=gemini"
	@echo ""
	@echo -e "$(GRAY)All operations support STACK= and service= parameters$(NC)"
	@echo -e "$(BLUE)=========================================================================$(NC)"

# ======================================================================================
# STACK-SPECIFIC SHORTCUTS
# ======================================================================================

gemini:
	@$(MAKE) up STACK=gemini

gemini-down:
	@$(MAKE) down STACK=gemini

gemini-restart:
	@$(MAKE) restart STACK=gemini