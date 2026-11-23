# SKELETON: never built. Build from the repository root so the packages are in the context:
#   docker build -f deploy/haos/fullstack-food/Dockerfile --build-arg BUILD_FROM=ghcr.io/home-assistant/aarch64-base-python:3.12-alpine3.20 .
ARG BUILD_FROM
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY packages/web/frontend/package.json packages/web/frontend/package-lock.json ./
RUN npm ci
COPY packages/web/frontend ./
RUN npm run build

FROM ${BUILD_FROM}
WORKDIR /app
COPY pyproject.toml README.md ./
COPY packages packages
RUN pip install --no-cache-dir ".[web]"
COPY --from=frontend /frontend/dist packages/web/frontend/dist
COPY schemas schemas
COPY catalog catalog
COPY deploy/haos/fullstack-food/run.sh /run.sh
RUN chmod a+x /run.sh
CMD ["/run.sh"]
