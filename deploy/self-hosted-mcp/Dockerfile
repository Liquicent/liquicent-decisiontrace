# DecisionTrace self-hosted MCP server. Build from the repository root:
#   docker build -f deploy/self-hosted-mcp/Dockerfile -t decisiontrace-mcp .
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 dt && mkdir -p /data && chown dt /data
COPY . /src
RUN pip install --no-cache-dir /src && rm -rf /src

USER dt
ENV DT_HOME=/data
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=3s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2)"

# DT_MCP_TOKEN must be set (docker run -e / compose .env); the server refuses to start without it.
CMD ["dt", "mcp", "--http", "--host", "0.0.0.0", "--port", "8765"]
