"""Runs the REAL ingestion app (real auth, tenant binding, OTLP, redaction) with in-memory
Kafka/ClickHouse stand-ins, plus GET /_test/events to inspect what was stored.
Used only by the local end-to-end test; not shipped as a service."""

import uvicorn

from app.main import create_app


class Sink:
    def __init__(self): self.items = []
    async def start(self): ...
    async def stop(self): ...
    async def publish(self, topic, event): self.items.append(event)
    async def write(self, event): ...


sink = Sink()
app = create_app(lambda s: sink, lambda s: sink)


@app.get("/_test/events")
async def events():
    return [e.model_dump(mode="json") for e in sink.items]


if __name__ == "__main__":
    import sys
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
