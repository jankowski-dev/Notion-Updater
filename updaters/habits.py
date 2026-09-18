"""Ежедневный инкремент счётчиков привычек в Notion.

Извлечено из Nexter.Bot/health_notion.py (increment_all_habit_counters).
Список привычек и параметры полей берутся из переменных окружения.
"""

import logging

import notion
from config import HabitsConfig

logger = logging.getLogger(__name__)


def run(config: HabitsConfig, dry_run: bool = False) -> int:
    """Увеличивает счётчик всех привычек из списка на 1."""
    habits_lower = [habit.lower() for habit in config.habits]

    try:
        pages = notion.query_database(config.database_id)
    except Exception as e:
        logger.error("Ошибка запроса привычек: %s", e)
        return 0

    updated = 0
    for page in pages:
        props = page.get("properties", {})
        title = notion.get_title(props, config.name_field)
        if title.lower() not in habits_lower:
            continue

        new_counter = int(notion.get_number(props, config.counter_field)) + 1
        try:
            if dry_run:
                logger.info("[DRY_RUN] +1 для '%s' -> %s", title, new_counter)
            else:
                notion.update_page(page["id"], {config.counter_field: {"number": new_counter}})
            updated += 1
        except Exception:
            logger.error("Ошибка +1 для %s", title)

    logger.info("+1 к %s привычкам.", updated)
    return updated
