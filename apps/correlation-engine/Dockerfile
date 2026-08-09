FROM python:3.12-slim AS base

WORKDIR /srv

COPY packages/schemas /srv/packages/schemas
COPY packages/redaction /srv/packages/redaction
COPY apps/correlation-engine/requirements.txt /srv/apps/correlation-engine/requirements.txt

WORKDIR /srv/apps/correlation-engine
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/correlation-engine/app /srv/apps/correlation-engine/app

WORKDIR /srv/apps/correlation-engine

ENV PYTHONUNBUFFERED=1
EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8002/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
