# Notion-Updater — дизайн объединённого сервиса

Дата: 2026-09-19

## Цель

Объединить три проекта обновления данных в Notion в один Railway-сервис,
выполнить структурный рефакторинг при переносе, не изменяя исходные репозитории.

## Источники

| Модуль | Исходный код | Перенесено |
|---|---|---|
| currency | `currency-updater/main.py` | `CurrencyParser`, `OptimizedNotionUpdater` |
| crypto | `crypto-updater/app.py` | `fetch_prices_from_coingecko`, обновление страниц |
| habits | `Nexter.Bot/health_notion.py`, `scheduler.py`, `notion_api.py` | `increment_all_habit_counters`, клиент Notion |

Из `Nexter.Bot` **не** переносятся: Viber (`notify`, `dispatcher`, `notion_webhook`,
`page_tracker`, `bot.py`, `app.py`), Flask/waitress, `health_config.yaml`.

## Архитектура

Один процесс. `main.py` валидирует конфиг и запускает `BackgroundScheduler` (APScheduler)
с тремя задачами. Каждая задача независима и включается флагом `ENABLE_*`.

```
main.py → config.load_config() → scheduler.build_scheduler()
                                     ├── currency (interval | cron)
                                     ├── crypto   (interval | cron)
                                     └── habits   (cron HH:MM)
```

Общие модули:

- `notion.py` — единый клиент: `query_database`, `get_page`, `update_page`,
  `get_title/get_rich_text/get_number/get_select/extract_id`.
- `config.py` — dataclasses + валидация, только для включённых модулей.

## Решения

- **Одна служба, один процесс** — минимум расходов на Railway, единые логи.
- **Конфигурация только через env** — единый стиль для всех модулей; привычки
  переведены с YAML на env (`HABITS_LIST`, `HABITS_DATABASE_ID`, поля).
- **Флаги `ENABLE_*`** — поэтапный переход без двойной записи в одни базы.
- **Интервалы опциональны** — env с дефолтами из исходников; для валют и крипты
  опциональные `CURRENCY_CRON` / `CRYPTO_CRON` перебивают интервал.
- **Логи только в stdout** — файловый лог крипты удалён (на Railway ФС эфемерная).

## Применённые улучшения

1. Крипта опрашивает базу Notion **один раз** за цикл вместо двух.
2. Логирование — только в stdout, без `FileHandler`.
3. `DRY_RUN` — чтение без записи.
4. Валидация конфига с понятными ошибками при старте.
5. Юнит-тесты на чистые функции.

## Отложено (поведение сохранено 1:1)

- Кэш курсов валют (1 ч) при интервале ≥ 1 ч неэффективен.
- Фиксированные курсы-заглушки маскируют сбои API.
- Унификация retry/backoff.
- Миграция Notion API с `2022-06-28` на data sources.

## Обработка ошибок

- Ошибка конфигурации → сообщение + выход с кодом 1.
- Сбой запроса к Notion/CoinGecko/Беларусбанку логируется; задача не роняет процесс.
- APScheduler: `coalesce=True`, `max_instances=1`, `misfire_grace_time=600`.
- `SIGTERM`/`SIGINT` → корректное завершение планировщика.

## Переход

1. `ENABLE_CRYPTO=true`, остальные `false` → проверить, погасить `crypto-updater`.
2. `ENABLE_CURRENCY=true` → погасить `currency-updater`.
3. `ENABLE_HABITS=true` → погасить habit-часть `Nexter.Bot`.
4. Старые репозитории не трогать.

## Проверка

- `python -m pytest` — зелёный.
- Сборка планировщика: 3 задачи (`currency`, `crypto`, `habits`) с ожидаемыми триггерами.
- DRY_RUN-прогон: задачи выполняются, ошибки сети/авторизации не роняют процесс.
