# ContextLib: the ctxlib CLI and MCP server over a library you mount at /library.
#   MCP (stdio):  docker run -i --rm --user "$(id -u):$(id -g)" -v ~/ContextLib:/library \
#                   ghcr.io/willykeenan/agentbrain-contextlib mcp --identity you
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && mkdir -p /library && chmod 777 /library
ENV CONTEXTLIB_ROOT=/library HOME=/tmp
VOLUME ["/library"]
ENTRYPOINT ["ctxlib"]
CMD ["--help"]
