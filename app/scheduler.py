"""Периодическая фоновая синхронизация кэша с трекером (план, раздел 2)."""
from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


def start_background_sync(job: Callable[[], None], interval_minutes: int) -> BackgroundScheduler:
    """Интервальная автосинхронизация; max_instances=1 — не гонять параллельно."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        job,
        "interval",
        minutes=interval_minutes,
        id="tracker_sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("Автосинхронизация трекера запущена: каждые %d мин.", interval_minutes)
    return scheduler
