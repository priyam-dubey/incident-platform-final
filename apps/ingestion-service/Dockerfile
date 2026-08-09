FROM python:3.12-slim AS base

WORKDIR /srv

# Copy the shared schemas package first since requirements.txt installs it
# from a relative file path - build context must include packages/schemas.
COPY packages/schemas /srv/packages/schemas
COPY apps/ingestion-service/requirements.txt /srv/apps/ingestion-service/requirements.txt

WORKDIR /srv/apps/ingestion-service
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/ingestion-service/app /srv/apps/ingestion-service/app

WORKDIR /srv/apps/ingestion-service

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
