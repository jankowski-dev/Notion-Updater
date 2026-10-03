"""Websocket-провайдеры цен: Kraken (основной) и Coinbase (fallback)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from prices.models import PricePoint

logger = logging.getLogger(__name__)


class Provider:
    name = ""
    ws_url = ""

    def subscribe_message(self, pairs: list[str]) -> str:
        raise NotImplementedError

    def unsubscribe_message(self, pairs: list[str]) -> str:
        raise NotImplementedError

    def parse(self, raw: str) -> tuple[str, PricePoint] | None:
        raise NotImplementedError

    def parse_error(self, raw: str) -> str | None:
        return None


class KrakenProvider(Provider):
    name = "kraken"
    ws_url = "wss://ws.kraken.com/v2"

    def subscribe_message(self, pairs: list[str]) -> str:
        return json.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": pairs}})

    def unsubscribe_message(self, pairs: list[str]) -> str:
        return json.dumps({"method": "unsubscribe", "params": {"channel": "ticker", "symbol": pairs}})

    def parse(self, raw: str) -> tuple[str, PricePoint] | None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(msg, dict) or msg.get("channel") != "ticker":
            return None
        for item in msg.get("data", []):
            pair = item.get("symbol")
            last = item.get("last")
            if pair is None or last is None:
                continue
            change = item.get("change")
            yesterday = (float(last) - float(change)) if change is not None else None
            return pair, PricePoint(float(last), yesterday, datetime.now(timezone.utc))
        return None

    def parse_error(self, raw: str) -> str | None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if isinstance(msg, dict) and msg.get("success") is False and msg.get("method") == "subscribe":
            pairs = (msg.get("params") or {}).get("symbol") or []
            return pairs[0] if pairs else ""
        return None


class CoinbaseProvider(Provider):
    name = "coinbase"
    ws_url = "wss://ws-feed.exchange.coinbase.com"

    def subscribe_message(self, pairs: list[str]) -> str:
        return json.dumps({"type": "subscribe", "product_ids": pairs, "channels": ["ticker_batch"]})

    def unsubscribe_message(self, pairs: list[str]) -> str:
        return json.dumps({"type": "unsubscribe", "product_ids": pairs, "channels": ["ticker_batch"]})

    def parse(self, raw: str) -> tuple[str, PricePoint] | None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if not isinstance(msg, dict) or msg.get("type") not in ("ticker", "ticker_batch"):
            return None
        pair = msg.get("product_id")
        price = msg.get("price")
        if pair is None or price is None:
            return None
        open24 = msg.get("open_24h")
        yesterday = float(open24) if open24 is not None else None
        return pair, PricePoint(float(price), yesterday, datetime.now(timezone.utc))

    def parse_error(self, raw: str) -> str | None:
        try:
            msg = json.loads(raw)
        except (ValueError, TypeError):
            return None
        if isinstance(msg, dict) and msg.get("type") == "error":
            return msg.get("product_id") or ""
        return None


_PROVIDER_CLASSES = {"kraken": KrakenProvider, "coinbase": CoinbaseProvider}
PROVIDER_NAMES = frozenset(_PROVIDER_CLASSES)


def build_providers(names: list[str]) -> dict[str, Provider]:
    return {name: _PROVIDER_CLASSES[name]() for name in names}
