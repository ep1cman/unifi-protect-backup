sources = unifi_protect_backup
container_name ?= ghcr.io/ep1cman/unifi-protect-backup
container_arches ?= linux/amd64,linux/arm64

.PHONY: test format lint unittest coverage pre-commit clean
test: format lint unittest

format:
	isort $(sources) tests
	black $(sources) tests

lint:
	flake8 $(sources) tests
	mypy $(sources) tests

unittest:
	pytest

coverage:
	pytest --cov=$(sources) --cov-branch --cov-report=term-missing tests

pre-commit:
	pre-commit run --all-files

clean:
	rm -rf .mypy_cache .pytest_cache
	rm -rf *.egg-info
	rm -rf .tox dist site
	rm -rf coverage.xml .coverage

docker:
	poetry build
	docker buildx build . --platform $(container_arches) -t $(container_name) --push
