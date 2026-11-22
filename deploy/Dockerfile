# One image for the hub and the simulator. Build from the repo root:
#   docker build -f deploy/Dockerfile -t fullstack-food .
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY packages packages
RUN pip install --no-cache-dir . && useradd --system --create-home fsf && mkdir /data && chown fsf /data
COPY schemas schemas
COPY catalog catalog
COPY sites/examples sites/examples
USER fsf
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "fsf_core", "validate"]
