# Compile the shared React UI from locked, tracked inputs. Node never enters runtime.
FROM node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5 AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Linux amd64/arm64 CPython 3.14.7; multi-platform digest and wheel hashes stay pinned.
FROM python:3.14.7-slim-bookworm@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HEETKIT_DATA_DIR=/var/lib/heetkit \
    HOME=/nonexistent
WORKDIR /opt/heetkit
COPY packaging/python-bootstrap.txt /opt/heetkit/python-bootstrap.txt
COPY packaging/linux/requirements.txt /opt/heetkit/requirements.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check --only-binary=:all: --require-hashes -r python-bootstrap.txt \
    && python -m pip install --no-cache-dir --disable-pip-version-check --only-binary=:all: --require-hashes -r requirements.txt \
    && python -m pip check \
    && groupadd --gid 10001 heetkit \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin heetkit \
    && mkdir -p /var/lib/heetkit \
    && chown 10001:10001 /var/lib/heetkit \
    && chmod 0700 /var/lib/heetkit
COPY app/ ./app/
COPY --from=frontend /frontend/dist/ ./app/resources/frontend/
COPY LICENSE NOTICE ./licenses/
USER 10001:10001
VOLUME ["/var/lib/heetkit"]
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=10s --timeout=3s --start-period=75s --retries=3 \
    CMD ["python", "-m", "app.headless_health"]
ENTRYPOINT ["python", "-m", "app.headless"]
CMD ["--health-file", "/tmp/heetkit-health.json"]
