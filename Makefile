# AIOps Guardian — every pipeline stage is a make target, so each one can be
# run by hand when debugging. Targets marked "commit N" are placeholders that
# get filled in by that commit of the implementation guide.

SHELL := /bin/bash
.DEFAULT_GOAL := help

DOCKER_USER ?= changeme
TAG         ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo dev)
APP_IMAGE   := $(DOCKER_USER)/booking-api
GUARD_IMAGE := $(DOCKER_USER)/aiops-guardian
# Docker Compose v2 plugin if present, else the standalone binary
COMPOSE     ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose)
DEV_COMPOSE := $(COMPOSE) -f docker-compose.dev.yml --env-file .env

define todo
	@echo "make $@: not implemented yet (added in commit $(1))" >&2; exit 1
endef

.PHONY: help versions \
        dev-up dev-down \
        lint test \
        train \
        images push check-blocked \
        deploy-booking deploy-guardian smoke \
        vault-forward \
        guardian-pause guardian-resume guardian-dry-run guardian-live \
        demo-reset

##@ General

help: ## List all targets
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m [TAG=<sha>] [DOCKER_USER=<user>]\n"} \
		/^[a-zA-Z0-9_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
	@echo

versions: ## Print installed tool versions to compare with the README
	@for c in "python3 --version" "docker --version" "minikube version --short" \
	          "kubectl version --client" "helm version --short" \
	          "ansible --version" "k6 version"; do \
		bin=$${c%% *}; \
		if command -v $$bin >/dev/null 2>&1; then \
			printf "%-10s %s\n" "$$bin" "$$($$c 2>/dev/null | head -n1)"; \
		else \
			printf "%-10s %s\n" "$$bin" "NOT INSTALLED"; \
		fi; \
	done
	@printf "%-10s %s\n" "sklearn" "$$(python3 -c 'import sklearn; print(sklearn.__version__)' 2>/dev/null || echo 'NOT INSTALLED')"

##@ Local development

dev-up: .env ## Start the dev stack (Postgres now; app added in commit 13)
	$(DEV_COMPOSE) up -d --wait

dev-down: ## Stop the dev compose stack (keeps the DB volume)
	$(DEV_COMPOSE) down

.env:
	@echo "No .env found: creating it from .env.example" >&2
	cp .env.example .env

##@ Quality

lint: ## Run ruff over app/ and guardian/ (commit 14)
	$(call todo,14)

test: ## Run unit tests (commit 11)
	$(call todo,11)

##@ Build and release

train: ## Train and gate the ML model (commit 48)
	$(call todo,48)

images: ## Build app and guardian images tagged $(TAG) (commit 15)
	$(call todo,15)

push: ## Push images to Docker Hub (commit 15, creds from Vault in commit 25)
	$(call todo,15)

check-blocked: ## Fail if $(TAG) is in booking/blocked-versions (commit 41)
	$(call todo,41)

##@ Deploy

deploy-booking: ## helm upgrade booking, keeping the live HPA floor (commit 21)
	$(call todo,21)

deploy-guardian: ## helm upgrade the separate guardian release (commit 39)
	$(call todo,39)

smoke: ## Post-deploy smoke test with k6 (commit 32)
	$(call todo,32)

vault-forward: ## Port-forward Vault to localhost:8200 (commit 25)
	$(call todo,25)

##@ Guardian control

guardian-pause: ## Stop all guardian actions within one cycle (commit 44)
	$(call todo,44)

guardian-resume: ## Resume guardian actions (commit 44)
	$(call todo,44)

guardian-dry-run: ## Guardian only logs what it would do (commit 44)
	$(call todo,44)

guardian-live: ## Guardian takes real actions (commit 44)
	$(call todo,44)

##@ Demo

demo-reset: ## Restore a clean demo state in under 2 minutes (commit 51)
	$(call todo,51)
