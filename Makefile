# ======================================================================================
# Makefile v2 - The Master Control Program
# ======================================================================================
# "The distance between thought and action, minimized."

# --- Configuration (Overridable via .env or command line) ---
-include .env

# Core config
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

PROJECT_NAME ?= substrate
COMPOSE_BASE_NAME ?= docker-compose
COMPOSE_FILE_PATTERN ?= $(COMPOSE_BASE_NAME)*.yml
COMPOSE_SEARCH_DIRS ?= infra services
COMPOSE_SEARCH_DEPTH ?= 3

PRODUCTION_STACKS ?= core humanizer yt-lab
BACKUP_DIR ?= backups
EXPORT_DIR ?= exports
LOG_TAIL ?= 100
VERBOSE ?= 0

# Cache file for last-used stack
CACHE_FILE := .make.cache

# --- Color Codes ---
RED     := \033[0;31m
GREEN   := \033[0;32m
YELLOW  := \033[1;33m
BLUE    := \033[0;34m
PURPLE  := \033[0;35m
CYAN    := \033[0;36m
GRAY    := \033[0;90m
BOLD    := \033[1m
NC      := \033[0m
DIM     := \033[2m
RESET   := $(NC)

# ======================================================================================
# PATH PARSING LOGIC
# ======================================================================================

# Get all command line goals
_ALL_GOALS := $(MAKECMDGOALS)

# The first goal is the target
_TARGET := $(firstword $(_ALL_GOALS))

# Everything else is the STACK_PATH - don't filter anything
# The second word onwards is what we want
STACK_PATH := $(strip $(wordlist 2,$(words $(_ALL_GOALS)),$(_ALL_GOALS)))

# Parse STACK_PATH into components
ifneq ($(STACK_PATH),)
    # Check if it contains a slash
    ifneq ($(findstring /,$(STACK_PATH)),)
        # Split on '/' - first part is always STACK (or VOL1 for vol-diff)
        override STACK := $(firstword $(subst /, ,$(STACK_PATH)))
        
        # Second part depends on target context
        _SECOND_PART := $(word 2,$(subst /, ,$(STACK_PATH)))
        
        # Detect target type to assign correctly
        ifeq ($(_TARGET),vol-diff)
            # Special case: vol-diff uses VOL1/VOL2
            override VOL1 := $(STACK)
            override VOL2 := $(_SECOND_PART)
            override STACK :=
            override SERVICE :=
            override VOL :=
        else ifeq ($(filter vol-%,$(_TARGET)),vol-)
            # Other volume operations: stack/volume
            override VOL := $(_SECOND_PART)
            override SERVICE :=
        else
            # Regular operation - second part is SERVICE
            override SERVICE := $(_SECOND_PART)
            override VOL :=
        endif
        
        # Validate: only 2 parts allowed
        _PATH_PARTS := $(subst /, ,$(STACK_PATH))
        _PART_COUNT := $(words $(_PATH_PARTS))
        
        ifneq ($(_PART_COUNT),2)
            $(error Invalid path format: $(STACK_PATH) - Use 'stack/service' (max 2 parts))
        endif
    else
        # No slash - just stack name
        override STACK := $(STACK_PATH)
        override SERVICE :=
        override VOL :=
    endif
else
    # No path provided - try to load from cache
    override STACK := $(shell cat $(CACHE_FILE) 2>/dev/null || echo "")
    override SERVICE :=
    override VOL :=
endif

# For ENV override
ENV ?=
ifneq ($(ENV),)
    ENV_FLAG := --env-file $(ENV)
else
    ENV_FLAG :=
endif

# ======================================================================================
# STACK DISCOVERY
# ======================================================================================

# Find compose file for current STACK
define find_compose
$(shell \
    for dir in $(COMPOSE_SEARCH_DIRS); do \
        if [ ! -d "$$dir" ]; then continue; fi; \
        if [ -z "$(STACK)" ]; then continue; fi; \
        found=$$(find "$$dir" -maxdepth $(COMPOSE_SEARCH_DEPTH) -name "$(COMPOSE_BASE_NAME).$(STACK).yml" 2>/dev/null | head -n1); \
        if [ -n "$$found" ]; then echo "$$found"; exit 0; fi; \
        found=$$(find "$$dir" -maxdepth $(COMPOSE_SEARCH_DEPTH) -name "$(COMPOSE_BASE_NAME).yml" 2>/dev/null | while read f; do \
            parent=$$(basename $$(dirname "$$f")); \
            if [ "$$parent" = "$(STACK)" ]; then echo "$$f"; exit 0; fi; \
        done | head -n1); \
        if [ -n "$$found" ]; then echo "$$found"; exit 0; fi; \
    done)
endef

COMPOSE_FILE = $(find_compose)
COMPOSE_PROJECT := $(PROJECT_NAME)-$(STACK)
COMPOSE := docker compose -f $(COMPOSE_FILE) $(ENV_FLAG) -p $(COMPOSE_PROJECT)
SERVICE_FLAG := $(if $(SERVICE),$(SERVICE),)

# ======================================================================================
# CACHE MANAGEMENT
# ======================================================================================

.PHONY: _cache-stack
_cache-stack:
	@if [ -n "$(STACK)" ]; then echo "$(STACK)" > $(CACHE_FILE); fi

# ======================================================================================
# VALIDATION
# ======================================================================================

.PHONY: validate-path validate-stack validate-service validate-config

validate-path:
	@if [ -z "$(STACK)" ] && [ -z "$(VOL1)" ]; then \
		echo -e "$(RED)✖ No stack specified and no cached stack found$(NC)"; \
		echo -e "$(YELLOW)Usage: make [target] <stack>[/service]$(NC)"; \
		echo -e "$(YELLOW)Example: make up core/nginx$(NC)"; \
		exit 1; \
	fi

validate-stack: validate-path _cache-stack
	@if [ "$(VERBOSE)" = "1" ]; then \
		echo -e "$(GRAY)[DEBUG] Validating stack: $(STACK)$(NC)"; \
		echo -e "$(GRAY)[DEBUG] Search dirs: $(COMPOSE_SEARCH_DIRS)$(NC)"; \
		echo -e "$(GRAY)[DEBUG] Search depth: $(COMPOSE_SEARCH_DEPTH)$(NC)"; \
	fi
	@if [ -z "$(COMPOSE_FILE)" ] || [ ! -f "$(COMPOSE_FILE)" ]; then \
		echo -e "$(RED)✖ Stack '$(STACK)' not found$(NC)"; \
		echo -e "$(YELLOW)Available stacks:$(NC)"; \
		for dir in $(COMPOSE_SEARCH_DIRS); do \
			if [ -d "$dir" ]; then \
				find "$dir" -maxdepth $(COMPOSE_SEARCH_DEPTH) -name "$(COMPOSE_FILE_PATTERN)" 2>/dev/null | while read f; do \
					basename_file=$(basename "$f"); \
					parent_dir=$(basename $(dirname "$f")); \
					if [ "$basename_file" = "$(COMPOSE_BASE_NAME).yml" ]; then \
						echo "  - $parent_dir ($f)"; \
					else \
						stack=$(echo "$basename_file" | sed "s/$(COMPOSE_BASE_NAME)\.//; s/\.yml//"); \
						echo "  - $stack ($f)"; \
					fi; \
				done; \
			fi; \
		done | sort -u; \
		exit 1; \
	fi; \
	echo -e "$(GRAY)Using: $(COMPOSE_FILE)$(NC)"

validate-service: validate-stack
	@if [ -n "$(SERVICE)" ]; then \
		if ! $(COMPOSE) config --services 2>/dev/null | grep -q "^$(SERVICE)$$"; then \
			echo -e "$(RED)✖ Service '$(SERVICE)' not found in stack '$(STACK)'$(NC)"; \
			echo -e "$(YELLOW)Available services:$(NC)"; \
			$(COMPOSE) config --services 2>/dev/null | sed 's/^/  - /'; \
			exit 1; \
		fi; \
	fi

validate-config: validate-stack
	@echo -e "$(BLUE)🔍 Validating compose configuration...$(NC)"
	@$(COMPOSE) config --quiet && echo -e "$(GREEN)✅ Configuration valid$(NC)" || \
		(echo -e "$(RED)✖ Configuration invalid$(NC)" && exit 1)

# ======================================================================================
# CORE OPERATIONS
# ======================================================================================

.PHONY: setup create-networks up down restart stop start

setup: validate-stack
	@echo -e "$(GREEN)✅ Setup complete — stack ‘$(STACK)’ validated$(NC)"

up: validate-service setup _cache-stack
	@echo -e "$(BLUE)🚀 Starting: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) up -d $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Stack running$(NC)"
	@$(MAKE) --no-print-directory list-stacks

down: validate-stack _cache-stack
	@echo -e "$(YELLOW)🛑 Stopping: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@if [ -n "$(SERVICE)" ]; then \
		$(COMPOSE) stop $(SERVICE); \
		$(COMPOSE) rm -f $(SERVICE); \
	else \
		$(COMPOSE) down --remove-orphans; \
	fi
	@echo -e "$(GREEN)✅ Stopped$(NC)"
	@$(MAKE) --no-print-directory list-stacks

restart: validate-service _cache-stack
	@echo -e "$(BLUE)♻️  Restarting: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) restart $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Restart complete$(NC)"

stop: validate-service _cache-stack
	@echo -e "$(YELLOW)⏸️  Stopping: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) stop $(SERVICE_FLAG)

start: validate-service _cache-stack
	@echo -e "$(BLUE)▶️  Starting: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) start $(SERVICE_FLAG)

# ======================================================================================
# BUILD & REBUILD
# ======================================================================================

.PHONY: build rebuild pull re rere recreate

build: validate-service _cache-stack
	@echo -e "$(BLUE)🔨 Building: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) build $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Build complete$(NC)"

rebuild: validate-service _cache-stack
	@echo -e "$(BLUE)🔨 Rebuilding (no-cache): $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) build --no-cache $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Rebuild complete$(NC)"

pull: validate-service _cache-stack
	@echo -e "$(BLUE)⬇️  Pulling latest images: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) pull $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Pull complete$(NC)"

re: build restart

rere: rebuild restart

recreate: validate-service _cache-stack
	@echo -e "$(BLUE)🔄 Recreating: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) up -d --force-recreate $(SERVICE_FLAG)
	@echo -e "$(GREEN)✅ Recreate complete$(NC)"

# ======================================================================================
# MONITORING
# ======================================================================================

.PHONY: logs ps status stats watch health top events

logs: validate-service _cache-stack
	@echo -e "$(CYAN)📜 Logs: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@$(COMPOSE) logs -f --tail=$(LOG_TAIL) $(SERVICE_FLAG)

ps status: validate-service _cache-stack
	@if [ -n "$(SERVICE)" ]; then \
		$(COMPOSE) ps $(SERVICE); \
	else \
		echo -e "$(CYAN)📊 Status: $(STACK)$(NC)"; \
		$(COMPOSE) ps -a; \
	fi

stats: validate-service _cache-stack
	@echo -e "$(CYAN)📈 Resource Usage: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@if [ -n "$(SERVICE)" ]; then \
		docker stats --no-stream $($(COMPOSE) ps -q $(SERVICE) 2>/dev/null); \
	else \
		docker stats --no-stream $($(COMPOSE) ps -q 2>/dev/null); \
	fi

top: validate-service _cache-stack
	@echo -e "$(CYAN)📊 Live Resource Monitor: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@echo -e "$(GRAY)Press Ctrl+C to exit$(NC)"
	@if [ -n "$(SERVICE)" ]; then \
		docker stats $($(COMPOSE) ps -q $(SERVICE) 2>/dev/null); \
	else \
		docker stats $($(COMPOSE) ps -q 2>/dev/null); \
	fi

events: validate-stack _cache-stack
	@echo -e "$(CYAN)📡 Docker Events: $(STACK)$(NC)"
	@echo -e "$(GRAY)Press Ctrl+C to exit$(NC)"
	@docker events --filter "label=com.docker.compose.project=$(COMPOSE_PROJECT)" --format '{{.Time}} {{.Status}} {{.Actor.Attributes.name}}'

watch: validate-service _cache-stack
	@echo -e "$(CYAN)👁️  Watching: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@watch -c -n 2 "make --no-print-directory status $(STACK) $(if $(SERVICE),$(STACK)/$(SERVICE),)"

health: validate-stack _cache-stack
	@echo -e "$(CYAN)🏥 Health Check: $(STACK)$(NC)"
	@if command -v jq >/dev/null 2>&1; then \
		$(COMPOSE) ps --format json 2>/dev/null | jq -r 'if type=="array" then .[] else . end | "\(.Service // .Name): \(.State) - \(.Health // "no healthcheck")"' 2>/dev/null || \
		$(COMPOSE) ps --format "table {{.Service}}\t{{.State}}\t{{.Health}}" 2>/dev/null; \
	else \
		$(COMPOSE) ps --format "table {{.Service}}\t{{.State}}\t{{.Health}}" 2>/dev/null; \
	fi

# ======================================================================================
# INTERACTIVE
# ======================================================================================

.PHONY: shell exec

shell: validate-service _cache-stack
	@if [ -z "$(SERVICE)" ]; then \
		echo -e "$(RED)✖ Usage: make shell <stack>/<service>$(NC)"; \
		echo -e "$(YELLOW)Available services:$(NC)"; \
		$(COMPOSE) config --services 2>/dev/null | sed 's/^/  - /'; \
		exit 1; \
	fi
	@$(COMPOSE) exec $(SERVICE) sh

exec: validate-service _cache-stack
	@if [ -z "$(SERVICE)" ]; then \
		echo -e "$(RED)✖ Usage: make exec <stack>/<service> \"<command>\"$(NC)"; \
		exit 1; \
	fi
	@# Extract command from remaining arguments after stack/service
	@cmd="$(wordlist 3,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))"; \
	if [ -z "$cmd" ]; then \
		echo -e "$(RED)✖ Usage: make exec <stack>/<service> \"<command>\"$(NC)"; \
		echo -e "$(YELLOW)Example: make exec core/nginx \"nginx -t\"$(NC)"; \
		exit 1; \
	fi; \
	if [ "$(VERBOSE)" = "1" ]; then \
		echo -e "$(GRAY)[DEBUG] Executing in $(SERVICE): $cmd$(NC)"; \
	fi; \
	$(COMPOSE) exec $(SERVICE) sh -c "$cmd"

# ======================================================================================
# BACKUP
# ======================================================================================

.PHONY: backup

backup: validate-stack _cache-stack
	@timestamp=$(date +%Y%m%d_%H%M%S); \
	backup_dir="$(BACKUP_DIR)/$(STACK)_$timestamp"; \
	mkdir -p "$backup_dir"; \
	echo -e "$(BLUE)📦 Backing up stack: $(STACK)$(NC)"; \
	echo -e "$(GRAY)  Saving compose file...$(NC)"; \
	cp "$(COMPOSE_FILE)" "$backup_dir/docker-compose.yml"; \
	echo -e "$(GRAY)  Backing up volumes...$(NC)"; \
	vol_count=0; \
	for vol in $($(COMPOSE) config --volumes 2>/dev/null); do \
		vol_count=$((vol_count + 1)); \
		echo -e "$(GRAY)    ↳ $vol$(NC)"; \
		docker run --rm -v "$vol:/data:ro" -v "$(pwd)/$backup_dir:/backup" \
			alpine tar czf "/backup/$vol.tar.gz" -C /data . 2>/dev/null || true; \
	done; \
	if [ $vol_count -eq 0 ]; then \
		echo -e "$(YELLOW)  No volumes found$(NC)"; \
	fi; \
	echo -e "$(GREEN)✅ Backup complete: $backup_dir$(NC)"; \
	echo -e "$(GRAY)  - Compose file: docker-compose.yml$(NC)"; \
	echo -e "$(GRAY)  - Volumes: $vol_count$(NC)"

# ======================================================================================
# CLEANUP
# ======================================================================================

.PHONY: clean fclean prune

clean: validate-stack _cache-stack
	@echo -e "$(YELLOW)🧹 Cleaning: $(STACK)$(if $(SERVICE), [$(SERVICE)],)$(NC)"
	@if [ -n "$(SERVICE)" ]; then \
		$(COMPOSE) stop $(SERVICE); \
		$(COMPOSE) rm -f $(SERVICE); \
	else \
		$(COMPOSE) down --remove-orphans; \
	fi
	@echo -e "$(GREEN)✅ Clean complete$(NC)"

fclean: validate-stack _cache-stack
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

.PHONY: list-stacks list-services

list-stacks:
	@total_stacks=0; total_running=0; total_unhealthy=0; total_offline=0; \
	for dir in $(COMPOSE_SEARCH_DIRS); do \
		if [ ! -d "$$dir" ]; then continue; fi; \
		while read -r f; do \
			stack_name="<unknown>"; \
			basename_file=$$(basename "$$f"); \
			parent_dir=$$(basename $$(dirname "$$f")); \
			if [ "$$basename_file" = "$(COMPOSE_BASE_NAME).yml" ]; then \
				stack_name="$$parent_dir"; \
			else \
				stack_name=$$(echo "$$basename_file" | sed "s/$(COMPOSE_BASE_NAME)\.//; s/\.yml//"); \
			fi; \
			project_name="$(PROJECT_NAME)-$$stack_name"; \
			running_cnt=$$(docker ps -q --filter "status=running" --filter "label=com.docker.compose.project=$$project_name" 2>/dev/null | wc -l); \
			total_cnt=$$(docker ps -a -q --filter "label=com.docker.compose.project=$$project_name" 2>/dev/null | wc -l); \
			unhealthy_cnt=$$(docker ps -q --filter "health=unhealthy" --filter "label=com.docker.compose.project=$$project_name" 2>/dev/null | wc -l); \
			if [ -n "$(ONLINE)" ] && [ "$$running_cnt" -eq 0 ]; then continue; fi; \
			total_stacks=$$((total_stacks + 1)); \
			rel_path=$$(echo "$$f" | sed "s|^./||"); \
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
				printf "$(GRAY)     📁 %s$(NC)\n" "$$rel_path"; \
				services_list=$$(docker ps --filter "label=com.docker.compose.project=$$project_name" --format "{{.Names}}" 2>/dev/null | sort); \
				service_count=$$(echo "$$services_list" | wc -l); \
				current_service=0; \
				while IFS= read -r service_name; do \
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
				done <<< "$$services_list"; \
				echo ""; \
			else \
				if [ "$$total_cnt" -gt 0 ]; then \
					total_offline=$$((total_offline + 1)); \
					printf "$(RED)● %-18s$(NC) $(RED)%-11s$(NC) [%2d/%2d stopped]\n" "$$stack_name" "STOPPED" "$$running_cnt" "$$total_cnt"; \
				else \
					printf "$(GRAY)○ %-18s$(NC) $(GRAY)%-11s$(NC) [no containers]\n" "$$stack_name" "OFFLINE"; \
				fi; \
				printf "$(GRAY)     📁 %s$(NC)\n\n" "$$rel_path"; \
			fi; \
		done < <(find "$$dir" -maxdepth $(COMPOSE_SEARCH_DEPTH) -name "$(COMPOSE_FILE_PATTERN)" 2>/dev/null); \
	done; \
	echo -e "$(PURPLE)──────────────────────────────────────────────────────────────────────────────$(NC)"; \
	echo -e " $(BOLD)Summary:$(NC)  $(GREEN)✔ $$total_running running$(NC),  $(RED)✖ $$total_unhealthy unhealthy$(NC),  $(GRAY)○ $$total_offline offline$(NC),  total: $$total_stacks"; \
	echo -e "$(PURPLE)──────────────────────────────────────────────────────────────────────────────$(NC)\n"; \
	echo -e " Legend:  $(GREEN)●$(GRAY)=Healthy  $(YELLOW)●$(GRAY)=Degraded  $(RED)●$(GRAY)=Unhealthy  $(GRAY)○$(GRAY)=Offline$(NC)\n"; \
	echo -e " $(GRAY)Search paths: $(COMPOSE_SEARCH_DIRS)$(NC)\n"

list-services: validate-stack _cache-stack
	@$(COMPOSE) config --format json > /tmp/$$.compose.json
	@GRAY="$$(printf '\033[0;90m')"; RED="$$(printf '\033[0;31m')"; GREEN="$$(printf '\033[0;32m')"; YELLOW="$$(printf '\033[1;33m')"; \
	DIM="$$(printf '\033[2m')"; NC="$$(printf '\033[0m')"; CYAN="$$(printf '\033[0;36m')"; WHITE="$$(printf '\033[1;37m')"; \
	BLUE="$$(printf '\033[0;34m')"; PURPLE="$$(printf '\033[0;35m')"; BOLD="$$(printf '\033[1m')"; \
	jq -c '.services | to_entries[]' /tmp/$$.compose.json | while IFS= read -r svc_obj; do \
		svc=$$(echo "$$svc_obj" | jq -r '.key'); \
		container=$$($(COMPOSE) ps -q "$$svc" 2>/dev/null | head -n1); \
		if [ -z "$$container" ]; then \
			printf "$${GRAY}○ %-20s $${RED}%s$${NC} $${DIM}(no container)$${NC}\n\n" "$$svc" "●"; \
			continue; \
		fi; \
		state=$$(docker inspect -f '{{.State.Status}}' "$$container"); \
		health=$$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$$container"); \
		restart_policy=$$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$$container"); \
		restart_count=$$(docker inspect -f '{{.RestartCount}}' "$$container"); \
		pid=$$(docker inspect -f '{{.State.Pid}}' "$$container"); \
		uptime_raw=$(docker inspect -f '{{if .State.Running}}{{.State.StartedAt}}{{end}}' "$container"); \
		if [ -n "$uptime_raw" ]; then \
			uptime_secs=$(date -d "$uptime_raw" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "${uptime_raw%.*}" +%s 2>/dev/null || echo "0"); \
			now_secs=$(date +%s); \
			uptime_delta=`expr $now_secs - $uptime_secs 2>/dev/null || echo "0"`; \
			uptime=$(awk -v d="$uptime_delta" 'BEGIN{printf "%dd %dh %dm",int(d/86400),int((d%86400)/3600),int((d%3600)/60)}' 2>/dev/null || echo "0d 0h 0m"); \
		else uptime="0d 0h 0m"; fi; \
		img=$(docker inspect -f '{{.Config.Image}}' "$container"); \
		dig=$(docker inspect -f '{{if index . "RepoDigests"}}{{if index .RepoDigests 0}}{{index .RepoDigests 0}}{{else}}{{.Id}}{{end}}{{else}}{{.Id}}{{end}}' "$container" | sed 's/.*[:@]//' | cut -c1-12); \
		[ "$$state" = "running" ] && colour="$$GREEN" || colour="$$RED"; \
		[ "$$health" = "healthy" ] && hdot="$$GREEN●$$NC" || { [ "$$health" = "none" ] && hdot="$$YELLOW●$$NC" || hdot="$$RED●$$NC"; }; \
		printf "$${colour}$${BOLD}%-20s$${NC} %b $${DIM}($$state" "$$svc" "$$hdot"; \
		[ "$$health" != "none" ] && printf ", $$health"; \
		printf ")$${NC}\n"; \
		printf "  $${DIM}·$${NC} $${CYAN}%-8s$${NC} %s\n" "image" "$$img"; \
		printf "  $${DIM}·$${NC} $${CYAN}%-8s$${NC} %s $${DIM}(pid: $$pid)$${NC}\n" "digest" "$$dig"; \
		printf "  $${DIM}·$${NC} $${CYAN}%-8s$${NC} %s $${DIM}(restarts: $$restart_count)$${NC}\n" "restart" "$$restart_policy"; \
		printf "  $${DIM}·$${NC} $${CYAN}%-8s$${NC} %s\n\n" "uptime" "$$uptime"; \
		printf "  $${BLUE}$${BOLD}Networking$${NC}\n"; \
		docker inspect -f '{{range $$net,$$conf := .NetworkSettings.Networks}}{{$$net}}|{{$$conf.IPAddress}}|{{$$conf.Aliases}}{{"\n"}}{{end}}' "$$container" | while IFS='|' read -r net ip aliases; do \
			[ -z "$$net" ] && continue; \
			aliases_clean=$$(echo "$$aliases" | sed 's/\[//; s/\]//; s/ /,/g'); \
			printf "  $${DIM}·$${NC} $${PURPLE}%-8s$${NC} %s" "$$net" "$$ip"; \
			[ -n "$$aliases_clean" ] && [ "$$aliases_clean" != "" ] && printf " $${DIM}(aliases: $$aliases_clean)$${NC}"; \
			printf "\n"; \
		done; \
		ports=$(docker inspect -f '{{range $p, $conf := .NetworkSettings.Ports}}{{if $conf}}{{$p}}→{{range $conf}}{{.HostPort}}{{end}} {{end}}{{end}}' "$container" | sed 's/ *$//'); \
		[ -n "$ports" ] && printf "  ${DIM}·${NC} ${PURPLE}%-8s${NC} %s\n" "ports" "$(echo $ports | sed 's/  */ /g; s/ /, /g')"; \
		printf "\n  ${BLUE}${BOLD}Storage${NC}\n"; \
		docker inspect -f '{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Destination}}|{{.RW}}{{"\n"}}{{end}}' "$container" | while IFS='|' read -r mtype src dst rw; do \
			[ -z "$mtype" ] && continue; \
			rw_label="ro"; [ "$rw" = "true" ] && rw_label="rw"; \
			src_short=$(echo "$src" | sed "s|^${HOME}|~|; s|^/var/lib/docker/volumes/||"); \
			if [ "$mtype" = "bind" ]; then \
				printf "  ${DIM}·${NC} ${src_short} ${DIM}→${NC} $dst ${DIM}(bind, $rw_label)${NC}\n"; \
			elif [ "$mtype" = "volume" ]; then \
				printf "  ${DIM}·${NC} ${src_short} ${DIM}→${NC} $dst ${DIM}(volume, $rw_label)${NC}\n"; \
			else \
				printf "  ${DIM}·${NC} $dst ${DIM}($mtype, $rw_label)${NC}\n"; \
			fi; \
		done; \
		mem_limit=$(docker inspect -f '{{.HostConfig.Memory}}' "$container"); \
		mem_reservation=$(docker inspect -f '{{.HostConfig.MemoryReservation}}' "$container"); \
		cpu_quota=$(docker inspect -f '{{.HostConfig.CpuQuota}}' "$container"); \
		cpu_period=$(docker inspect -f '{{.HostConfig.CpuPeriod}}' "$container"); \
		if [ "$mem_limit" != "0" ] || [ "$cpu_quota" != "0" ]; then \
			printf "\n  ${BLUE}${BOLD}Resources${NC}\n"; \
			if [ "$mem_limit" != "0" ]; then \
				mem_mb=$((mem_limit / 1024 / 1024)); \
				printf "  ${DIM}·${NC} ${CYAN}%-8s${NC} ${mem_mb}M limit" "memory"; \
				if [ "$mem_reservation" != "0" ]; then \
					mem_res_mb=$((mem_reservation / 1024 / 1024)); \
					printf ", ${mem_res_mb}M reserved"; \
				fi; \
				printf "\n"; \
			fi; \
			if [ "$cpu_quota" != "0" ] && [ "$cpu_period" != "0" ]; then \
				cpu_cores=$(awk -v q="$cpu_quota" -v p="$cpu_period" 'BEGIN{printf "%.2f", q/p}'); \
				printf "  ${DIM}·${NC} ${CYAN}%-8s${NC} ${cpu_cores} cores limit\n" "cpu"; \
			fi; \
		fi; \
		labels=$(echo "$svc_obj" | jq -er '.value.labels // {} | to_entries | map(select(.key | startswith("traefik.") or startswith("backup.") or startswith("com."))) | map("\(.key)=\(.value|tostring)") | join(",")' 2>/dev/null || echo ""); \
		if [ -n "$labels" ] && [ "$labels" != "" ]; then \
			printf "\n  ${BLUE}${BOLD}Labels${NC}\n"; \
			echo "$labels" | tr ',' '\n' | while read -r label; do \
				[ -n "$label" ] && { \
					label_key="${label%%=*}"; label_val="${label#*=}"; \
					printf "  ${DIM}·${NC} ${CYAN}%s${DIM}=${NC}${WHITE}%s${NC}\n" "$label_key" "$label_val"; \
				}; \
			done; \
		fi; \
		printf "\n${GRAY}────────────────────────────────────────────────────────────${NC}\n\n"; \
	done
	@rm -f /tmp/$.compose.json

# ======================================================================================
# VOLUME OPERATIONS
# ======================================================================================

.PHONY: volumes vol-inspect vol-backup vol-restore vol-export vol-import vol-clone vol-diff vol-clean vol-prune

volumes: validate-stack _cache-stack
	@echo -e "$(CYAN)📦 Volumes in stack: $(STACK)$(NC)"
	@$(COMPOSE) config --volumes 2>/dev/null | while read vol; do \
		size=$(docker volume inspect "$vol" --format '{{.Mountpoint}}' 2>/dev/null | xargs du -sh 2>/dev/null | cut -f1 || echo "N/A"); \
		echo -e "  $(GREEN)●$(NC) $vol $(GRAY)($size)$(NC)"; \
	done

vol-inspect: validate-stack _cache-stack
	@if [ -z "$(VOL)" ]; then \
		echo -e "$(RED)✖ Usage: make vol-inspect <stack>/<volume>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(CYAN)🔍 Inspecting volume: $(VOL)$(NC)"
	@docker volume inspect "$(VOL)"

vol-backup: validate-stack _cache-stack
	@if [ -z "$(VOL)" ]; then \
		echo -e "$(RED)✖ Usage: make vol-backup <stack>/<volume>$(NC)"; \
		exit 1; \
	fi
	@timestamp=$(date +%Y%m%d_%H%M%S); \
	backup_file="$(BACKUP_DIR)/volumes/$(STACK)/$(VOL)_$timestamp.tar.gz"; \
	mkdir -p "$(dirname $backup_file)"; \
	echo -e "$(BLUE)📦 Backing up volume: $(VOL)$(NC)"; \
	docker run --rm -v "$(VOL):/data" -v "$(pwd)/$(BACKUP_DIR)/volumes/$(STACK):/backup" \
		alpine tar czf "/backup/$(VOL)_$timestamp.tar.gz" -C /data . 2>/dev/null; \
	echo -e "$(GREEN)✅ Backup complete: $backup_file$(NC)"

vol-restore: validate-stack _cache-stack
	@if [ -z "$(VOL)" ] || [ -z "$(BACKUP)" ]; then \
		echo -e "$(RED)✖ Usage: make vol-restore <stack>/<volume> BACKUP=<path>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(YELLOW)⚠️  This will overwrite volume: $(VOL)$(NC)"; \
	@read -p "Continue? [y/N] " -n 1 -r; echo; \
	if [[ $REPLY =~ ^[Yy]$ ]]; then \
		echo -e "$(BLUE)📦 Restoring volume: $(VOL)$(NC)"; \
		docker run --rm -v "$(VOL):/data" -v "$(pwd):/backup" \
			alpine sh -c "cd /data && tar xzf /backup/$(BACKUP)"; \
		echo -e "$(GREEN)✅ Restore complete$(NC)"; \
	else \
		echo -e "$(GRAY)Cancelled$(NC)"; \
	fi

vol-export: validate-stack _cache-stack
	@if [ -z "$(VOL)" ]; then \
		echo -e "$(RED)✖ Usage: make vol-export <stack>/<volume> [DIR=path]$(NC)"; \
		exit 1; \
	fi
	@if [ -z "$(DIR)" ]; then \
		timestamp=$(date +%Y%m%d_%H%M%S); \
		export_dir="$(EXPORT_DIR)/$(STACK)/$(VOL)_$timestamp"; \
	else \
		export_dir="$(DIR)"; \
	fi; \
	mkdir -p "$export_dir"; \
	echo -e "$(BLUE)📤 Exporting volume: $(VOL) → $export_dir$(NC)"; \
	docker run --rm -v "$(VOL):/data:ro" -v "$(pwd)/$export_dir:/export" \
		alpine cp -a /data/. /export/; \
	echo -e "$(GREEN)✅ Export complete: $export_dir$(NC)"

vol-import: validate-stack _cache-stack
	@if [ -z "$(VOL)" ] || [ -z "$(DIR)" ]; then \
		echo -e "$(RED)✖ Usage: make vol-import <stack>/<volume> DIR=<path>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(YELLOW)⚠️  This will overwrite volume: $(VOL)$(NC)"; \
	@read -p "Continue? [y/N] " -n 1 -r; echo; \
	if [[ $REPLY =~ ^[Yy]$ ]]; then \
		echo -e "$(BLUE)📥 Importing to volume: $(VOL)$(NC)"; \
		docker run --rm -v "$(VOL):/data" -v "$(pwd)/$(DIR):/import:ro" \
			alpine cp -a /import/. /data/; \
		echo -e "$(GREEN)✅ Import complete$(NC)"; \
	else \
		echo -e "$(GRAY)Cancelled$(NC)"; \
	fi

vol-clone: validate-stack _cache-stack
	@if [ -z "$(VOL)" ] || [ -z "$(TARGET)" ]; then \
		echo -e "$(RED)✖ Usage: make vol-clone <stack>/<volume> TARGET=<new-volume>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(BLUE)📋 Cloning volume: $(VOL) → $(TARGET)$(NC)"; \
	@docker volume create "$(TARGET)" >/dev/null; \
	docker run --rm -v "$(VOL):/source:ro" -v "$(TARGET):/target" \
		alpine cp -a /source/. /target/; \
	echo -e "$(GREEN)✅ Clone complete: $(TARGET)$(NC)"

vol-diff:
	@if [ -z "$(VOL1)" ] || [ -z "$(VOL2)" ]; then \
		echo -e "$(RED)✖ Usage: make vol-diff <vol1>/<vol2>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(CYAN)📊 Comparing volumes: $(VOL1) ↔ $(VOL2)$(NC)"; \
	size1=$(docker volume inspect "$(VOL1)" --format '{{.Mountpoint}}' 2>/dev/null | xargs du -sb 2>/dev/null | cut -f1 || echo "0"); \
	size2=$(docker volume inspect "$(VOL2)" --format '{{.Mountpoint}}' 2>/dev/null | xargs du -sb 2>/dev/null | cut -f1 || echo "0"); \
	echo -e "  $(VOL1): $(numfmt --to=iec-i --suffix=B $size1 2>/dev/null || echo $size1)"; \
	echo -e "  $(VOL2): $(numfmt --to=iec-i --suffix=B $size2 2>/dev/null || echo $size2)"; \
	diff=$((size1 - size2)); \
	if [ $diff -gt 0 ]; then \
		echo -e "  $(YELLOW)Difference: +$(numfmt --to=iec-i --suffix=B $diff 2>/dev/null || echo $diff) (VOL1 larger)$(NC)"; \
	elif [ $diff -lt 0 ]; then \
		echo -e "  $(YELLOW)Difference: $(numfmt --to=iec-i --suffix=B $diff 2>/dev/null || echo $diff) (VOL2 larger)$(NC)"; \
	else \
		echo -e "  $(GREEN)Same size$(NC)"; \
	fi

vol-clean: validate-stack _cache-stack
	@echo -e "$(YELLOW)🧹 Cleaning unused volumes in stack: $(STACK)$(NC)"
	@$(COMPOSE) down --volumes --remove-orphans 2>/dev/null || true
	@echo -e "$(GREEN)✅ Cleanup complete$(NC)"

vol-prune:
	@echo -e "$(RED)🧹 System-wide volume prune (WARNING: removes all unused volumes)$(NC)"
	@read -p "Continue? [y/N] " -n 1 -r; echo; \
	if [[ $REPLY =~ ^[Yy]$ ]]; then \
		docker volume prune -f; \
		echo -e "$(GREEN)✅ Volumes pruned$(NC)"; \
	else \
		echo -e "$(GRAY)Cancelled$(NC)"; \
	fi

# ======================================================================================
# ADVANCED OPERATIONS
# ======================================================================================

.PHONY: scale rollback network-inspect port

scale: validate-service _cache-stack
	@if [ -z "$(SERVICE)" ] || [ -z "$(REPLICAS)" ]; then \
		echo -e "$(RED)✖ Usage: make scale <stack>/<service> REPLICAS=<n>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(BLUE)⚖️  Scaling $(SERVICE) to $(REPLICAS) replicas$(NC)"; \
	$(COMPOSE) up -d --scale $(SERVICE)=$(REPLICAS) $(SERVICE); \
	echo -e "$(GREEN)✅ Scaled$(NC)"

rollback: validate-service _cache-stack
	@if [ -z "$(SERVICE)" ]; then \
		echo -e "$(RED)✖ Usage: make rollback <stack>/<service>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(YELLOW)⏪ Rolling back $(SERVICE) to previous image$(NC)"; \
	current_image=$(docker inspect --format='{{.Config.Image}}' "$($(COMPOSE) ps -q $(SERVICE) 2>/dev/null)" 2>/dev/null || echo ""); \
	if [ -z "$current_image" ]; then \
		echo -e "$(RED)✖ Service not running$(NC)"; \
		exit 1; \
	fi; \
	echo -e "$(GRAY)  Current: $current_image$(NC)"; \
	echo -e "$(BLUE)  Stopping service...$(NC)"; \
	$(COMPOSE) stop $(SERVICE) 2>/dev/null; \
	echo -e "$(BLUE)  Removing container...$(NC)"; \
	$(COMPOSE) rm -f $(SERVICE) 2>/dev/null; \
	echo -e "$(BLUE)  Starting with previous image...$(NC)"; \
	$(COMPOSE) up -d $(SERVICE); \
	new_image=$(docker inspect --format='{{.Config.Image}}' "$($(COMPOSE) ps -q $(SERVICE) 2>/dev/null)" 2>/dev/null || echo ""); \
	echo -e "$(GRAY)  New: $new_image$(NC)"; \
	echo -e "$(GREEN)✅ Rollback complete$(NC)"; \
	echo -e "$(YELLOW)Note: This recreates the container. For true image rollback, update compose file.$(NC)"

network-inspect: validate-stack _cache-stack
	@echo -e "$(CYAN)🌐 Network topology for stack: $(STACK)$(NC)"
	@for net in $($(COMPOSE) config --format json | jq -r '.networks | keys[]' 2>/dev/null); do \
		echo -e "\n$(BOLD)$net:$(NC)"; \
		docker network inspect "$net" --format '{{range .Containers}}  - {{.Name}} ({{.IPv4Address}}){{"\n"}}{{end}}' 2>/dev/null; \
	done

port: validate-service _cache-stack
	@if [ -z "$(SERVICE)" ]; then \
		echo -e "$(RED)✖ Usage: make port <stack>/<service>$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(CYAN)🔌 Port mappings for $(SERVICE):$(NC)"
	@$(COMPOSE) ps --format json $(SERVICE) 2>/dev/null | jq -r 'if type=="array" then .[] else . end | .Publishers // [] | .[] | "  \(.PublishedPort):\(.TargetPort)/\(.Protocol)"' 2>/dev/null || \
		docker port "$($(COMPOSE) ps -q $(SERVICE) 2>/dev/null | head -1)" 2>/dev/null | sed 's/^/  /' || \
		echo -e "$(GRAY)  No ports exposed$(NC)"

# ======================================================================================
# MULTI-STACK SHORTCUTS (Renamed to avoid conflicts with stack names)
# ======================================================================================

.PHONY: all all-down all-restart

all: ## Start all production stacks
	@for stack in $(PRODUCTION_STACKS); do \
		$(MAKE) up $$stack; \
	done

all-down: ## Stop all production stacks
	@for stack in $(PRODUCTION_STACKS); do \
		$(MAKE) down $$stack 2>/dev/null || true; \
	done

all-restart: ## Restart all production stacks
	@for stack in $(PRODUCTION_STACKS); do \
		$(MAKE) restart $$stack; \
	done

# ======================================================================================
# UTILITIES
# ======================================================================================

.PHONY: boiler-lab test-parse

boiler-lab: ## Scaffold a new microservice: make boiler-lab NAME=my_service
	@if [ -z "$(NAME)" ]; then \
		echo -e "$(RED)✖ Usage: make boiler-lab NAME=<service-name> [PORT=<port>]$(NC)"; \
		exit 1; \
	fi
	@python3 scripts/boiler-lab.py "$(NAME)" $(if $(PORT),--port $(PORT),)

test-parse:
	@echo -e "$(CYAN)=== Parser Test ===$(NC)"
	@echo "MAKECMDGOALS  : $(MAKECMDGOALS)"
	@echo "_ALL_GOALS    : $(_ALL_GOALS)"
	@echo "_TARGET       : $(_TARGET)"
	@echo "STACK_PATH    : $(STACK_PATH)"
	@echo "STACK         : $(STACK)"
	@echo "SERVICE       : $(SERVICE)"
	@echo "VOL           : $(VOL)"
	@echo "VOL1          : $(VOL1)"
	@echo "VOL2          : $(VOL2)"
	@echo "COMPOSE_FILE  : $(COMPOSE_FILE)"
	@echo "ENV_FLAG      : $(ENV_FLAG)"

# ======================================================================================
# HELP
# ======================================================================================

.DEFAULT_GOAL := help

.PHONY: help

help:
	@echo -e "$(BLUE)========================================================================="
	@echo -e " Makefile v2 - The Master Control Program"
	@echo -e "=========================================================================$(NC)"
	@echo -e "$(CYAN)\"The distance between thought and action, minimized.\"$(NC)"
	@echo ""
	@echo -e "$(YELLOW)New Syntax:$(NC)"
	@echo -e "  make [target] <stack>[/service] [PARAMS]"
	@echo ""
	@echo -e "$(GREEN)Core Operations:$(NC)"
	@echo -e "  up <stack>[/service]     - Start stack or service"
	@echo -e "  down <stack>[/service]   - Stop and remove"
	@echo -e "  restart <stack>[/service]- Restart"
	@echo -e "  stop/start <stack>[/svc] - Stop/start without removing"
	@echo -e "  build <stack>[/service]  - Build images (cached)"
	@echo -e "  rebuild <stack>[/svc]    - Build images (no-cache)"
	@echo -e "  pull <stack>[/service]   - Pull latest images"
	@echo -e "  re/rere <stack>[/svc]    - Build and restart"
	@echo -e "  recreate <stack>[/svc]   - Force recreate containers"
	@echo ""
	@echo -e "$(GREEN)Monitoring:$(NC)"
	@echo -e "  logs <stack>[/service]   - Follow logs (LOG_TAIL=N)"
	@echo -e "  ps/status <stack>[/svc]  - Show container status"
	@echo -e "  stats <stack>[/service]  - Resource usage (one-time)"
	@echo -e "  top <stack>[/service]    - Live resource monitor"
	@echo -e "  events <stack>           - Stream Docker events"
	@echo -e "  watch <stack>[/service]  - Live status updates"
	@echo -e "  list-stacks [ONLINE=1]     - Dashboard (ONLINE=1 for running only)"
	@echo -e "  list-services <stack>    - Detailed service info"
	@echo -e "  health <stack>           - Health check report"
	@echo ""
	@echo -e "$(GREEN)Interactive:$(NC)"
	@echo -e "  shell <stack>/<service>  - Interactive shell"
	@echo -e "  exec <stack>/<svc> cmd   - Execute command"
	@echo ""
	@echo -e "$(GREEN)Backup & Restore:$(NC)"
	@echo -e "  backup <stack>           - Backup compose file + volumes"
	@echo ""
	@echo -e "$(GREEN)Volume Operations:$(NC)"
	@echo -e "  volumes <stack>                    - List volumes"
	@echo -e "  vol-inspect <stack>/<volume>       - Inspect volume"
	@echo -e "  vol-backup <stack>/<volume>        - Backup volume"
	@echo -e "  vol-restore <stack>/<vol> BACKUP=  - Restore volume"
	@echo -e "  vol-export <stack>/<vol> [DIR=]    - Export to directory"
	@echo -e "  vol-import <stack>/<vol> DIR=      - Import from directory"
	@echo -e "  vol-clone <stack>/<vol> TARGET=    - Clone volume"
	@echo -e "  vol-diff <vol1>/<vol2>             - Compare volumes"
	@echo -e "  vol-clean <stack>                  - Clean unused volumes"
	@echo -e "  vol-prune                          - System-wide prune"
	@echo ""
	@echo -e "$(GREEN)Advanced:$(NC)"
	@echo -e "  scale <stack>/<svc> REPLICAS=N - Scale service"
	@echo -e "  rollback <stack>/<service>     - Rollback service"
	@echo -e "  network-inspect <stack>        - Network topology"
	@echo -e "  port <stack>/<service>         - Port mappings"
	@echo -e "  validate-config <stack>        - Validate compose file"
	@echo ""
	@echo -e "$(GREEN)Cleanup:$(NC)"
	@echo -e "  clean <stack>[/service]  - Remove containers"
	@echo -e "  fclean <stack>           - Remove containers + volumes"
	@echo -e "  prune                    - System-wide prune"
	@echo ""
	@echo -e "$(GREEN)Utilities:$(NC)"
	@echo -e "  boiler-lab NAME=<name>   - Create service boilerplate (compose + Dockerfile + FastAPI stub)"
	@echo -e "  test-parse <stack>[/svc] - Debug parser"
	@echo ""
	@echo -e "$(YELLOW)Examples:$(NC)"
	@echo -e "  make all                                  # Start all production stacks ($(PRODUCTION_STACKS))"
	@echo -e "  make up core                              # Start core stack (api_gateway, inference, redis, nginx, ...)"
	@echo -e "  make up humanizer                         # Start humanizer service"
	@echo -e "  make up yt-lab                            # Start yt-lab stack (extractor + lab)"
	@echo -e "  make up core/api_gateway                  # Start specific service"
	@echo -e "  make logs core                            # Follow all logs"
	@echo -e "  make logs core/blog_generator LOG_TAIL=500"
	@echo -e "  make top core                             # Live resource monitor"
	@echo -e "  make list-stacks                          # Dashboard of all stacks"
	@echo -e "  make list-stacks ONLINE=1                 # Running stacks only"
	@echo -e "  make list-services core                   # Detailed per-service info"
	@echo -e "  make shell core/api_gateway               # Interactive shell"
	@echo -e "  make backup core                          # Backup compose file + volumes"
	@echo -e "  make rebuild core                         # Rebuild all images (no cache)"
	@echo -e "  make health core                          # Health check report"
	@echo -e "  make VERBOSE=1 up core                    # Verbose mode"
	@echo ""
	@echo -e "$(YELLOW)Configuration (override in .env):$(NC)"
	@echo -e "  PROJECT_NAME=$(PROJECT_NAME)"
	@echo -e "  COMPOSE_BASE_NAME=$(COMPOSE_BASE_NAME)"
	@echo -e "  COMPOSE_SEARCH_DIRS=$(COMPOSE_SEARCH_DIRS)"
	@echo -e "  NETWORK_NAMES=$(NETWORK_NAMES)"
	@echo -e "  VERBOSE=$(VERBOSE)  (set to 1 for debug output)"
	@echo -e "$(YELLOW)Production stacks ($(PRODUCTION_STACKS)):$(NC)"
	@echo -e "  core      — api_gateway, inference-gateway, blog_generator, event_bus, ..."
	@echo -e "  humanizer — text humanization (port 8013)"
	@echo -e "  yt-lab    — YouTube automation stack (extractor :8020 + lab :8021)"
	@echo ""
	@echo -e "$(GRAY)Cache file: $(CACHE_FILE) (stores last-used stack)$(NC)"
	@echo -e "$(BLUE)=========================================================================$(NC)"

# ======================================================================================
# DUMMY TARGET (prevents "No rule to make target" errors for stack/service paths)
# ======================================================================================

%:
	@:
