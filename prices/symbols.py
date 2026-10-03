"""Разрешение значения из Notion в биржевой инструмент.

Порядок: явная пара -> тикер (USD, затем USDT) -> ленивый CoinGecko /coins/list.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Callable

import requests

from prices.models import ResolvedCoin

logger = logging.getLogger(__name__)

COINGECKO_LIST_URL = "https://api.coingecko.com/api/v3/coins/list"
COINGECKO_UA = "Notion-Updater/1.0"

_PAIR_RE = re.compile(r"^([A-Za-z0-9]{2,12})[-/]([A-Za-z0-9]{2,8})$")
_TICKER_RE = re.compile(r"^[A-Z0-9]{2,10}$")

PAIR_SEPARATOR = {"kraken": "/", "coinbase": "-"}
PROVIDER_QUOTES = {"kraken": ["USD", "USDT"], "coinbase": ["USD", "USDT"]}

# Явной парой считаем только пары с поддерживаемой котировкой. Иначе значение
# вида "bitcoin-cash" (CoinGecko-id) ошибочно распалось бы на BASE/QUOTE.
SUPPORTED_QUOTES = frozenset(q for quotes in PROVIDER_QUOTES.values() for q in quotes)


def parse_explicit_pair(value: str) -> tuple[str, str] | None:
    m = _PAIR_RE.match(value.strip())
    if not m:
        return None
    base, quote = m.group(1).upper(), m.group(2).upper()
    if quote not in SUPPORTED_QUOTES:
        return None
    return base, quote


def format_pair(provider: str, base: str, quote: str) -> str:
    return f"{base}{PAIR_SEPARATOR[provider]}{quote}"


def _candidates(base: str, providers: list[str]) -> list[ResolvedCoin]:
    out: list[ResolvedCoin] = []
    for provider in providers:
        for quote in PROVIDER_QUOTES[provider]:
            if quote == base:
                continue
            out.append(ResolvedCoin(provider, format_pair(provider, base, quote)))
    return out


def resolve_candidates(
    raw_symbol: str,
    providers: list[str],
    lookup: Callable[[str], str | None] | None = None,
) -> list[ResolvedCoin]:
    """Кандидаты (provider, pair) в порядке приоритета; [] — не разрешилось."""
    value = raw_symbol.strip()
    if not value:
        return []

    explicit = parse_explicit_pair(value)
    if explicit:
        base, quote = explicit
        return [ResolvedCoin(p, format_pair(p, base, quote)) for p in providers]

    if _TICKER_RE.match(value):
        return _candidates(value, providers)

    if lookup is not None:
        ticker = lookup(value)
        if ticker:
            return _candidates(ticker.upper(), providers)

    return []


class CoinGeckoList:
    """Ленивый справочник id/symbol -> symbol из CoinGecko /coins/list."""

    def __init__(self, cooldown_seconds: float = 300.0) -> None:
        self._by_id: dict[str, str] = {}
        self._by_symbol: dict[str, str] = {}
        self._id_by_symbol: dict[str, str] = {}
        self._loaded = False
        self._retry_after = 0.0
        self._cooldown = cooldown_seconds

    def symbol_for(self, value: str) -> str | None:
        if not self._loaded and time.monotonic() >= self._retry_after:
            self._load()
        key = value.strip().lower()
        return self._by_id.get(key) or self._by_symbol.get(key)

    def id_for(self, value: str) -> str | None:
        """CoinGecko-id для значения (если это id или известный symbol)."""
        if not self._loaded and time.monotonic() >= self._retry_after:
            self._load()
        key = value.strip().lower()
        if key in self._by_id:
            return key
        return self._id_by_symbol.get(key)

    def _load(self) -> None:
        try:
            for item in self._fetch():
                cid = (item.get("id") or "").strip()
                symbol = (item.get("symbol") or "").strip()
                if cid and symbol:
                    self._by_id[cid.lower()] = symbol
                    self._by_symbol.setdefault(symbol.lower(), symbol)
                    self._id_by_symbol.setdefault(symbol.lower(), cid)
            self._loaded = True
            logger.info("CoinGecko /coins/list: %s записей", len(self._by_id))
        except Exception as e:  # noqa: BLE001 — справочник необязателен
            self._retry_after = time.monotonic() + self._cooldown
            logger.warning("Не удалось загрузить CoinGecko /coins/list: %s", e)

    def _fetch(self) -> list[dict]:
        headers = {"User-Agent": COINGECKO_UA}
        key = os.getenv("COINGECKO_DEMO_API_KEY")
        if key:
            headers["x-cg-demo-api-key"] = key
        resp = requests.get(COINGECKO_LIST_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()
