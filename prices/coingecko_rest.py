"""REST-fallback на CoinGecko /simple/price.

Используется только для монет, которых нет ни у одного websocket-провайдера
(DEX/неликвид). Один батч-запрос на все непокрытые id, поэтому нагрузка
минимальна и не зависит от числа монет.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import requests

from prices.models import PricePoint

logger = logging.getLogger(__name__)

COINGECKO_SIMPLE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_UA = "Notion-Updater/1.0"


class CoinGeckoRest:
    def __init__(self, vs_currency: str = "usd") -> None:
        self._vs = vs_currency
        self._cache: dict[str, PricePoint] = {}

    def snapshot(self) -> dict[str, PricePoint]:
        return dict(self._cache)

    def refresh(self, coingecko_ids: list[str]) -> None:
        ids = sorted({cid for cid in coingecko_ids if cid})
        if not ids:
            self._cache = {}
            return
        try:
            response = requests.get(
                COINGECKO_SIMPLE_URL,
                params={
                    "ids": ",".join(ids),
                    "vs_currencies": self._vs,
                    "include_24hr_change": "true",
                },
                headers=_headers(),
                timeout=20,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:  # noqa: BLE001 — фолбэк необязателен
            logger.warning("CoinGecko /simple/price недоступен: %s", e)
            return

        now = datetime.now(timezone.utc)
        cache: dict[str, PricePoint] = {}
        for cid in ids:
            item = data.get(cid) or {}
            price = item.get(self._vs)
            if price is None:
                logger.warning("CoinGecko REST: нет цены для %r", cid)
                continue
            change = item.get(f"{self._vs}_24h_change")
            yesterday = (float(price) / (1 + change / 100)) if change is not None else None
            cache[cid] = PricePoint(float(price), yesterday, now)

        self._cache = cache
        logger.info("CoinGecko REST: получено %s цен (запрошено %s)", len(cache), len(ids))


def _headers() -> dict:
    headers = {"User-Agent": COINGECKO_UA}
    demo_key = os.getenv("COINGECKO_DEMO_API_KEY")
    if demo_key:
        headers["x-cg-demo-api-key"] = demo_key
    return headers
