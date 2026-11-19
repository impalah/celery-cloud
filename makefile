# Variables
PROFILE="pak"
DOMAIN="celery-cloud"
AWS_REGION="us-east-1"
REGISTRY_URI="public.ecr.aws/e2b2x4l7"
REPOSITORY_NAME="lambda-runner"
PLATFORM="linux/amd64"
BUILDER_NAME="mybuilder"
PART ?= patch  # puede sobrescribirse con: make bump-version PART=minor

.PHONY: venv bump-version build clean publish publish-test docker-build release \
	docker-release lint format type-check security-check check test mutation mutation-report \
	docs docs-serve infra-check

# Delete the virtual environment and force a sync
venv:
	rm -rf .venv && \
	echo "✅ Deleted virtual environment" && \
	uv sync && \
	echo "✅ Created virtual environment" && \
	uvx --from=toml-cli toml get --toml-path=pyproject.toml project.version

# Bump patch/minor/major version (pyproject.toml and uv.lock). Explicit only:
# build/release do NOT bump, nor does the release workflow: bump manually.
bump-version:
	@echo "🔧 Current version: $$(uv version --short)" && \
	uv version --bump $(PART) --no-sync && \
	echo "✅ Version bumped ($(PART)) to $$(uv version --short)"

# Build python package
build:
	uv build

# Clean build artifacts
clean:
	rm -rf dist *.egg-info build && \
	echo "✅ Cleaned build artifacts"

# Publish package on PyPI (use UV_PYPI_TOKEN or .pypirc for authentication)
publish: build
	uv publish

# Publish on TestPyPI
publish-test: build
	uv publish --repository testpypi

# Build docker image
docker-build:
	@BASE_VERSION=$$(uv version --short) && \
	echo "✅ Building version $$BASE_VERSION" && \
	if docker buildx inspect $(BUILDER_NAME) >/dev/null 2>&1; then \
		echo "✅ Builder '$(BUILDER_NAME)' exists. Activating..."; \
		docker buildx use $(BUILDER_NAME); \
	else \
		echo "⚠️  Builder '$(BUILDER_NAME)' not found. Creating..."; \
		docker buildx create --name $(BUILDER_NAME) --use; \
	fi && \
	docker buildx inspect $(BUILDER_NAME) --bootstrap && \
	aws --profile $(PROFILE) ecr-public get-login-password --region $(AWS_REGION) | docker login --username AWS --password-stdin $(REGISTRY_URI) && \
	docker run --rm --privileged multiarch/qemu-user-static --reset -p yes && \
	docker buildx build \
		--provenance=false \
		--progress=plain \
		--platform $(PLATFORM) \
		-t $(REGISTRY_URI)/$(DOMAIN)/$(REPOSITORY_NAME):$$BASE_VERSION \
		-f Dockerfile \
		--push .

# Alias for all the Python package release cycle
release: clean build publish

# Alias for all the Docker image release cycle
docker-release: docker-build

# Development utilities
# Ruff lint (style, imports, common errors)
lint:
	uv run ruff check src

# Sort imports
format:
	uv run ruff format src
	uv run ruff check --fix src

# Typing with mypy
type-check:
	uv run mypy src

# Bandit security scan
security-check:
	uv run bandit -r src

# Full review
check: lint format type-check security-check


# Test execution	
test:
	uv run pytest -v --tb=short --doctest-modules --disable-warnings --maxfail=1 --junitxml=junit.xml --cov-report term-missing --cov-report html:coverage_html_report --cov-report xml:coverage.xml --cov-config=.coveragerc --cov src tests

# Mutation testing (slow, manual: NOT part of `check` nor of the regular CI).
# Mutates the critical modules (see [tool.mutmut] in pyproject.toml) and reports
# the mutants that no test detects.
mutation:
	uv run mutmut run

# Show the surviving mutants of the last run (`uv run mutmut show <name>` for the diff)
mutation-report:
	uv run mutmut results

# Documentation (Sphinx): sources in pages_source/, HTML in docs/ (GitHub Pages).
# Warnings are errors, as in the CI.
docs:
	rm -rf docs
	uv run --group docs sphinx-build -W --keep-going -d pages_source/_build/.doctrees pages_source docs

# Serve the built site on http://localhost:8000
docs-serve: docs
	uv run python -m http.server 8000 --directory docs

# Terraform (infra/terraform): fmt, validate and mocked-provider tests, no credentials needed
infra-check:
	./infra/terraform/check.sh
