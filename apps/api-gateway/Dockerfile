FROM python:3.12-slim
WORKDIR /srv
COPY packages/llm /srv/packages/llm
COPY packages/schemas /srv/packages/schemas
COPY apps/api-gateway/requirements.txt /srv/apps/api-gateway/requirements.txt
WORKDIR /srv/apps/api-gateway
RUN pip install --no-cache-dir -r requirements.txt
COPY apps/api-gateway/app /srv/apps/api-gateway/app
ENV PYTHONUNBUFFERED=1
EXPOSE 8005
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8005/healthz')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005"]
