"""Обновление цен криптовалют в Notion.

Извлечено из crypto-updater/app.py. Источник — CoinGecko /coins/markets.
Улучшение: база Notion опрашивается один раз за цикл (в исходнике — дважды).
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from time import sleep

import requests

import notion
from config import CryptoConfig

logger = logging.getLogger(__name__)

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"


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

    logger.info("Найдено %s страниц криптовалют.", len(result))
    return result


def fetch_prices_from_coingecko(coin_ids_list: list[str], chunk_size: int) -> tuple[dict, dict]:
    logger.info("Запрос текущих и вчерашних цен для %s криптовалют у CoinGecko...", len(coin_ids_list))
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

        retries = 3
        for attempt in range(retries):
            try:
                response = requests.get(COINGECKO_MARKETS_URL, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    for coin_data in data:
                        coin_id = coin_data.get("id")
                        if not coin_id:
                            logger.warning("ID монеты не найден в данных markets для chunk %s.", i + 1)
                            continue

                        current_price = coin_data.get("current_price")
                        if current_price is not None:
                            all_current_prices[coin_id] = current_price
                        else:
                            logger.warning("Текущая цена для %s не найдена.", coin_id)

                        price_change_pct = coin_data.get("price_change_percentage_24h_in_currency")
                        yesterday = compute_yesterday_price(current_price, price_change_pct)
                        if yesterday is not None:
                            all_yesterday_prices[coin_id] = yesterday
                        else:
                            logger.debug("%s — нет данных о 24h изменении, вчерашняя цена пропущена.", coin_id)

                    logger.info("Получены цены из markets для чанка %s/%s", i + 1, len(chunks))
                    break
                elif response.status_code == 429:
                    reset_time = int(response.headers.get("Retry-After", 60))
                    logger.warning("Rate limit от CoinGecko (markets). Ожидание %s секунд...", reset_time)
                    sleep(reset_time)
                    continue
                else:
                    logger.error(
                        "Ошибка от CoinGecko (markets, чанк %s): %s - %s",
                        i + 1,
                        response.status_code,
                        response.text,
                    )
                    if attempt == retries - 1:
                        raise Exception(
                            f"Не удалось получить цены markets для чанка {i + 1} после {retries} попыток."
                        )
            except Exception as e:
                logger.error("Ошибка при запросе markets (чанк %s): %s", i + 1, e)
                if attempt == retries - 1:
                    raise e
        sleep(0.1)

    logger.info("Всего получено текущих цен для %s монет.", len(all_current_prices))
    logger.info("Всего получено вчерашних цен для %s монет.", len(all_yesterday_prices))
    return all_current_prices, all_yesterday_prices


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
