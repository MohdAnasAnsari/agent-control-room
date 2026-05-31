# ── Stage 1: builder ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Build-time deps only (gcc for asyncpg C extension, libpq-dev for pg client headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into an isolated venv so it can be copied cleanly to the runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Carry the venv across; no build tools in the final image
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# curl for health-check probes; libpq5 is the asyncpg runtime dep
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Dedicated non-root user (uid/gid 999 matches K8s securityContext)
RUN groupadd -r -g 999 appuser \
    && useradd -r -u 999 -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

COPY --chown=appuser:appuser . .

RUN chmod +x /app/entrypoint.sh

USER appuser

EXPOSE 8000

# 10s interval; give the app 30s to start before the first probe
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
