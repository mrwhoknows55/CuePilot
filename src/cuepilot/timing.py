"""Consistent wall-clock latency logs for processing operations."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def log_latency(
    logger: logging.Logger, operation: str, *, level: int = logging.INFO
) -> Iterator[None]:
    started = perf_counter()
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        logger.log(
            level, "Latency: operation=%s duration_ms=%.2f status=%s",
            operation, (perf_counter() - started) * 1000, status,
        )
