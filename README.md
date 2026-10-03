# Notion-Updater

Единый сервис обновления данных в Notion. Объединяет три ранее независимых проекта:

| Модуль | Что делает | Источник |
|---|---|---|
| `currency` | Курсы валют с API Беларусбанка → Notion | `currency-updater` |
| `crypto` | Цены криптовалют с websocket (Kraken + Coinbase) → Notion | `crypto-updater` |
| `habits` | Ежедневный `+1` к счётчикам привычек в Notion | `Nexter.Bot` (часть про привычки) |

Один процесс, один Railway-сервис, планировщик APScheduler с тремя независимыми задачами.

## Структура

```
main.py               # точка входа: логи, конфиг, планировщик
config.py             # чтение и валидация переменных окружения
notion.py             # единый клиент Notion API
scheduler.py          # регистрация задач
updaters/
  currency.py         # логика валют
  crypto.py           # логика крипты
  habits.py           # логика привычек
prices/
  models.py           # модели рыночных данных
  symbols.py          # разрешение символов Notion в биржевые пары
  providers.py        # websocket-провайдеры Kraken и Coinbase
  engine.py           # движок: соединения, кэш цен, подписки
tests/                # pytest
```

## Локальный запуск

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements-dev.txt
copy .env.example .env           # заполнить значения
python main.py
```

Проверка без записи в Notion:

```bash
set DRY_RUN=true
python main.py
```

Тесты:

```bash
python -m pytest -q
```

## Деплой на Railway

1. Создать новый сервис из репозитория `Notion-Updater`.
2. Railway подхватит `railway.json` (NIXPACKS, `startCommand: python -u main.py`, restart `ALWAYS`).
3. Порт открывать не нужно — это worker без HTTP.
4. Задать переменные окружения (см. таблицу ниже).
5. Для поэтапного переключения включать модули по одному через `ENABLE_*` и гасить соответствующий старый сервис.

## Переменные окружения

### Общие

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `NOTION_TOKEN` | да* | — | Интеграционный токен Notion |
| `NOTION_API_KEY` | нет | — | Альтернатива `NOTION_TOKEN` (используется, если токен не задан) |
| `TZ` | нет | `Europe/Minsk` | Часовой пояс планировщика (для задачи привычек) |
| `LOG_LEVEL` | нет | `INFO` | Уровень логирования |
| `DRY_RUN` | нет | `false` | `true` — читает Notion, но ничего не записывает |
| `ENABLE_CURRENCY` | нет | `true` | Включить модуль валют |
| `ENABLE_CRYPTO` | нет | `true` | Включить модуль крипты |
| `ENABLE_HABITS` | нет | `true` | Включить модуль привычек |

\* Обязательна, если включён хотя бы один модуль.

### Валюты (при `ENABLE_CURRENCY=true`)

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `CURRENCY_DATABASE_ID` | да | — | ID базы Notion с валютами |
| `CURRENCY_CODE_FIELD` | нет | `ID_money` | Поле с числовым кодом валюты |
| `CURRENCY_RATE_FIELD` | нет | `Money_rate` | Поле, куда пишется курс (старое имя — `RATE_FIELD`, поддерживается) |
| `CURRENCY_UPDATE_HOURS` | нет | `2` | Интервал обновления, часов |
| `CURRENCY_CRON` | нет | — | Cron-выражение (5 полей). Перебивает интервал |
| `CURRENCY_CITY` | нет | `Минск` | Город для API Беларусбанка |

### Крипта (при `ENABLE_CRYPTO=true`)

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `CRYPTO_DATABASE_ID` | да | — | ID базы Notion с монетами |
| `CRYPTO_SYMBOL_FIELD` | нет | `Symbol` | Поле с монетой: пара (`BTC-USD`), тикер (`BTC`) или CoinGecko-id (`bitcoin`) |
| `CRYPTO_PRICE_FIELD` | нет | `Price` | Поле текущей цены |
| `CRYPTO_UPDATED_FIELD` | нет | `Last Updated` | Поле времени обновления |
| `CRYPTO_YESTERDAY_PRICE_FIELD` | нет | `Price (Yesterday)` | Поле вчерашней цены |
| `CRYPTO_TICK_SECONDS` | нет | `30` | Интервал записи в Notion, секунд (минимум 20) |
| `CRYPTO_RESYNC_SECONDS` | нет | `300` | Как часто перечитывать базу на новые монеты, секунд |
| `CRYPTO_PROVIDERS` | нет | `kraken,coinbase` | Провайдеры websocket в порядке приоритета |
| `CRYPTO_STALE_SECONDS` | нет | `300` | Не писать цену старше этого возраста, секунд |
| `CRYPTO_HEARTBEAT_SECONDS` | нет | `0` | «Пульс» для неизменившихся (0 — выключен) |
| `COINGECKO_DEMO_API_KEY` | нет | — | Для ленивого `/coins/list` (только если используешь CoinGecko-id) |

### Привычки (при `ENABLE_HABITS=true`)

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `HABITS_DATABASE_ID` | да | — | ID базы Notion с привычками |
| `HABITS_LIST` | да | — | Список привычек через запятую |
| `HABITS_NAME_FIELD` | нет | `Название` | Поле с названием привычки |
| `HABITS_COUNTER_FIELD` | нет | `Срок [P]` | Поле-счётчик, инкрементируется |
| `HABITS_INCREMENT_TIME` | нет | `22:00` | Время ежедневного инкремента (HH:MM) |

## Поведение

- **Валюты**: при старте выполняется сразу, далее по интервалу. Курсы берутся с Беларусбанка одним запросом на все валюты. Если валюты нет в ответе — используется фиксированный курс-заглушка (как в исходном проекте).
- **Крипта**: цены приходят push-потоком с websocket (Kraken, при отсутствии пары — Coinbase). Раз в `CRYPTO_TICK_SECONDS` в Notion записываются только изменившиеся цены (не изменилось — запроса нет). База Notion перечитывается раз в `CRYPTO_RESYNC_SECONDS`: новые монеты подхватываются автоматически, без правок кода или конфига. Поле `Symbol` понимает пару (`BTC-USD`), тикер (`BTC`) или CoinGecko-id (`bitcoin`).
- **Привычки**: раз в сутки в `HABITS_INCREMENT_TIME` по часовому поясу `TZ`. Инкрементируются только привычки из `HABITS_LIST`.

## Известные точки для будущих улучшений

Не изменены при объединении, чтобы сохранить поведение 1:1:

- Кэш курсов валют (1 час) при интервале обновления ≥ 1 часа практически не используется.
- Фиксированные курсы-заглушки молча маскируют недоступность API Беларусбанка.
- Три разные реализации retry/backoff не унифицированы.
- Версия Notion API `2022-06-28` устарела (миграция на data sources — отдельная задача).

## Важно

Исходные репозитории `currency-updater`, `crypto-updater` и `Nexter.Bot` не изменялись. Из них только прочитан и перенесён код.
