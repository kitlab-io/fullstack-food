compose := "docker compose -f deploy/compose/base.yaml -f deploy/compose/mock.yaml"

# List available tasks
default:
    @just --list

# Lint (same as CI)
lint:
    uv run ruff check .

# Validate the catalog and the example sites against the schemas
validate *sites:
    uv run python -m fsf_core validate {{sites}}

# Unit, contract and scenario tests (the mock system on a virtual clock)
test *args:
    uv run pytest {{args}}

# Run a simulated site against a real MQTT broker: just mock mushrooms 600
mock site="houseplants" speed="120":
    FSF_SITE={{site}} FSF_SPEED={{speed}} {{compose}} up --build

# Stop the mock stack
mock-down:
    {{compose}} down

# Watch every MQTT message of the running mock stack
mock-watch:
    {{compose}} exec broker mosquitto_sub -t 'fsf/#' -v

# Scan the working tree for secrets (needs gitleaks installed)
secrets-scan:
    gitleaks dir .
