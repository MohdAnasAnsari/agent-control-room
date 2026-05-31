# ─────────────────────────────────────────────────────────────────────────────
# Multi-Agent Orchestrator — Developer Makefile
# Usage: make <target>
# Run `make help` for a full list of targets.
# ─────────────────────────────────────────────────────────────────────────────

SHELL := /bin/bash
.DEFAULT_GOAL := help

# ── Configuration ─────────────────────────────────────────────────────────────
REGISTRY       ?= your-registry
BACKEND_IMAGE  := $(REGISTRY)/orchestrator-backend
FRONTEND_IMAGE := $(REGISTRY)/orchestrator-frontend
GIT_SHA        := $(shell git rev-parse --short HEAD 2>/dev/null || echo "dev")
K8S_NAMESPACE  := orchestrator
COMPOSE_FILE   := docker-compose.yml

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
RESET  := \033[0m

.PHONY: help \
	test test-backend test-frontend test-watch e2e \
	lint lint-fix lint-backend lint-frontend \
	security security-backend security-frontend \
	build build-backend build-frontend push push-backend push-frontend \
	up up-build down restart logs logs-backend logs-frontend shell-backend shell-db \
	migrate migrate-rollback migrate-status migrate-new \
	deploy deploy-canary deploy-blue-green rollback rollback-to status smoke-test \
	pre-deploy-check post-deploy-verify \
	tf-init tf-plan tf-apply tf-destroy tf-output \
	dr-status dr-test dr-execute \
	clean clean-docker clean-all

# ─────────────────────────────────────────────────────────────────────────────
# HELP
# ─────────────────────────────────────────────────────────────────────────────
help: ## Show this help message
	@echo ""
	@echo "Multi-Agent Orchestrator — make targets"
	@echo "────────────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-22s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
# TESTING
# ─────────────────────────────────────────────────────────────────────────────
test: test-backend test-frontend ## Run all tests (backend + frontend)

test-backend: ## Run backend tests with coverage (≥80% required)
	@echo "$(YELLOW)Running backend tests...$(RESET)"
	cd backend && pytest tests/ \
		--cov=app \
		--cov-report=term-missing \
		--cov-fail-under=80 \
		-v \
		--tb=short

test-frontend: ## Run frontend tests with coverage
	@echo "$(YELLOW)Running frontend tests...$(RESET)"
	cd frontend && npm run test:ci

test-watch: ## Run frontend tests in watch mode
	cd frontend && npm run test:watch

test-backend-watch: ## Run backend tests in watch mode (ptw)
	cd backend && pip install pytest-watch --quiet && ptw tests/

e2e: ## Run end-to-end Playwright tests (requires running stack)
	@echo "$(YELLOW)Running E2E tests...$(RESET)"
	cd e2e && npx playwright test

e2e-ui: ## Open Playwright UI mode
	cd e2e && npx playwright test --ui

e2e-report: ## Show last Playwright HTML report
	cd e2e && npx playwright show-report

# ─────────────────────────────────────────────────────────────────────────────
# LINT & FORMAT
# ─────────────────────────────────────────────────────────────────────────────
lint: lint-backend lint-frontend ## Run all linters

lint-backend: ## Run flake8 + black check on backend
	@echo "$(YELLOW)Linting backend...$(RESET)"
	cd backend && flake8 app/ tests/ --max-line-length=100 --extend-ignore=E203,W503
	cd backend && black --check --diff app/ tests/

lint-frontend: ## Run ESLint on frontend
	@echo "$(YELLOW)Linting frontend...$(RESET)"
	cd frontend && npm run lint

lint-fix: ## Auto-fix formatting (black + eslint --fix)
	@echo "$(YELLOW)Fixing formatting...$(RESET)"
	cd backend && black app/ tests/
	cd frontend && npm run lint -- --fix

# ─────────────────────────────────────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────────────────────────────────────
security: security-backend security-frontend ## Run all security scans

security-backend: ## bandit Python security analysis
	@echo "$(YELLOW)Running bandit...$(RESET)"
	cd backend && bandit -r app/ --severity-level medium --confidence-level medium

security-frontend: ## npm audit for high/critical vulnerabilities
	@echo "$(YELLOW)Running npm audit...$(RESET)"
	cd frontend && npm audit --audit-level=high

# ─────────────────────────────────────────────────────────────────────────────
# DOCKER — LOCAL DEVELOPMENT
# ─────────────────────────────────────────────────────────────────────────────
up: ## Start all services in the background (docker compose)
	@echo "$(GREEN)Starting services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) up -d
	@echo ""
	@echo "  Frontend  → http://localhost:3000"
	@echo "  Backend   → http://localhost:8000"
	@echo "  API docs  → http://localhost:8000/docs"
	@echo "  Adminer   → http://localhost:8080"

up-build: ## Rebuild images and start all services
	@echo "$(GREEN)Rebuilding and starting services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) up -d --build

down: ## Stop and remove containers
	@echo "$(RED)Stopping services...$(RESET)"
	docker compose -f $(COMPOSE_FILE) down

restart: ## Restart a single service (usage: make restart svc=backend)
	docker compose -f $(COMPOSE_FILE) restart $(svc)

logs: ## Follow logs for all services
	docker compose -f $(COMPOSE_FILE) logs -f

logs-backend: ## Follow backend service logs
	docker compose -f $(COMPOSE_FILE) logs -f backend

logs-frontend: ## Follow frontend service logs
	docker compose -f $(COMPOSE_FILE) logs -f frontend

shell-backend: ## Open a shell inside the running backend container
	docker compose -f $(COMPOSE_FILE) exec backend bash

shell-db: ## Open psql inside the running postgres container
	docker compose -f $(COMPOSE_FILE) exec postgres \
		psql -U orchestrator -d orchestrator_dev

# ─────────────────────────────────────────────────────────────────────────────
# DOCKER — BUILD & PUSH
# ─────────────────────────────────────────────────────────────────────────────
build: build-backend build-frontend ## Build all Docker images

build-backend: ## Build backend Docker image
	@echo "$(YELLOW)Building backend image ($(GIT_SHA))...$(RESET)"
	docker build \
		-t $(BACKEND_IMAGE):$(GIT_SHA) \
		-t $(BACKEND_IMAGE):latest \
		./backend

build-frontend: ## Build frontend Docker image
	@echo "$(YELLOW)Building frontend image ($(GIT_SHA))...$(RESET)"
	docker build \
		-t $(FRONTEND_IMAGE):$(GIT_SHA) \
		-t $(FRONTEND_IMAGE):latest \
		./frontend

push: push-backend push-frontend ## Push all images to the registry

push-backend: ## Push backend image to registry
	docker push $(BACKEND_IMAGE):$(GIT_SHA)
	docker push $(BACKEND_IMAGE):latest

push-frontend: ## Push frontend image to registry
	docker push $(FRONTEND_IMAGE):$(GIT_SHA)
	docker push $(FRONTEND_IMAGE):latest

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE MIGRATIONS
# ─────────────────────────────────────────────────────────────────────────────
migrate: ## Run pending Alembic migrations (upgrade head)
	@echo "$(YELLOW)Running migrations...$(RESET)"
	cd backend && alembic upgrade head

migrate-rollback: ## Roll back the last migration
	@echo "$(RED)Rolling back last migration...$(RESET)"
	cd backend && alembic downgrade -1

migrate-status: ## Show current migration revision
	cd backend && alembic current

migrate-history: ## Show full migration history
	cd backend && alembic history --verbose

migrate-new: ## Create a new migration (usage: make migrate-new msg="add foo column")
	@[ -n "$(msg)" ] || (echo "Usage: make migrate-new msg='description'" && exit 1)
	cd backend && alembic revision --autogenerate -m "$(msg)"

# ─────────────────────────────────────────────────────────────────────────────
# KUBERNETES — PRODUCTION
# ─────────────────────────────────────────────────────────────────────────────
deploy: ## Deploy latest images to Kubernetes (kubeconfig required)
	@echo "$(GREEN)Deploying to Kubernetes (namespace: $(K8S_NAMESPACE))...$(RESET)"
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/deployment.yaml
	kubectl apply -f k8s/service.yaml
	kubectl rollout status deployment/orchestrator-backend \
		-n $(K8S_NAMESPACE) \
		--timeout=300s
	@echo "$(GREEN)Deploy complete.$(RESET)"

rollback: ## Roll back the last Kubernetes deployment
	@echo "$(RED)Rolling back orchestrator-backend...$(RESET)"
	kubectl rollout undo deployment/orchestrator-backend -n $(K8S_NAMESPACE)
	kubectl rollout status deployment/orchestrator-backend \
		-n $(K8S_NAMESPACE) \
		--timeout=180s
	@$(MAKE) smoke-test

status: ## Show Kubernetes pod, service, and deployment status
	@echo "── Pods ────────────────────────────────────────"
	kubectl get pods -n $(K8S_NAMESPACE) -o wide
	@echo ""
	@echo "── Deployments ─────────────────────────────────"
	kubectl get deployments -n $(K8S_NAMESPACE)
	@echo ""
	@echo "── Services ────────────────────────────────────"
	kubectl get svc -n $(K8S_NAMESPACE)

smoke-test: ## Quick /health check against the production service
	@echo "$(YELLOW)Running smoke test...$(RESET)"
	@HOSTNAME=$$(kubectl get svc orchestrator-backend -n $(K8S_NAMESPACE) \
		-o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null); \
	if [ -z "$$HOSTNAME" ]; then \
		echo "$(RED)Could not resolve service hostname — is kubeconfig configured?$(RESET)"; \
		exit 1; \
	fi; \
	URL="http://$$HOSTNAME"; \
	echo "Testing $$URL/health ..."; \
	RESPONSE=$$(curl -s -o /dev/null -w "%{http_code}" "$$URL/health"); \
	if [ "$$RESPONSE" = "200" ]; then \
		echo "$(GREEN)✓ /health OK (200)$(RESET)"; \
	else \
		echo "$(RED)✗ /health returned $$RESPONSE$(RESET)"; \
		exit 1; \
	fi

k8s-logs: ## Tail backend pod logs in production
	kubectl logs -f -l app=orchestrator-backend -n $(K8S_NAMESPACE) --tail=100

k8s-shell: ## Open a shell in a production backend pod (read-only)
	kubectl exec -it \
		$$(kubectl get pod -l app=orchestrator-backend -n $(K8S_NAMESPACE) \
			-o jsonpath='{.items[0].metadata.name}') \
		-n $(K8S_NAMESPACE) -- /bin/sh

# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────────────────
clean: ## Remove Python and Node build artefacts
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -name "*.pyc" -delete 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/coverage-html backend/coverage.xml
	rm -rf frontend/dist frontend/coverage

clean-docker: ## Remove stopped containers and dangling images
	docker compose -f $(COMPOSE_FILE) down -v --remove-orphans
	docker image prune -f

clean-all: clean clean-docker ## Remove all build artefacts and Docker resources
	rm -rf frontend/node_modules
	@echo "$(GREEN)Clean complete.$(RESET)"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5.4 — PRODUCTION DEPLOYMENT
# ─────────────────────────────────────────────────────────────────────────────
pre-deploy-check: ## Run pre-deployment checklist (all gates must pass)
	@echo "$(YELLOW)Running pre-deployment checklist...$(RESET)"
	bash scripts/pre-deploy-check.sh --env production

deploy-full: ## Full production deploy with pre-checks, rolling update, and smoke tests
	@echo "$(GREEN)Starting full production deployment...$(RESET)"
	bash deploy.sh --env production --image-tag $(GIT_SHA)

deploy-canary: ## Deploy as canary at 10% of instances
	@[ -n "$(percent)" ] || (echo "Usage: make deploy-canary percent=10" && exit 1)
	bash deploy.sh --env production --image-tag $(GIT_SHA) --canary $(percent)

deploy-blue-green: ## Blue/green deployment (zero-downtime)
	bash deploy.sh --env production --image-tag $(GIT_SHA) --blue-green

rollback-to: ## Roll back to a specific revision (usage: make rollback-to rev=5)
	@[ -n "$(rev)" ] || (echo "Usage: make rollback-to rev=5" && exit 1)
	bash scripts/rollback.sh --revision $(rev)

post-deploy-verify: ## Run post-deployment verification against production
	@HOSTNAME=$$(kubectl get svc orchestrator-backend -n $(K8S_NAMESPACE) \
		-o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null); \
	bash scripts/post-deploy-verify.sh "http://$$HOSTNAME"

# ─────────────────────────────────────────────────────────────────────────────
# TERRAFORM — INFRASTRUCTURE AS CODE
# ─────────────────────────────────────────────────────────────────────────────
tf-init: ## Initialize Terraform (run once per environment)
	@echo "$(YELLOW)Initializing Terraform...$(RESET)"
	cd terraform && terraform init

tf-plan: ## Preview Terraform changes (production)
	cd terraform && terraform plan -var-file=production.tfvars

tf-plan-staging: ## Preview Terraform changes (staging)
	cd terraform && terraform plan -var-file=staging.tfvars

tf-apply: ## Apply Terraform changes (production) — prompts for confirmation
	@echo "$(RED)Applying infrastructure changes to PRODUCTION...$(RESET)"
	cd terraform && terraform apply -var-file=production.tfvars

tf-apply-staging: ## Apply Terraform changes (staging)
	cd terraform && terraform apply -var-file=staging.tfvars

tf-output: ## Show all Terraform outputs (connection strings, cluster names)
	cd terraform && terraform output

tf-destroy: ## DANGER: Destroy all infrastructure — prompts for confirmation
	@echo "$(RED)WARNING: This will destroy ALL infrastructure!$(RESET)"
	@read -p "Type 'destroy' to confirm: " c && [ "$$c" = "destroy" ]
	cd terraform && terraform destroy -var-file=production.tfvars

# ─────────────────────────────────────────────────────────────────────────────
# DISASTER RECOVERY
# ─────────────────────────────────────────────────────────────────────────────
dr-status: ## Check disaster recovery readiness
	bash scripts/disaster-recovery.sh status

dr-test: ## Run non-destructive DR drill (quarterly)
	bash scripts/disaster-recovery.sh test

dr-execute: ## Execute actual DR recovery (DANGER: modifies production)
	bash scripts/disaster-recovery.sh execute --confirm
