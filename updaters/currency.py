"""Обновление курсов валют в Notion.

Извлечено из currency-updater/main.py (CurrencyParser + OptimizedNotionUpdater).
Логика сохранена: источник — API Беларусбанка, фиксированные курсы как fallback.
"""

import logging
import time
from typing import Dict, Optional, Set

import requests

import notion
from config import CurrencyConfig

logger = logging.getLogger(__name__)

# Соответствие числовых кодов из поля Notion буквенным кодам валют.
CURRENCY_CODE_MAPPING = {
    145: "USD",  # Доллар США
    292: "EUR",  # Евро
    298: "RUB",  # Российский рубль
    1: "BYN",  # Белорусский рубль
    293: "GBP",  # Фунт стерлингов
    304: "CNY",  # Китайский юань
}

# Фиксированные курсы на случай недоступности API (сохранено как в исходнике).
FIXED_RATES = {
    "USD": 3.15,
    "EUR": 3.40,
    "RUB": 0.034,
    "GBP": 4.00,
    "CNY": 0.43,
}

BANK_FIELD_MAPPING = {
    "USD": "USD_in",
    "EUR": "EUR_in",
    "RUB": "RUB_in",
    "GBP": "GBP_in",
    "CNY": "CNY_in",
    "PLN": "PLN_in",
    "UAH": "UAH_in",
}


class CurrencyParser:
    """Парсер курсов валют с кэшированием ответа Беларусбанка."""

    def __init__(self, city: str):
        self.city = city
        self.rates_cache: Dict[str, float] = {}
        self.cache_timestamp: Optional[float] = None
        self.cache_valid_hours = 1

    def get_exchange_rates_batch(self, currency_codes: Set[str]) -> Dict[str, float]:
        result: Dict[str, float] = {}

        if "BYN" in currency_codes:
            result["BYN"] = 1.0

        bank_rates = self._get_belarusbank_rates()

        for code in currency_codes:
            if code == "BYN":
                continue
            if code in bank_rates:
                result[code] = bank_rates[code]
            else:
                fixed_rate = FIXED_RATES.get(code)
                if fixed_rate is not None:
                    result[code] = fixed_rate
                    logger.warning("Используется фиксированный курс для %s: %s", code, fixed_rate)

        return result

    def _get_belarusbank_rates(self) -> Dict[str, float]:
        try:
            if self._should_refresh_cache():
                logger.info("Загрузка курсов с Беларусбанка...")

                url = "https://belarusbank.by/api/kursExchange"
                response = requests.get(url, params={"city": self.city}, timeout=15)
                response.raise_for_status()

                data = response.json()

                if not data or not isinstance(data, list):
                    logger.error("Неверный формат ответа от Беларусбанка")
                    return {}

                self.rates_cache = {}
                bank_data = data[0]

                for our_code, bank_field in BANK_FIELD_MAPPING.items():
                    if bank_field in bank_data and bank_data[bank_field]:
                        try:
                            self.rates_cache[our_code] = float(bank_data[bank_field])
                        except (ValueError, TypeError):
                            logger.warning("Не удалось преобразовать курс для %s", our_code)

                self.cache_timestamp = time.time()
                logger.info("Загружено %s курсов с Беларусбанка", len(self.rates_cache))

            return self.rates_cache.copy()

        except requests.exceptions.Timeout:
            logger.error("Таймаут при запросе к API Беларусбанка")
            return {}
        except Exception as e:
            logger.error("Ошибка загрузки курсов: %s", e)
            return {}

    def _should_refresh_cache(self) -> bool:
        if not self.cache_timestamp:
            return True
        return (time.time() - self.cache_timestamp) > (self.cache_valid_hours * 3600)


class CurrencyUpdater:
    def __init__(self, config: CurrencyConfig, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.parser = CurrencyParser(config.city)

    def extract_currency_code(self, page_properties: Dict) -> Optional[str]:
        try:
            id_money_field = page_properties.get(self.config.code_field)
            if not id_money_field:
                return None

            if id_money_field.get("type") == "number":
                number_value = id_money_field.get("number")
                if number_value is not None:
                    return CURRENCY_CODE_MAPPING.get(int(number_value))

            return None
        except Exception:
            return None

    def run(self) -> Dict:
        logger.info("Получение всех записей из базы данных %s", self.config.database_id)
        try:
            pages = notion.query_database(self.config.database_id)
        except Exception as e:
            logger.error("Ошибка получения данных: %s", e)
            return {"updated": 0, "skipped": 0, "errors": 0, "unique_currencies": 0, "api_calls_saved": 0}

        logger.info("Найдено %s записей", len(pages))
        if not pages:
            return {"updated": 0, "skipped": 0, "errors": 0, "unique_currencies": 0, "api_calls_saved": 0}

        page_data = []
        unique_currencies: Set[str] = set()

        for page in pages:
            page_id = page["id"]
            currency_code = self.extract_currency_code(page.get("properties", {}))
            if not currency_code:
                logger.debug("Пропуск записи %s: не удалось определить валюту", page_id)
                continue
            page_data.append((page_id, currency_code))
            unique_currencies.add(currency_code)

        logger.info(
            "Найдено %s уникальных валют: %s",
            len(unique_currencies),
            ", ".join(sorted(unique_currencies)),
        )

        if not unique_currencies:
            if pages:
                logger.warning(
                    "Не удалось определить валюту ни для одной записи. Проверьте CURRENCY_CODE_FIELD='%s'. Доступные поля: %s",
                    self.config.code_field,
                    ", ".join(pages[0].get("properties", {}).keys()),
                )
            else:
                logger.warning("Нет валют для обработки")
            return {"updated": 0, "skipped": len(pages), "errors": 0, "unique_currencies": 0, "api_calls_saved": 0}

        start_time = time.time()
        exchange_rates = self.parser.get_exchange_rates_batch(unique_currencies)
        logger.info(
            "Получено курсов: %s из %s за %.2fс",
            len(exchange_rates),
            len(unique_currencies),
            time.time() - start_time,
        )

        updated_count = 0
        error_count = 0

        for page_id, currency_code in page_data:
            if currency_code not in exchange_rates:
                logger.warning("Нет курса для валюты %s (запись %s)", currency_code, page_id)
                error_count += 1
                continue

            rate = exchange_rates[currency_code]
            if self._update_single_page(page_id, rate):
                updated_count += 1
                logger.debug("Обновлен курс %s = %s для записи %s", currency_code, rate, page_id)
            else:
                error_count += 1

            time.sleep(0.05)

        return {
            "updated": updated_count,
            "skipped": len(pages) - len(page_data),
            "errors": error_count,
            "unique_currencies": len(unique_currencies),
            "api_calls_saved": len(page_data) - len(unique_currencies),
        }

    def _update_single_page(self, page_id: str, rate: float) -> bool:
        if self.dry_run:
            logger.info("[DRY_RUN] Запись %s: %s = %s", page_id, self.config.rate_field, rate)
            return True
        try:
            notion.update_page(page_id, {self.config.rate_field: {"number": rate}})
            return True
        except Exception as e:
            logger.error("Ошибка обновления %s: %s", page_id, e)
            return False


def run(config: CurrencyConfig, dry_run: bool = False) -> Dict:
    return CurrencyUpdater(config, dry_run=dry_run).run()
