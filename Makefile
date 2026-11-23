.PHONY: test-node-sdk test-e2e test-gateway run-gateway test-llm infra-up infra-down infra-logs migrate migrate-status test-db test-schemas test-redaction test-ingestion test-correlation test-reasoning test-alerts test-all run-ingestion run-correlation run-reasoning run-alerts run-dashboard

infra-up:
	docker compose -f infra/docker/docker-compose.yml up -d

infra-down:
	docker compose -f infra/docker/docker-compose.yml down

infra-logs:
	docker compose -f infra/docker/docker-compose.yml logs -f

migrate:
	cd packages/db/src && python migrate.py up

migrate-status:
	cd packages/db/src && python migrate.py status

test-db:
	cd packages/db && pytest -v

test-schemas:
	cd packages/schemas && pytest -v

test-redaction:
	cd packages/redaction && pytest -v

test-ingestion:
	cd apps/ingestion-service && pytest -v

test-correlation:
	cd apps/correlation-engine && pytest -v

test-reasoning:
	cd apps/reasoning-service && pytest -v

test-alerts:
	cd apps/alert-router && pytest -v

run-ingestion:
	cd apps/ingestion-service && uvicorn app.main:app --reload --port 8001

run-correlation:
	cd apps/correlation-engine && uvicorn app.main:app --reload --port 8002

run-reasoning:
	cd apps/reasoning-service && uvicorn app.main:app --reload --port 8003

run-alerts:
	cd apps/alert-router && uvicorn app.main:app --reload --port 8004

run-dashboard:
	cd apps/dashboard && npm run dev

test-all: test-node-sdk test-gateway test-llm test-db test-schemas test-redaction test-ingestion test-correlation test-reasoning test-alerts
	@echo "All tests passed."

test-llm:
	cd packages/llm && pytest -v

test-e2e:
	cd tests/e2e && TEST_DATABASE_URL=$$TEST_DATABASE_URL pytest -v   # needs Postgres; runs gateway + ingestion locally

test-gateway:
	cd apps/api-gateway && pytest -v   # set TEST_DATABASE_URL to run the integration tests

run-gateway:
	cd apps/api-gateway && uvicorn app.main:app --reload --port 8005

test-node-sdk:
	cd packages/node-sdk && npm test
