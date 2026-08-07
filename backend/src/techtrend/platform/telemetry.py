"""structlog + prometheus. Never log article bodies or settings wholesale."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog
from prometheus_client import Counter, Gauge, Histogram

JOBS = Counter("tt_jobs_total", "Jobs processed", ["stage", "outcome"])
JOB_TIME = Histogram("tt_job_seconds", "Job duration", ["stage"])
BACKLOG = Gauge("tt_backlog", "Pending jobs", ["stage"])
AI_TOKENS = Counter("tt_ai_tokens_total", "Claude tokens", ["stage", "kind"])

log = structlog.get_logger()


def init(env: str, level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), 20))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer()
            if env != "local"
            else structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), 20)),
        cache_logger_on_first_use=True,
    )


@contextmanager
def span(name: str, **fields: Any) -> Iterator[None]:
    with structlog.contextvars.bound_contextvars(span=name, **fields):
        yield
