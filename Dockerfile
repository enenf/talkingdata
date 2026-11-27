FROM node:22-bookworm-slim
ARG CODEX_VERSION=0.162.1
RUN apt-get update && apt-get install -y --no-install-recommends python3 git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex@${CODEX_VERSION} \
    && npm cache clean --force
WORKDIR /app
COPY --chown=node:node server.py agent.py transport.py ./
COPY --chown=node:node static ./static
RUN mkdir -p /data && chown node:node /data
USER node
ENV APP_HOST=0.0.0.0 APP_PORT=8080 DATA_DIR=/data RUN_IN_CONTAINER=1 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)" || exit 1
CMD ["python3", "server.py"]
