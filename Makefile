# Substrate — Omni Indie Hacker Control Plane
# Makefile for scaffolding, booting, and managing the "Motherboard"

SERVICES_DIR := services
INFRA_DIR    := infra
COMPOSE_CMD  := docker compose

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-25s\033[0m %s\n", $$1, $$2}'

# ─── Scaffolding ─────────────────────────────────────────────────────────────

boiler-lab: ## Scaffold a new microservice: make boiler-lab NAME=api_gateway
	@if [ -z "$(NAME)" ]; then echo "Usage: make boiler-lab NAME=<service_name>"; exit 1; fi
	@echo "→ Scaffolding service: $(NAME)"
	@mkdir -p $(SERVICES_DIR)/$(NAME)/{config,volumes/data,app}
	@touch $(SERVICES_DIR)/$(NAME)/config/.gitkeep
	@touch $(SERVICES_DIR)/$(NAME)/volumes/data/.gitkeep
	@if [ ! -f $(SERVICES_DIR)/$(NAME)/Dockerfile ]; then \
		echo "FROM python:3.12-slim" > $(SERVICES_DIR)/$(NAME)/Dockerfile; \
		echo "" >> $(SERVICES_DIR)/$(NAME)/Dockerfile; \
		echo "WORKDIR /app" >> $(SERVICES_DIR)/$(NAME)/Dockerfile; \
		echo "COPY app/ ." >> $(SERVICES_DIR)/$(NAME)/Dockerfile; \
		echo "RUN pip install -r requirements.txt" >> $(SERVICES_DIR)/$(NAME)/Dockerfile; \
		echo "CMD [\"python\", \"main.py\"]" >> $(SERVICES_DIR)/$(NAME)/Dockerfile; \
	fi
	@if [ ! -f $(SERVICES_DIR)/$(NAME)/docker-compose.yml ]; then \
		echo "version: \"3.8\"" > $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "services:" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "  $(NAME):" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "    build: ." >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "    ports:" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo '      - "8000"' >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "    volumes:" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "      - ./config:/app/config:ro" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "      - ./volumes/data:/app/data" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "    env_file:" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
		echo "      - ../../.env" >> $(SERVICES_DIR)/$(NAME)/docker-compose.yml; \
	fi
	@if [ ! -f $(SERVICES_DIR)/$(NAME)/requirements.txt ]; then \
		echo "fastapi" > $(SERVICES_DIR)/$(NAME)/requirements.txt; \
		echo "uvicorn" >> $(SERVICES_DIR)/$(NAME)/requirements.txt; \
		echo "pydantic" >> $(SERVICES_DIR)/$(NAME)/requirements.txt; \
	fi
	@if [ ! -f $(SERVICES_DIR)/$(NAME)/app/main.py ]; then \
		echo '"""$(NAME) — Substrate service"""' > $(SERVICES_DIR)/$(NAME)/app/main.py; \
		echo "def main():" >> $(SERVICES_DIR)/$(NAME)/app/main.py; \
		echo '    print("$(NAME) service starting...")' >> $(SERVICES_DIR)/$(NAME)/app/main.py; \
		echo "" >> $(SERVICES_DIR)/$(NAME)/app/main.py; \
		echo 'if __name__ == "__main__":' >> $(SERVICES_DIR)/$(NAME)/app/main.py; \
		echo "    main()" >> $(SERVICES_DIR)/$(NAME)/app/main.py; \
	fi
	@echo "✓ Service $(NAME) scaffolded at $(SERVICES_DIR)/$(NAME)/"

scaffold-dirs: ## Create all top-level manifest and config directories
	@echo "→ Creating manifest directories..."
	@mkdir -p manifests/agents/{scribe,recon,sentinel,broker}/{system-prompts,tools}
	@mkdir -p manifests/agents/scribe/tools/mdx_writer/scripts
	@mkdir -p manifests/agents/recon/tools/playwright_scraper
	@mkdir -p manifests/agents/sentinel/tools/health_ping
	@mkdir -p manifests/agents/broker/tools/stripe_client
	@mkdir -p manifests/relics/{content_vault,ledger_db,recon_graph,metrics_store}/app
	@mkdir -p manifests/workflows
	@mkdir -p manifests/monuments/{content_engine,devops_monitor,financial_hub}
	@mkdir -p std/manifests/tools/{web_search,fs_read,json_parser}
	@mkdir -p std/manifests/relics/generic_kv_store
	@mkdir -p clients/{webui,tui_lab,android_app}
	@mkdir -p scripts
	@mkdir -p infra/nginx/conf.d
	@mkdir -p infra/env
	@echo "✓ Directory scaffold complete"

scaffold-initial-files: ## Touch placeholder files for manifests and config
	@echo "→ Creating initial files..."
	@touch manifests/agents/scribe/agent.yml
	@touch manifests/agents/scribe/system-prompts/scribe.md
	@touch manifests/agents/scribe/tools/mdx_writer/tool.yml
	@touch manifests/agents/scribe/tools/mdx_writer/scripts/writer.py
	@touch manifests/agents/recon/agent.yml manifests/agents/recon/system-prompts/recon.md
	@touch manifests/agents/sentinel/agent.yml manifests/agents/sentinel/system-prompts/sentinel.md
	@touch manifests/agents/broker/agent.yml manifests/agents/broker/system-prompts/broker.md
	@touch manifests/relics/content_vault/relic.yml
	@touch manifests/relics/ledger_db/relic.yml
	@touch manifests/relics/recon_graph/relic.yml
	@touch manifests/relics/metrics_store/relic.yml
	@touch manifests/workflows/seo_content_loop.workflow.yml
	@touch manifests/workflows/weekly_recon_sweep.workflow.yml
	@touch manifests/workflows/incident_response.workflow.yml
	@touch manifests/monuments/content_engine/monument.yml
	@touch manifests/monuments/devops_monitor/monument.yml
	@touch manifests/monuments/financial_hub/monument.yml
	@touch settings.yml autoload.yml
	@touch infra/docker-compose.core.yml
	@touch infra/nginx/nginx.conf
	@echo "✓ Initial files created"

scaffold-all: scaffold-dirs scaffold-initial-files ## Run all scaffolding (dirs + initial files)
	@echo "✓ Full scaffold complete"

# ─── Service Management ──────────────────────────────────────────────────────

up: ## Boot all core services (docker compose up -d)
	@$(COMPOSE_CMD) -f $(INFRA_DIR)/docker-compose.core.yml up -d

down: ## Stop all core services
	@$(COMPOSE_CMD) -f $(INFRA_DIR)/docker-compose.core.yml down

logs: ## Tail logs from all services
	@$(COMPOSE_CMD) -f $(INFRA_DIR)/docker-compose.core.yml logs -f

ps: ## Show running services
	@$(COMPOSE_CMD) -f $(INFRA_DIR)/docker-compose.core.yml ps

# ─── Development ─────────────────────────────────────────────────────────────

.PHONY: help boiler-lab scaffold-dirs scaffold-initial-files scaffold-all up down logs ps
