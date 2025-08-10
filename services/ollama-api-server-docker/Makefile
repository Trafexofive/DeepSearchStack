# ======================================================================================
#                          CHIMERA DOCKER ORCHESTRATOR
# ======================================================================================
#
#  The Unified Master Control Program for the entire Chimera Stack.
#  Final Forging by Gemini. One command to rule them all.
#
# ======================================================================================

# --- Configuration ---
SHELL := /bin/bash
COMPOSE_FILE := docker-compose.yml
COMPOSE := docker-compose -f docker-compose.yml

# --- Cosmetics ---
RED     := \033[0;31m
GREEN   := \033[0;32m
YELLOW  := \033[0;33m
BLUE    := \033[0;34m
PURPLE  := \033[0;35m
CYAN    := \033[0;36m
NC      := \033[0m

.DEFAULT_GOAL := help

# ======================================================================================
#                                  SELF-DOCUMENTATION
# ======================================================================================

help:
	@echo -e "${PURPLE}==========================================================================${NC}"
	@echo -e " ${PURPLE}Chimera Unified Stack - Master Control Program${NC}"
	@echo -e "${PURPLE}==========================================================================${NC}"
	@echo -e "\n${YELLOW}Usage:${NC} make [target] [service=SERVICE_NAME]\n"
	@echo -e "${GREEN}Core Stack Management:${NC}"
	@echo -e "  ${CYAN}up${NC}                  - Builds and ignites the entire Chimera stack."
	@echo -e "  ${CYAN}down${NC}                - Shuts down the stack and removes containers."
	@echo -e "  ${CYAN}start${NC}               - Starts existing containers."
	@echo -e "  ${CYAN}stop${NC}                - Stops running containers."
	@echo -e "  ${CYAN}restart${NC}             - Restarts the entire stack."
	@echo -e "  ${CYAN}re${NC}                  - ${YELLOW}Obliterates and completely rebuilds the stack from scratch.${NC}"
	@echo -e "\n${GREEN}Building & Forging:${NC}"
	@echo -e "  ${CYAN}build${NC} [service=<name>] - Forges container images (all or specific service)."
	@echo -e "\n${GREEN}System Diagnostics & Interaction:${NC}"
	@echo -e "  ${CYAN}status${NC}              - Displays the status of all services."
	@echo -e "  ${CYAN}logs${NC} [service=<name>] - Taps into the data stream of a service."
	@echo -e "  ${CYAN}ssh${NC} [service=<name>]  - Establishes a shell into a service container."
	@echo -e "\n${GREEN}Testing & Validation:${NC}"
	@echo -e "  ${CYAN}test${NC}                - Runs the primary orchestrator test suite."
	@echo -e "  ${CYAN}test-all${NC}            - Runs all available test suites."
	@echo -e "  ${CYAN}test-lifecycle${NC}      - Runs the gateway and worker lifecycle test."
	@echo -e "  ${CYAN}test-concurrency${NC}    - Runs the gateway concurrency test."
	@echo -e "  ${CYAN}test-client${NC}         - Runs the client commands test."
	@echo -e "  ${CYAN}test-final${NC}          - Runs the new, streamlined final test suite."
	@echo -e "\n${GREEN}Sanitization & Pruning:${NC}"
	@echo -e "  ${CYAN}clean${NC}              - ${RED}DANGER:${NC} Obliterates all stack containers, networks, and volumes."
	@echo -e "  ${CYAN}prune${NC}               - ${RED}DANGER:${NC} Obliterates all unused Docker assets on the host."
	@echo -e "${PURPLE}==========================================================================${NC}"


# ======================================================================================
#                               CORE STACK MANAGEMENT
# ======================================================================================

up: build
	@echo -e "${GREEN}Igniting the unified Chimera stack...${NC}"
	@$(COMPOSE) up -d --remove-orphans

down:
	@echo -e "${RED}Shutting down the Chimera stack...${NC}"
	@$(COMPOSE) down --remove-orphans

stop:
	@echo -e "${YELLOW}Stopping Chimera stack containers...${NC}"
	@$(COMPOSE) stop

start:
	@echo -e "${GREEN}Starting existing Chimera stack containers...${NC}"
	@$(COMPOSE) start

restart: stop start

re: clean up
	@echo -e "${GREEN}Stack has been reforged and reignited from a clean slate.${NC}"

# ======================================================================================
#                              BUILDING & FORGING
# ======================================================================================

build:
	@echo -e "${BLUE}Forging components... Building images for $(or $(service), all services).${NC}"
	@$(COMPOSE) build $(service)

# ======================================================================================
#                         SYSTEM DIAGNOSTICS & INTERACTION
# ======================================================================================

status:
	@echo -e "${BLUE}System Status Report:${NC}"
	@$(COMPOSE) ps

logs:
	@echo -e "${BLUE}Tapping into data stream for $(or $(service), all services)...${NC}"
	@$(COMPOSE) logs -f --tail=100 $(service)

ssh:
	@if [ -z "$(service)" ]; then \
		echo -e "${RED}Error: Service name required. Usage: make ssh service=<service_name>${NC}"; \
		exit 1; \
	fi
	@echo -e "${GREEN}Establishing DirectConnect to $(service)...${NC}"
	@$(COMPOSE) exec $(service) /bin/bash || $(COMPOSE) exec $(service) /bin/sh

# ======================================================================================
#                              TESTING & VALIDATION
# ======================================================================================

test:
	@echo -e "${PURPLE}Running primary orchestrator test suite...${NC}"
	@./tests/test_orchestrator.sh

test-all: test test-lifecycle test-concurrency test-client
	@echo -e "${GREEN}All test suites passed successfully.${NC}"

test-lifecycle:
	@echo -e "${PURPLE}Running gateway and worker lifecycle test...${NC}"
	@./tests/test_gateway_lifecycle.sh

test-concurrency:
	@echo -e "${PURPLE}Running gateway concurrency test...${NC}"
	@./tests/test_gateway_concurrency.sh

test-client:
	@echo -e "${PURPLE}Running client commands test...${NC}"
	@./tests/test_client_commands.sh

test-final:
	@echo -e "${PURPLE}Running the final, streamlined test suite...${NC}"
	@./tests/test_suite_final.sh

# ======================================================================================
#                              SANITIZATION & PRUNING
# ======================================================================================

clean:
	@echo -e "${RED}DANGER: Obliterating all Chimera containers, networks, and volumes...${NC}"
	@echo -e "${YELLOW}First, attempting to remove any orphaned worker containers...${NC}"
	-@for id in $(docker ps -a -q --filter "label=ollama-worker"); do docker stop $id && docker rm -f $id; done
	@echo -e "${YELLOW}Now, taking down the main stack...${NC}"
	@$(COMPOSE) down -v --remove-orphans


prune:
	@echo -e "${RED}DANGER: This will remove all unused Docker assets on the host system.${NC}"
	@read -p "Are you sure you want to continue? (y/N) " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		echo -e "\n${RED}Pruning host system...${NC}"; \
		docker system prune -af --volumes; \
		docker builder prune -af; \
		echo -e "${GREEN}System prune complete.${NC}"; \
	else \
		echo -e "\n${YELLOW}Prune cancelled.${NC}"; \
	fi

.PHONY: help up down stop start restart re build status logs ssh test test-all test-lifecycle test-concurrency test-client test-final clean prune
