FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY cineforge ./cineforge
COPY workflows ./workflows
RUN pip install --no-cache-dir -e . && playwright install --with-deps chromium
CMD ["cineforge-mcp"]
