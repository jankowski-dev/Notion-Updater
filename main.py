"""Notion-Updater — единая точка входа.

Запускает APScheduler с задачами обновления курсов валют, цен криптовалют
и счётчиков привычек в Notion.
"""

import logging
import os
import signal
import sys
import time

from dotenv import load_dotenv

from config import ConfigError, load_config
from scheduler import build_scheduler

logger = logging.getLogger("notion_updater")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )


def main() -> int:
    sys.stdout.reconfigure(line_buffering=True)
    load_dotenv()

    _setup_logging(os.environ.get("LOG_LEVEL", "INFO").upper())

    try:
        config = load_config()
    except ConfigError as e:
        logger.error("Ошибка конфигурации: %s", e)
        return 1

    logger.info("=" * 60)
    logger.info("Запуск Notion-Updater")
    logger.info("  Валюты: %s", "вкл" if config.enable_currency else "выкл")
    logger.info("  Крипта: %s", "вкл" if config.enable_crypto else "выкл")
    logger.info("  Привычки: %s", "вкл" if config.enable_habits else "выкл")
    logger.info("  DRY_RUN: %s", config.dry_run)
    logger.info("=" * 60)

    scheduler = build_scheduler(config)
    scheduler.start()
    logger.info("Планировщик запущен. Задач: %s", len(scheduler.get_jobs()))

    stop = {"flag": False}

    def _handle_signal(signum, frame):
        logger.info("Получен сигнал %s, завершение...", signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        while not stop["flag"]:
            time.sleep(1)
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Остановлено.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
