FROM python:3.12-slim AS base

WORKDIR /srv

COPY packages/schemas /srv/packages/schemas
COPY apps/reasoning-service/requirements.txt /srv/apps/reasoning-service/requirements.txt

WORKDIR /srv/apps/reasoning-service
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/reasoning-service/app /srv/apps/reasoning-service/app

WORKDIR /srv/apps/reasoning-service

ENV PYTHONUNBUFFERED=1
EXPOSE 8003

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
