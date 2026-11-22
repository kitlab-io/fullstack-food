# List available tasks
default:
    @just --list

# Lint (same as CI)
lint:
    uv run ruff check .

# Run tests
test:
    uv run pytest

# Scan the working tree for secrets (needs gitleaks installed)
secrets-scan:
    gitleaks dir .
