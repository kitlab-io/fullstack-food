# One image for the hub, the simulator and the dashboard. Build from the repo root:
#   docker build -f deploy/Dockerfile -t fullstack-food .
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY packages/web/frontend/package.json packages/web/frontend/package-lock.json ./
RUN npm ci
COPY packages/web/frontend ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY packages packages
RUN pip install --no-cache-dir ".[web]" && useradd --system --create-home fsf && mkdir /data && chown fsf /data
COPY --from=frontend /frontend/dist packages/web/frontend/dist
COPY schemas schemas
COPY catalog catalog
COPY sites/examples sites/examples
USER fsf
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "fsf_core", "validate"]
