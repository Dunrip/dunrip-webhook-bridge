.PHONY: setup wizard up smoke test-github first-run doctor down release benchmark benchmark-baseline benchmark-compare post-release-verify

COMPOSE_FILE ?= deploy/docker-compose.yml
PROJECT_DIR ?= .
COMPOSE ?= docker compose --project-directory $(PROJECT_DIR) -f $(COMPOSE_FILE)

setup:
	./scripts/bootstrap.sh

wizard:
	python3 ./scripts/setup-wizard.py

up:
	$(COMPOSE) up -d

smoke:
	./scripts/smoke-test.sh

test-github:
	./scripts/test-github.sh

first-run: wizard up smoke

doctor:
	./scripts/doctor.sh

down:
	$(COMPOSE) down

release:
	VERSION=$(VERSION) ./scripts/release.sh

benchmark:
	PYTHONPATH=. .venv/bin/python scripts/benchmark_local.py --iterations $${ITERATIONS:-100}

benchmark-baseline:
	PYTHONPATH=. .venv/bin/python scripts/benchmark_local.py --iterations $${ITERATIONS:-100} --baseline-out $${BASELINE:-.benchmarks/local-baseline.json}

benchmark-compare:
	PYTHONPATH=. .venv/bin/python scripts/benchmark_local.py --iterations $${ITERATIONS:-100} --compare-baseline $${BASELINE:-.benchmarks/local-baseline.json} --max-p95-regression-pct $${MAX_P95_REGRESSION_PCT:-20} --max-error-rate-regression-abs $${MAX_ERROR_RATE_REGRESSION_ABS:-0.01}

post-release-verify:
	./scripts/post-release-verify.sh
