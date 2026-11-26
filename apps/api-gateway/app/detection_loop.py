"""Optional background detection loop (DETECTION_ENABLED=true). One failing app never stops the others."""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("detection")


def run_once(repo, executor, settings, llm=None) -> int:
    """Run detection for every live application. Returns the number of apps processed successfully."""
    from app.routes.incidents import process_application
    ok = 0
    for app in repo.monitored_applications():
        try:
            process_application(repo, executor, app, settings, llm)
            ok += 1
        except Exception:
            logger.exception("detection_failed application=%s", app.get("id"))
    return ok


def run_forever(repo, executor, settings, stop: threading.Event, llm_getter=lambda: None) -> None:
    while not stop.is_set():
        try:
            run_once(repo, executor, settings, llm_getter())
        except Exception:
            logger.exception("detection_cycle_failed")
        stop.wait(max(10, settings.detection_interval_seconds))
