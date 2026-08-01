FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends chromium chromium-sandbox nodejs npm \
    && npm install -g @mermaid-js/mermaid-cli@11.12.0 \
    && useradd --system --no-create-home --shell /usr/sbin/nologin hydrawiki-renderer \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
COPY hydrawiki ./hydrawiki
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "hydrawiki.api:app", "--host", "0.0.0.0", "--port", "8000"]
