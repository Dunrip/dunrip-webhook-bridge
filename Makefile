.PHONY: setup wizard up smoke test-github first-run doctor down release

COMPOSE_FILE ?= deploy/docker-compose.yml
COMPOSE ?= docker compose -f $(COMPOSE_FILE)

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
