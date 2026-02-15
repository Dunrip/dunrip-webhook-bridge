.PHONY: setup wizard up smoke down

setup:
	./scripts/bootstrap.sh

wizard:
	python3 ./scripts/setup-wizard.py

up:
	docker compose up -d

smoke:
	./scripts/smoke-test.sh

down:
	docker compose down
