FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
RUN python -m venv /opt/venv

COPY pyproject.toml README.md ./
COPY ciclorota ./ciclorota
RUN /opt/venv/bin/pip install .

FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system ciclorota \
    && useradd --system --gid ciclorota --home-dir /app --no-create-home ciclorota \
    && mkdir -p /app/data \
    && chown -R ciclorota:ciclorota /app

COPY --from=builder --chown=ciclorota:ciclorota /opt/venv /opt/venv
COPY --chown=ciclorota:ciclorota ciclorota ./ciclorota

USER ciclorota
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).read()" || exit 1

CMD ["uvicorn", "ciclorota.api:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
