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

# Run scenario files or all scenarios of a site: just scenario sites/examples/mushrooms --serve
scenario *args:
    uv run fsf scenario run {{args}}

# Run a simulated site against a real MQTT broker: just mock mushrooms 600
mock site="houseplants" speed="120":
    FSF_SITE={{site}} FSF_SPEED={{speed}} {{compose}} up --build

# Stop the mock stack
mock-down:
    {{compose}} down

# Watch every MQTT message of the running mock stack
mock-watch:
    {{compose}} exec broker mosquitto_sub -t 'fsf/#' -v

# Write one ESPHome config per node into build/firmware/<site>: just firmware sites/local/my-site
firmware site *args:
    uv run fsf firmware build {{site}} {{args}}

# BOM, wiring diagrams, build guide, checklist and LED legend into build/docs/<site>
docs site *args:
    uv run fsf docs build {{site}} {{args}}

# Health check of a running installation: just doctor --site sites/local/my-site --db hub.db
doctor *args:
    uv run fsf doctor {{args}}

# Run the node contract suite against a broker: just node-test shelf-node --site sites/local/my-site --actuate
node-test node *args:
    uv run fsf node test {{node}} {{args}}

# Build the dashboard frontend into packages/web/frontend/dist (needs Node.js)
web-build:
    cd packages/web/frontend && npm ci && npm run build

# Serve the dashboard for a site: just web sites/examples/houseplants --db hub.db
web site *args:
    uv run python -m fsf_web --site {{site}} {{args}}

# Scan the working tree for secrets (needs gitleaks installed)
secrets-scan:
    gitleaks dir .
