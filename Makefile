# ======================================================================================
# DeepSearchStack Makefile - Definitive Version 10.0 (Restored Glory)
# ======================================================================================

# --- Cosmetics ---
RED     := \033[0;31m
GREEN   := \033[0;32m
YELLOW  := \033[1;33m
BLUE    := \033[0;34m
NC      := \033[0m

# --- Configuration ---
SHELL := /bin/bash
COMPOSE_FILE ?= infra/docker-compose.yml
COMPOSE := docker compose -p deepsearch -f $(COMPOSE_FILE)

.DEFAULT_GOAL := help

# --- Phony Targets ---
.PHONY: help up down logs ps build no-cache restart re config status clean fclean prune stop ssh ollama-pull

# ======================================================================================
# HELP & USAGE
# ======================================================================================
help:
	@echo -e "$(BLUE)========================================================================="
	@echo -e " DeepSearchStack - Master Control Program"
	@echo -e "=========================================================================$(NC)"
	@echo -e "$(YELLOW)Usage: make [target] [service=SERVICE_NAME] [args=\"ARGS\"] [model=MODEL_NAME]$(NC)"
	@echo ""
	@echo -e "$(GREEN)Core Stack Management:$(NC)"
	@echo -e "  up                  - Start all services in detached mode."
	@echo -e "  down                - Stop and remove all services and networks."
	@echo -e "  restart             - Restart all services (down + up)."
	@echo -e "  re                  - Rebuild images (cached) and restart all services."
	@echo -e "  rere                - Rebuild images (no-cache) and restart all services."
	@echo ""
	@echo -e "$(GREEN)Model Management (Ollama):$(NC)"
	@echo -e "  ollama-pull model=<name> - Pulls a new model into the running Ollama service."
	@echo ""
	@echo -e "$(GREEN)Information & Debugging:$(NC)"
	@echo -e "  status [service=<name>] - Show status of services (Alias: ps)."
	@echo -e "  logs [service=<name>]   - Follow logs (all or specific service)."
	@echo -e "  ssh service=<name>    - Get an interactive shell into a running service."
	@echo -e "  exec svc=<name> args=\"<cmd>\" - Execute a command in a running service."
	@echo ""
	@echo -e "$(GREEN)Cleaning & Pruning:$(NC)"
	@echo -e "  fclean              - Stop and remove all services, volumes, and networks."
	@echo -e "  prune               - Ultimate clean: fclean + prune entire Docker system."
	@echo ""
	@echo -e "$(YELLOW)Execution Order:$(NC)"
	@echo -e "  1. make up                       # Start stack. Default models are pulled on first run."
	@echo -e "  2. make ollama-pull model=phi3   # Pull additional models to the running service."
	@echo -e "$(BLUE)========================================================================="

# ======================================================================================
# CORE STACK MANAGEMENT
# ======================================================================================
up:
	@echo -e "$(GREEN)Igniting Deep Search Agent Stack...$(NC)"
	@$(COMPOSE) up -d --remove-orphans
	@echo -e "$(GREEN)Services are now running in detached mode.$(NC)"

down:
	@echo -e "$(RED)Shutting down DeepSearchStack...$(NC)"
	@$(COMPOSE) down --remove-orphans

restart: down up
re: down build up logs
rere: down no-cache up logs

# ======================================================================================
# MODEL MANAGEMENT
# ======================================================================================
ollama-pull:
	@if [ -z "$(model)" ]; then \
		echo -e "$(RED)Error: Model name required. Usage: make ollama-pull model=<name>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(BLUE)Executing pull command in 'ollama-1' for model: $(model)...$(NC)"
	@$(COMPOSE) exec ollama-1 ollama pull $(model)
	@echo -e "$(GREEN)Pull command finished.$(NC)"

# ======================================================================================
# BUILDING IMAGES
# ======================================================================================
build:
	@echo -e "$(BLUE)Forging components... Building images for $(or $(service),all services)...$(NC)"
	@$(COMPOSE) build $(service)

no-cache:
	@echo -e "$(YELLOW)Force-forging (no cache)... Building for $(or $(service),all services)...$(NC)"
	@$(COMPOSE) build --no-cache $(service)

# ======================================================================================
# INFORMATION & DEBUGGING
# ======================================================================================
status:
	@echo -e "$(BLUE)System Status Report:$(NC)"
	@$(COMPOSE) ps $(service)
ps: status

logs:
	@echo -e "$(BLUE)Tapping into data stream for $(or $(service),all services)...$(NC)"
	@$(COMPOSE) logs -f --tail="100" $(service)

ssh:
	@if [ -z "$(service)" ]; then \
		echo -e "$(RED)Error: Service name required. Usage: make ssh service=<service_name>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(GREEN)Establishing connection to $(service)...$(NC)"
	@$(COMPOSE) exec $(service) /bin/sh || $(COMPOSE) exec $(service) /bin/bash

exec:
	@if [ -z "$(svc)" ] || [ -z "$(args)" ]; then \
		echo -e "$(RED)Error: Service and command required. Usage: make exec svc=<name> args=\"<cmd>\"$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(GREEN)Executing remote directive in $(svc): $(args)...$(NC)"
	@$(COMPOSE) exec $(svc) $(args)

# ======================================================================================
# CLEANING & PRUNING
# ======================================================================================
fclean:
	@echo -e "$(RED)Deep cleaning containers, networks, and volumes...$(NC)"
	@$(COMPOSE) down --volumes --remove-orphans

prune: fclean
	@echo -e "$(RED)Executing ultimate prune sequence...$(NC)"
	@docker system prune -af --volumes
	@docker builder prune -af
	@echo -e "$(GREEN)Full system prune complete.$(NC)"
