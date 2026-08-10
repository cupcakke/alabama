FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_ROOT=/app

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The Markdown files are part of the data source and are copied into the image.
COPY . .

RUN useradd --create-home --uid 10001 mcpuser \
    && chown -R mcpuser:mcpuser /app
USER mcpuser

EXPOSE 8000

CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
