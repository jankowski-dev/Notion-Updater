"""Загрузка и валидация конфигурации из переменных окружения.

Все параметры читаются в момент вызова load_config(), что упрощает тесты
и позволяет менять окружение без перезапуска импорта.
"""

import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(Exception):
    """Ошибка конфигурации с понятным для пользователя текстом."""


def _get_str(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name}: ожидалось целое число, получено {raw!r}")


def _require(name: str, value: str) -> str:
    if not value:
        raise ConfigError(f"{name} не задана (обязательна для включённого модуля)")
    return value


def _parse_hhmm(name: str, value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ConfigError(f"{name}: ожидался формат HH:MM, получено {value!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ConfigError(f"{name}: ожидался формат HH:MM, получено {value!r}")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"{name}: недопустимое время {value!r}")
    return hour, minute


@dataclass
class CurrencyConfig:
    database_id: str
    code_field: str
    rate_field: str
    update_hours: int
    cron: str
    city: str


@dataclass
class CryptoConfig:
    database_id: str
    symbol_field: str
    price_field: str
    updated_field: str
    yesterday_price_field: str
    chunk_size: int
    update_seconds: int
    cron: str


@dataclass
class HabitsConfig:
    database_id: str
    habits: list[str]
    name_field: str
    counter_field: str
    hour: int
    minute: int


@dataclass
class Config:
    notion_token: str
    timezone: str
    log_level: str
    dry_run: bool
    enable_currency: bool
    enable_crypto: bool
    enable_habits: bool
    currency: CurrencyConfig | None
    crypto: CryptoConfig | None
    habits: HabitsConfig | None


def _parse_timezone(name: str, value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError(f"{name}: неизвестный часовой пояс {value!r}")
    return value


def _parse_habits_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_currency_config() -> CurrencyConfig | None:
    if not _get_bool("ENABLE_CURRENCY", True):
        return None
    return CurrencyConfig(
        database_id=_require("CURRENCY_DATABASE_ID", _get_str("CURRENCY_DATABASE_ID")),
        code_field=_get_str("CURRENCY_CODE_FIELD", "ID_money"),
        rate_field=_get_str("CURRENCY_RATE_FIELD", "Money_rate"),
        update_hours=_get_int("CURRENCY_UPDATE_HOURS", 2),
        cron=_get_str("CURRENCY_CRON"),
        city=_get_str("CURRENCY_CITY", "Минск"),
    )


def parse_crypto_config() -> CryptoConfig | None:
    if not _get_bool("ENABLE_CRYPTO", True):
        return None
    return CryptoConfig(
        database_id=_require("CRYPTO_DATABASE_ID", _get_str("CRYPTO_DATABASE_ID")),
        symbol_field=_get_str("CRYPTO_SYMBOL_FIELD", "Symbol"),
        price_field=_get_str("CRYPTO_PRICE_FIELD", "Price"),
        updated_field=_get_str("CRYPTO_UPDATED_FIELD", "Last Updated"),
        yesterday_price_field=_get_str("CRYPTO_YESTERDAY_PRICE_FIELD", "Price (Yesterday)"),
        chunk_size=_get_int("CRYPTO_CHUNK_SIZE", 200),
        update_seconds=_get_int("CRYPTO_UPDATE_SECONDS", 300),
        cron=_get_str("CRYPTO_CRON"),
    )


def parse_habits_config() -> HabitsConfig | None:
    if not _get_bool("ENABLE_HABITS", True):
        return None
    habits = _parse_habits_list(_get_str("HABITS_LIST"))
    if not habits:
        raise ConfigError(
            "HABITS_LIST не задана или пуста (обязательна для включённого модуля привычек)"
        )
    hour, minute = _parse_hhmm("HABITS_INCREMENT_TIME", _get_str("HABITS_INCREMENT_TIME", "22:00"))
    return HabitsConfig(
        database_id=_require("HABITS_DATABASE_ID", _get_str("HABITS_DATABASE_ID")),
        habits=habits,
        name_field=_get_str("HABITS_NAME_FIELD", "Название"),
        counter_field=_get_str("HABITS_COUNTER_FIELD", "Срок [P]"),
        hour=hour,
        minute=minute,
    )


def load_config() -> Config:
    """Читает окружение и собирает конфиг. Бросает ConfigError при ошибке."""
    enable_currency = _get_bool("ENABLE_CURRENCY", True)
    enable_crypto = _get_bool("ENABLE_CRYPTO", True)
    enable_habits = _get_bool("ENABLE_HABITS", True)

    any_enabled = enable_currency or enable_crypto or enable_habits

    token = _get_str("NOTION_TOKEN") or _get_str("NOTION_API_KEY")
    if any_enabled and not token:
        raise ConfigError("NOTION_TOKEN (или NOTION_API_KEY) не задан")

    timezone = _parse_timezone("TZ", _get_str("TZ", "Europe/Minsk"))

    return Config(
        notion_token=token,
        timezone=timezone,
        log_level=_get_str("LOG_LEVEL", "INFO").upper(),
        dry_run=_get_bool("DRY_RUN", False),
        enable_currency=enable_currency,
        enable_crypto=enable_crypto,
        enable_habits=enable_habits,
        currency=parse_currency_config(),
        crypto=parse_crypto_config(),
        habits=parse_habits_config(),
    )
