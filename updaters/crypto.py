"""Обновление цен криптовалют в Notion.

Извлечено из crypto-updater/app.py. Источник — CoinGecko.
Улучшения:
- база Notion опрашивается один раз за цикл (в исходнике — дважды);
- если /coins/markets заблокирован (403 с IP датацентра), используется
  резервный запрос каждой монеты через /coins/{id}.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import sleep

import requests

import notion
from config import CryptoConfig

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_MARKETS_URL = f"{COINGECKO_BASE}/coins/markets"
COINGECKO_UA = "Notion-Updater/1.0"


def _coingecko_headers() -> dict:
    """Заголовки для CoinGecko: User-Agent + опциональный API-ключ.

    Ключ снимает блокировку запросов с датацентров (CloudFront 403).
    Бесплатный demo-ключ: https://www.coingecko.com/en/api/pricing
    """
    headers = {"User-Agent": COINGECKO_UA}
    demo_key = os.getenv("COINGECKO_DEMO_API_KEY")
    pro_key = os.getenv("COINGECKO_PRO_API_KEY")
    if demo_key:
        headers["x-cg-demo-api-key"] = demo_key
    elif pro_key:
        headers["x-cg-pro-api-key"] = pro_key
    return headers


def compute_yesterday_price(current_price, price_change_pct):
    """Вчерашняя цена из текущей цены и 24h-изменения в процентах."""
    if price_change_pct is None or current_price is None:
        return None
    return current_price / (1 + price_change_pct / 100)


def _symbol_from_props(props: dict, field: str) -> str:
    prop = props.get(field, {})
    ptype = prop.get("type")
    if ptype == "rich_text":
        arr = prop.get("rich_text", [])
    elif ptype == "title":
        arr = prop.get("title", [])
    else:
        return ""
    if not arr:
        return ""
    return arr[0].get("text", {}).get("content", "").strip()


def get_pages_with_symbols(config: CryptoConfig) -> list[dict]:
    """Возвращает страницы базы с их символом монеты (один запрос вместо двух)."""
    logger.info("Получение страниц криптовалют из Notion...")
    try:
        pages = notion.query_database(config.database_id)
    except Exception as e:
        logger.error("Ошибка при получении страниц из Notion: %s", e)
        return []

    result = []
    for page in pages:
        symbol = _symbol_from_props(page.get("properties", {}), config.symbol_field)
        if symbol:
            result.append({"page_id": page["id"], "coin_id": symbol.lower()})
        else:
            logger.warning(
                "Пропущена страница %s: '%s' пустое или не найдено.",
                page["id"],
                config.symbol_field,
            )

    if not result and pages:
        logger.warning(
            "Не найдено ни одного символа. Проверьте CRYPTO_SYMBOL_FIELD='%s'. Доступные поля: %s",
            config.symbol_field,
            ", ".join(pages[0].get("properties", {}).keys()),
        )

    logger.info("Найдено %s страниц криптовалют.", len(result))
    return result


def _fetch_markets(coin_ids_list: list[str], chunk_size: int) -> tuple[dict, dict] | None:
    """Батч-запрос через /coins/markets. Возвращает None, если не удалось."""
    logger.info(
        "Запрос текущих и вчерашних цен для %s криптовалют у CoinGecko (markets)...",
        len(coin_ids_list),
    )
    chunks = [coin_ids_list[i : i + chunk_size] for i in range(0, len(coin_ids_list), chunk_size)]

    all_current_prices: dict = {}
    all_yesterday_prices: dict = {}

    for i, chunk in enumerate(chunks):
        ids_str = ",".join(chunk)
        params = {
            "vs_currency": "usd",
            "ids": ids_str,
            "sparkline": "false",
            "price_change_percentage": "24h",
        }

        success = False
        for attempt in range(3):
            try:
                response = requests.get(
                    COINGECKO_MARKETS_URL, params=params, headers=_coingecko_headers(), timeout=10
                )
                if response.status_code == 200:
                    data = response.json()
                    if not data:
                        logger.warning(
                            "CoinGecko вернул пустой ответ (чанк %s). Сырой ответ: %s",
                            i + 1,
                            response.text[:500],
                        )
                    else:
                        logger.info("Ответ markets (чанк %s): %s элементов.", i + 1, len(data))
                    for coin_data in data:
                        coin_id = coin_data.get("id")
                        if not coin_id:
                            logger.warning("ID монеты не найден в данных markets для chunk %s.", i + 1)
                            continue

                        current_price = coin_data.get("current_price")
                        if current_price is not None:
                            all_current_prices[coin_id] = current_price
                        else:
                            logger.warning(
                                "Текущая цена для %s не найдена. Объект: %s",
                                coin_id,
                                str(coin_data)[:300],
                            )

                        price_change_pct = coin_data.get("price_change_percentage_24h_in_currency")
                        yesterday = compute_yesterday_price(current_price, price_change_pct)
                        if yesterday is not None:
                            all_yesterday_prices[coin_id] = yesterday
                        else:
                            logger.debug("%s — нет данных о 24h изменении, вчерашняя цена пропущена.", coin_id)

                    success = True
                    break
                elif response.status_code == 429:
                    reset_time = int(response.headers.get("Retry-After", 60))
                    logger.warning("Rate limit от CoinGecko (markets). Ожидание %s секунд...", reset_time)
                    sleep(reset_time)
                    continue
                elif response.status_code == 403:
                    wait = 30 * (attempt + 1)
                    logger.warning(
                        "CoinGecko заблокировал запрос (403, вероятно IP датацентра). "
                        "Повтор через %s сек... Если повторяется — задайте COINGECKO_DEMO_API_KEY.",
                        wait,
                    )
                    sleep(wait)
                    continue
                else:
                    logger.error(
                        "Ошибка от CoinGecko (markets, чанк %s): %s - %s",
                        i + 1,
                        response.status_code,
                        response.text,
                    )
            except Exception as e:
                logger.error("Ошибка при запросе markets (чанк %s): %s", i + 1, e)

        if not success:
            logger.error("Не удалось получить цены markets для чанка %s.", i + 1)
            return None
        sleep(0.1)

    logger.info("Всего получено текущих цен для %s монет.", len(all_current_prices))
    logger.info("Всего получено вчерашних цен для %s монет.", len(all_yesterday_prices))
    return all_current_prices, all_yesterday_prices


def _fetch_per_coin(coin_ids_list: list[str]) -> tuple[dict, dict]:
    """Резерв: запрос каждой монеты через /coins/{id} (markets может быть заблокирован)."""
    logger.info("Резервный запрос по одной монете для %s монет...", len(coin_ids_list))
    all_current_prices: dict = {}
    all_yesterday_prices: dict = {}

    for coin_id in coin_ids_list:
        for attempt in range(3):
            try:
                response = requests.get(
                    f"{COINGECKO_BASE}/coins/{coin_id}",
                    headers=_coingecko_headers(),
                    timeout=15,
                )
                if response.status_code == 200:
                    data = response.json()
                    market_data = data.get("market_data") or {}
                    current_price = (market_data.get("current_price") or {}).get("usd")
                    if current_price is not None:
                        all_current_prices[coin_id] = current_price
                        change = market_data.get("price_change_percentage_24h")
                        yesterday = compute_yesterday_price(current_price, change)
                        if yesterday is not None:
                            all_yesterday_prices[coin_id] = yesterday
                    else:
                        logger.warning("Нет цены для %s в /coins/%s.", coin_id, coin_id)
                    break
                elif response.status_code == 429:
                    reset = int(response.headers.get("Retry-After", 10))
                    logger.warning("Rate limit (per-coin) для %s. Ожидание %s сек...", coin_id, reset)
                    sleep(reset)
                    continue
                else:
                    logger.warning("Ответ /coins/%s: %s", coin_id, response.status_code)
                    sleep(5)
            except Exception as e:
                logger.error("Ошибка /coins/%s: %s", coin_id, e)
                sleep(5)
        sleep(2.5)

    logger.info("Резерв: получено текущих цен для %s монет.", len(all_current_prices))
    return all_current_prices, all_yesterday_prices


def fetch_prices_from_coingecko(coin_ids_list: list[str], chunk_size: int) -> tuple[dict, dict]:
    """Сначала батч-запрос, при неудаче — резерв по одной монете."""
    result = _fetch_markets(coin_ids_list, chunk_size)
    if result is not None:
        return result
    logger.warning("Батч-запрос markets не удался. Пробуем резервный запрос по одной монете.")
    return _fetch_per_coin(coin_ids_list)


def update_single_notion_page(args) -> tuple[bool, str]:
    page_id, current_price, yesterday_price, config, dry_run = args
    payload_props = {
        config.price_field: {"number": float(current_price)},
        config.updated_field: {"date": {"start": datetime.now().isoformat()}},
    }
    if yesterday_price is not None:
        payload_props[config.yesterday_price_field] = {"number": float(yesterday_price)}

    if dry_run:
        logger.info("[DRY_RUN] Страница %s: %s", page_id, payload_props)
        return True, page_id

    try:
        notion.update_page(page_id, payload_props)
        return True, page_id
    except Exception as e:
        return False, f"{page_id}: {str(e)}"


def run(config: CryptoConfig, dry_run: bool = False) -> dict:
    try:
        pages = get_pages_with_symbols(config)
        if not pages:
            logger.warning("В базе Notion не найдено ни одной монеты для обновления. Пропуск.")
            return {"updated": 0, "errors": 0}

        coin_ids = list({page["coin_id"] for page in pages})
        current_prices_map, yesterday_prices_map = fetch_prices_from_coingecko(coin_ids, config.chunk_size)

        update_tasks = []
        for page in pages:
            coin_id = page["coin_id"]
            current_price = current_prices_map.get(coin_id)
            if current_price is not None:
                update_tasks.append(
                    (page["page_id"], current_price, yesterday_prices_map.get(coin_id), config, dry_run)
                )
            else:
                logger.warning(
                    "Текущая цена для монеты '%s' не найдена в CoinGecko. Страница %s пропущена.",
                    coin_id,
                    page["page_id"],
                )

        logger.info("Подготовлено %s задач на обновление.", len(update_tasks))

        updated_count = 0
        failed_updates = []
        if update_tasks:
            with ThreadPoolExecutor(max_workers=3) as executor:
                results = list(executor.map(update_single_notion_page, update_tasks))

            for success, info in results:
                if success:
                    updated_count += 1
                    logger.info("Обновлена страница %s", info)
                else:
                    failed_updates.append(info)
                    logger.error("Ошибка обновления: %s", info)

        logger.info("ЗАВЕРШЕНО: %s обновлено, %s ошибок.", updated_count, len(failed_updates))
        if failed_updates:
            logger.error("Список ошибок: %s", failed_updates)

        return {"updated": updated_count, "errors": len(failed_updates)}
    except Exception:
        logger.critical("Критическая ошибка в обновлении крипты", exc_info=True)
        return {"updated": 0, "errors": 1}
