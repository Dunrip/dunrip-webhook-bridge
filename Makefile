.PHONY: setup wizard up smoke doctor down

setup:
	./scripts/bootstrap.sh

wizard:
	python3 ./scripts/setup-wizard.py

up:
	docker compose up -d

smoke:
	./scripts/smoke-test.sh

doctor:
	./scripts/doctor.sh

down:
	docker compose down
