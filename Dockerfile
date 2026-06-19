# syntax=docker/dockerfile:1
# Build for linux/amd64 (DGX Spark). On Apple Silicon:
#   docker buildx build --platform linux/amd64 -t ghcr.io/ybordag/rhizome:latest .

FROM --platform=linux/amd64 python:3.12-slim

WORKDIR /app

# System libs needed for psycopg2 (Postgres driver)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps before copying source (better layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root
RUN useradd --no-create-home --shell /bin/false rhizome
USER rhizome

EXPOSE 8001
CMD ["python", "server.py"]
