FROM python:3.12-slim AS base

WORKDIR /srv

COPY packages/schemas /srv/packages/schemas
COPY apps/alert-router/requirements.txt /srv/apps/alert-router/requirements.txt

WORKDIR /srv/apps/alert-router
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/alert-router/app /srv/apps/alert-router/app

WORKDIR /srv/apps/alert-router

ENV PYTHONUNBUFFERED=1
EXPOSE 8004

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8004/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
