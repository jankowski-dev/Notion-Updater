"""Регистрация задач обновления в APScheduler.

Каждый включённый модуль получает отдельную задачу. Для валют и крипты
поддерживается либо интервал, либо cron-выражение (перебивает интервал).
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import Config
from updaters import crypto, currency, habits

logger = logging.getLogger(__name__)

_JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 600,
}


def _job_currency(config: Config) -> None:
    result = currency.run(config.currency, dry_run=config.dry_run)
    logger.info(
        "Валюты: обновлено=%s пропущено=%s ошибок=%s",
        result["updated"],
        result["skipped"],
        result["errors"],
    )


def _job_crypto(config: Config) -> None:
    result = crypto.run(config.crypto, dry_run=config.dry_run)
    logger.info("Крипта: обновлено=%s ошибок=%s", result["updated"], result["errors"])


def _job_habits(config: Config) -> None:
    updated = habits.run(config.habits, dry_run=config.dry_run)
    logger.info("Привычки: +1 к %s записям", updated)


def _add_cron_or_interval(scheduler, func, job_id, cron, interval_kwargs) -> None:
    if cron:
        trigger = CronTrigger.from_crontab(cron, timezone=scheduler.timezone)
        scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **_JOB_DEFAULTS)
        logger.info("%s: cron '%s'", job_id, cron)
    else:
        scheduler.add_job(
            func,
            "interval",
            id=job_id,
            replace_existing=True,
            next_run_time=datetime.now(scheduler.timezone),
            **interval_kwargs,
            **_JOB_DEFAULTS,
        )
        logger.info("%s: интервал %s", job_id, interval_kwargs)


def build_scheduler(config: Config) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=ZoneInfo(config.timezone))
    logger.info("Часовой пояс планировщика: %s", config.timezone)

    if config.enable_currency and config.currency:
        _add_cron_or_interval(
            scheduler,
            lambda: _job_currency(config),
            "currency",
            config.currency.cron,
            {"hours": config.currency.update_hours},
        )

    if config.enable_crypto and config.crypto:
        _add_cron_or_interval(
            scheduler,
            lambda: _job_crypto(config),
            "crypto",
            config.crypto.cron,
            {"seconds": config.crypto.update_seconds},
        )

    if config.enable_habits and config.habits:
        scheduler.add_job(
            lambda: _job_habits(config),
            CronTrigger(
                hour=config.habits.hour,
                minute=config.habits.minute,
                timezone=scheduler.timezone,
            ),
            id="habits",
            replace_existing=True,
            **_JOB_DEFAULTS,
        )
        logger.info("habits: ежедневно в %02d:%02d", config.habits.hour, config.habits.minute)

    return scheduler
