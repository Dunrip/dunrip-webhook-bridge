.PHONY: setup wizard up smoke test-github first-run doctor down release

setup:
	./scripts/bootstrap.sh

wizard:
	python3 ./scripts/setup-wizard.py

up:
	docker compose up -d

smoke:
	./scripts/smoke-test.sh

test-github:
	./scripts/test-github.sh

first-run: wizard up smoke

doctor:
	./scripts/doctor.sh

down:
	docker compose down

release:
	VERSION=$(VERSION) ./scripts/release.sh
