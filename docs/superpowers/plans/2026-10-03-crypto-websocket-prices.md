# Крипта на websocket-ценах — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить опрос CoinGecko в модуле крипты на push-поток websocket (Kraken + Coinbase fallback) с записью в Notion раз в 30с и минимумом запросов.

**Architecture:** Новый пакет `prices/` (модели, разрешение символов, провайдеры, движок на фоновом потоке) отдаёт снимок цен. `updaters/crypto.py` превращается в тонкого «писателя» `CryptoUpdater` с дедупом по цене; `scheduler.py` запускает `crypto_write` (30с) и `crypto_resync` (5 мин) на общем движке. Существующие APScheduler, валюты и привычки не трогаются.

**Tech Stack:** Python 3.11, `websocket-client`, `requests`, APScheduler, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-crypto-websocket-prices-design.md`

---

## Task 0: Зафиксировать реальные семплы провайдеров

Парсинг зависит от точной схемы сообщений — сначала поймаем живые семплы.

**Files:**
- Create: `docs/superpowers/notes/provider-samples.md`

- [ ] **Step 1: Установить websocket-client**

Run: `pip install websocket-client`
Expected: успешная установка.

- [ ] **Step 2: Поймать семпл Kraken v2**

Run:
```bash
python -c "import json,websocket; ws=websocket.create_connection('wss://ws.kraken.com/v2',timeout=10); ws.send(json.dumps({'method':'subscribe','params':{'channel':'ticker','symbol':['BTC/USD','ALGO/USD']}})); print(ws.recv()); print(ws.recv()); print(ws.recv()); ws.close()"
```
Expected: 3 JSON-сообщения; среди них `type: snapshot`/`update` с полями `symbol`, `last`, `change`.

- [ ] **Step 3: Поймать семпл Coinbase**

Run:
```bash
python -c "import json,websocket; ws=websocket.create_connection('wss://ws-feed.exchange.coinbase.com',timeout=10); ws.send(json.dumps({'type':'subscribe','product_ids':['BTC-USD'],'channels':['ticker_batch']})); [print(ws.recv()) for _ in range(5)]; ws.close()"
```
Expected: сообщение с `type: ticker`, `product_id`, `price`, `open_24h`.

- [ ] **Step 4: Записать семплы**

Скопировать по одному реальному сообщению каждого типа (Kraken subscribe-ack, Kraken snapshot, Coinbase subscriptions-ack, Coinbase ticker) в `docs/superpowers/notes/provider-samples.md`. Если поля отличаются от ожидаемых в Task 3 — поправить код парсинга в Task 3 соответственно и отметить расхождение в заметке.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/notes/provider-samples.md
git commit -m "docs: зафиксировать семплы websocket-сообщений Kraken и Coinbase"
```

---

## Task 1: Модели `prices/models.py`

**Files:**
- Create: `prices/__init__.py`
- Create: `prices/models.py`
- Test: `tests/test_prices_models.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone

from prices.models import CoinSpec, PricePoint, ResolvedCoin


def test_resolved_coin_key():
    c = ResolvedCoin(provider="kraken", pair="BTC/USD")
    assert c.key == "kraken:BTC/USD"


def test_coin_spec_defaults():
    spec = CoinSpec(page_id="p1", raw_symbol="BTC")
    assert spec.candidates == []


def test_price_point_fields():
    ts = datetime.now(timezone.utc)
    p = PricePoint(price=1.5, yesterday=1.4, ts=ts)
    assert (p.price, p.yesterday, p.ts) == (1.5, 1.4, ts)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prices_models.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'prices'`.

- [ ] **Step 3: Write minimal implementation**

`prices/__init__.py`:
```python
```
(пустой файл)

`prices/models.py`:
```python
"""Модели слоя рыночных данных."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ResolvedCoin:
    """Конкретный биржевой инструмент у провайдера."""

    provider: str
    pair: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.pair}"


@dataclass
class CoinSpec:
    """Одна строка Notion: что просили и куда это раскладывается."""

    page_id: str
    raw_symbol: str
    candidates: list[ResolvedCoin] = field(default_factory=list)


@dataclass
class PricePoint:
    """Цена и «вчера», полученные из стрима."""

    price: float
    yesterday: float | None
    ts: datetime
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_prices_models.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add prices/__init__.py prices/models.py tests/test_prices_models.py
git commit -m "feat(prices): модели слоя рыночных данных"
```

---

## Task 2: Разрешение символов `prices/symbols.py`

**Files:**
- Create: `prices/symbols.py`
- Test: `tests/test_prices_symbols.py`

- [ ] **Step 1: Write the failing test**

```python
from prices.models import ResolvedCoin
from prices.symbols import CoinGeckoList, parse_explicit_pair, resolve_candidates

PROVIDERS = ["kraken", "coinbase"]


def test_parse_explicit_pair_dash_and_slash():
    assert parse_explicit_pair("BTC-USD") == ("BTC", "USD")
    assert parse_explicit_pair("xbt/usd") == ("XBT", "USD")
    assert parse_explicit_pair("notapair") is None


def test_resolve_ticker_prefers_kraken_usd_then_usdt_then_coinbase():
    got = resolve_candidates("BTC", PROVIDERS)
    assert got == [
        ResolvedCoin("kraken", "BTC/USD"),
        ResolvedCoin("kraken", "BTC/USDT"),
        ResolvedCoin("coinbase", "BTC-USD"),
        ResolvedCoin("coinbase", "BTC-USDT"),
    ]


def test_resolve_explicit_pair_keeps_quote():
    got = resolve_candidates("ETH-USDT", PROVIDERS)
    assert got == [
        ResolvedCoin("kraken", "ETH/USDT"),
        ResolvedCoin("coinbase", "ETH-USDT"),
    ]


def test_resolve_lowercase_uses_lookup():
    got = resolve_candidates("bitcoin", PROVIDERS, lookup=lambda v: "btc" if v == "bitcoin" else None)
    assert got[0] == ResolvedCoin("kraken", "BTC/USD")


def test_resolve_unknown_returns_empty():
    assert resolve_candidates("bitcoin", PROVIDERS, lookup=lambda v: None) == []


def test_coingecko_list_matches_id_and_symbol(monkeypatch):
    cg = CoinGeckoList()
    monkeypatch.setattr(cg, "_fetch", lambda: [{"id": "bitcoin", "symbol": "btc"}])
    assert cg.symbol_for("bitcoin") == "btc"
    assert cg.symbol_for("BTC") == "btc"
    assert cg.symbol_for("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prices_symbols.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'prices.symbols'`.

- [ ] **Step 3: Write minimal implementation**

`prices/symbols.py`:
```python
"""Разрешение значения из Notion в биржевой инструмент.

Порядок: явная пара -> тикер (USD, затем USDT) -> ленивый CoinGecko /coins/list.
"""

from __future__ import annotations

import logging
import os
import re
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


def parse_explicit_pair(value: str) -> tuple[str, str] | None:
    m = _PAIR_RE.match(value.strip())
    if not m:
        return None
    return m.group(1).upper(), m.group(2).upper()


def format_pair(provider: str, base: str, quote: str) -> str:
    return f"{base}{PAIR_SEPARATOR[provider]}{quote}"


def _candidates(base: str, providers: list[str]) -> list[ResolvedCoin]:
    out: list[ResolvedCoin] = []
    for provider in providers:
        for quote in PROVIDER_QUOTES[provider]:
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

    def __init__(self) -> None:
        self._by_id: dict[str, str] = {}
        self._by_symbol: dict[str, str] = {}
        self._loaded = False

    def symbol_for(self, value: str) -> str | None:
        if not self._loaded:
            self._load()
        key = value.strip().lower()
        return self._by_id.get(key) or self._by_symbol.get(key)

    def _load(self) -> None:
        try:
            for item in self._fetch():
                cid = (item.get("id") or "").strip()
                symbol = (item.get("symbol") or "").strip()
                if cid and symbol:
                    self._by_id[cid.lower()] = symbol
                    self._by_symbol.setdefault(symbol.lower(), symbol)
            self._loaded = True
            logger.info("CoinGecko /coins/list: %s записей", len(self._by_id))
        except Exception as e:  # noqa: BLE001 — справочник необязателен
            logger.warning("Не удалось загрузить CoinGecko /coins/list: %s", e)

    def _fetch(self) -> list[dict]:
        headers = {"User-Agent": COINGECKO_UA}
        key = os.getenv("COINGECKO_DEMO_API_KEY")
        if key:
            headers["x-cg-demo-api-key"] = key
        resp = requests.get(COINGECKO_LIST_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_prices_symbols.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add prices/symbols.py tests/test_prices_symbols.py
git commit -m "feat(prices): разрешение символов Notion в биржевые пары"
```

---

## Task 3: Провайдеры `prices/providers.py`

**Files:**
- Create: `prices/providers.py`
- Test: `tests/test_prices_providers.py`

- [ ] **Step 1: Write the failing test**

```python
import json

from prices.providers import CoinbaseProvider, KrakenProvider, build_providers


def test_build_providers_order():
    providers = build_providers(["coinbase", "kraken"])
    assert list(providers) == ["coinbase", "kraken"]
    assert isinstance(providers["kraken"], KrakenProvider)


def test_kraken_parse_snapshot():
    raw = json.dumps({
        "channel": "ticker",
        "type": "snapshot",
        "data": [{"symbol": "BTC/USD", "last": 100.0, "change": 25.0}],
    })
    parsed = KrakenProvider().parse(raw)
    assert parsed is not None
    pair, point = parsed
    assert pair == "BTC/USD"
    assert point.price == 100.0
    assert point.yesterday == 75.0


def test_kraken_ignores_non_ticker_and_bad_json():
    assert KrakenProvider().parse("not json") is None
    assert KrakenProvider().parse(json.dumps({"channel": "heartbeat"})) is None


def test_kraken_subscribe_message():
    msg = json.loads(KrakenProvider().subscribe_message(["BTC/USD"]))
    assert msg == {"method": "subscribe", "params": {"channel": "ticker", "symbol": ["BTC/USD"]}}


def test_kraken_parse_error():
    raw = json.dumps({"method": "subscribe", "success": False, "error": "Unknown symbol",
                      "params": {"channel": "ticker", "symbol": ["NOPE/USD"]}})
    assert KrakenProvider().parse_error(raw) == "NOPE/USD"


def test_coinbase_parse_ticker_with_open_24h():
    raw = json.dumps({"type": "ticker", "product_id": "BTC-USD", "price": "100.0", "open_24h": "75.0"})
    parsed = CoinbaseProvider().parse(raw)
    assert parsed is not None
    pair, point = parsed
    assert pair == "BTC-USD"
    assert point.price == 100.0
    assert point.yesterday == 75.0


def test_coinbase_parse_without_open_24h():
    raw = json.dumps({"type": "ticker", "product_id": "BTC-USD", "price": "100.0"})
    _, point = CoinbaseProvider().parse(raw)
    assert point.yesterday is None


def test_coinbase_subscribe_message():
    msg = json.loads(CoinbaseProvider().subscribe_message(["BTC-USD"]))
    assert msg == {"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker_batch"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prices_providers.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'prices.providers'`.

- [ ] **Step 3: Write minimal implementation**

`prices/providers.py`:
```python
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


def build_providers(names: list[str]) -> dict[str, Provider]:
    return {name: _PROVIDER_CLASSES[name]() for name in names}
```

Note: если семплы из Task 0 показали `type: ticker_batch` вместо `ticker` — учтено; если поле «вчера» называется иначе — поправить `parse` и тест.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_prices_providers.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add prices/providers.py tests/test_prices_providers.py
git commit -m "feat(prices): провайдеры Kraken и Coinbase"
```

---

## Task 4: Движок `prices/engine.py`

**Files:**
- Create: `prices/engine.py`
- Test: `tests/test_prices_engine.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timedelta, timezone

from prices.engine import PriceEngine
from prices.models import CoinSpec, PricePoint, ResolvedCoin
from prices.providers import KrakenProvider


class FakeWs:
    def __init__(self):
        self.sent = []
        self.closed = False

    def settimeout(self, t):
        pass

    def send(self, raw):
        self.sent.append(raw)

    def recv(self):
        raise TimeoutError("no more")

    def close(self):
        self.closed = True


def test_set_coins_computes_needed_pairs():
    engine = PriceEngine({"kraken": KrakenProvider()})
    engine.set_coins([
        CoinSpec(page_id="p1", raw_symbol="BTC",
                 candidates=[ResolvedCoin("kraken", "BTC/USD"), ResolvedCoin("coinbase", "BTC-USD")]),
    ])
    assert engine.needed_pairs("kraken") == {"BTC/USD"}


def test_sync_subscriptions_sends_subscribe_and_unsubscribe():
    engine = PriceEngine({"kraken": KrakenProvider()})
    engine.set_coins([
        CoinSpec(page_id="p1", raw_symbol="BTC", candidates=[ResolvedCoin("kraken", "BTC/USD")]),
    ])
    ws = FakeWs()
    engine._sync_subscriptions(ws, "kraken", engine._providers["kraken"])
    assert any("BTC/USD" in s for s in ws.sent)
    engine.set_coins([])
    engine._sync_subscriptions(ws, "kraken", engine._providers["kraken"])
    assert any("unsubscribe" in s for s in ws.sent)


def test_snapshot_picks_first_fresh_candidate():
    engine = PriceEngine({"kraken": KrakenProvider(), "coinbase": KrakenProvider()})
    engine.set_coins([
        CoinSpec(page_id="p1", raw_symbol="BTC",
                 candidates=[ResolvedCoin("kraken", "BTC/USD"), ResolvedCoin("coinbase", "BTC-USD")]),
    ])
    engine._prices["coinbase:BTC-USD"] = PricePoint(100.0, 75.0, datetime.now(timezone.utc))
    snap = engine.snapshot()
    assert snap["BTC"].price == 100.0


def test_snapshot_skips_stale():
    engine = PriceEngine({"kraken": KrakenProvider()}, stale_seconds=300)
    engine.set_coins([
        CoinSpec(page_id="p1", raw_symbol="BTC", candidates=[ResolvedCoin("kraken", "BTC/USD")]),
    ])
    engine._prices["kraken:BTC/USD"] = PricePoint(
        100.0, None, datetime.now(timezone.utc) - timedelta(seconds=1000)
    )
    assert engine.snapshot() == {}


def test_handle_message_updates_prices():
    engine = PriceEngine({"kraken": KrakenProvider()})
    raw = '{"channel":"ticker","type":"update","data":[{"symbol":"BTC/USD","last":10,"change":1}]}'
    engine._handle_message(engine._providers["kraken"], raw)
    assert engine._prices["kraken:BTC/USD"].price == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_prices_engine.py -v`
Expected: FAIL с `ModuleNotFoundError: No module named 'prices.engine'`.

- [ ] **Step 3: Write minimal implementation**

`prices/engine.py`:
```python
"""Движок цен: фоновые потоки на провайдера, кэш последних цен, подписки."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timezone

import websocket

from prices.models import CoinSpec, PricePoint, ResolvedCoin
from prices.providers import Provider

logger = logging.getLogger(__name__)


class PriceEngine:
    def __init__(
        self,
        providers: dict[str, Provider],
        *,
        stale_seconds: int = 300,
        idle_timeout: float = 90.0,
        connect=None,
    ) -> None:
        self._providers = providers
        self._stale_seconds = stale_seconds
        self._idle_timeout = idle_timeout
        self._connect = connect or self._default_connect
        self._lock = threading.Lock()
        self._prices: dict[str, PricePoint] = {}
        self._desired: dict[str, list[ResolvedCoin]] = {}
        self._needed: dict[str, set[str]] = {name: set() for name in providers}
        self._subscribed: dict[str, set[str]] = {name: set() for name in providers}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ---- lifecycle ----
    def start(self) -> None:
        for name in self._providers:
            thread = threading.Thread(
                target=self._provider_loop, args=(name,), name=f"prices-{name}", daemon=True
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=5)

    # ---- public API ----
    def set_coins(self, specs: list[CoinSpec]) -> None:
        desired: dict[str, list[ResolvedCoin]] = {spec.raw_symbol: spec.candidates for spec in specs}
        with self._lock:
            self._desired = desired
            for name in self._needed:
                self._needed[name] = {
                    candidate.pair
                    for candidates in desired.values()
                    for candidate in candidates
                    if candidate.provider == name
                }

    def needed_pairs(self, provider: str) -> set[str]:
        with self._lock:
            return set(self._needed[provider])

    def snapshot(self) -> dict[str, PricePoint]:
        now = datetime.now(timezone.utc)
        with self._lock:
            desired = dict(self._desired)
            prices = dict(self._prices)
        result: dict[str, PricePoint] = {}
        for raw, candidates in desired.items():
            for candidate in candidates:
                point = prices.get(candidate.key)
                if point is not None and (now - point.ts).total_seconds() <= self._stale_seconds:
                    result[raw] = point
                    break
        return result

    # ---- internals ----
    def _default_connect(self, provider: Provider):
        return websocket.create_connection(provider.ws_url, timeout=self._idle_timeout)

    def _provider_loop(self, name: str) -> None:
        provider = self._providers[name]
        backoff = 1.0
        while not self._stop.is_set():
            ws = None
            try:
                ws = self._connect(provider)
                ws.settimeout(1.0)
                logger.info("Провайдер %s: подключён (%s)", name, provider.ws_url)
                self._sync_subscriptions(ws, name, provider)
                backoff = 1.0
                last_msg = time.monotonic()
                while not self._stop.is_set():
                    if self._pending_sync(name):
                        self._sync_subscriptions(ws, name, provider)
                    try:
                        raw = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        if time.monotonic() - last_msg > self._idle_timeout:
                            raise TimeoutError("нет сообщений от провайдера")
                        continue
                    last_msg = time.monotonic()
                    self._handle_message(provider, raw)
            except Exception as e:  # noqa: BLE001 — поток не должен падать
                if self._stop.is_set():
                    break
                wait = backoff + random.uniform(0, backoff / 2)
                logger.warning("Провайдер %s: ошибка (%s), переподключение через %.0fс", name, e, wait)
                self._stop.wait(wait)
                backoff = min(backoff * 2, 60.0)
            finally:
                if ws is not None:
                    try:
                        ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                with self._lock:
                    self._subscribed[name].clear()

    def _pending_sync(self, name: str) -> bool:
        with self._lock:
            return set(self._needed[name]) != set(self._subscribed[name])

    def _sync_subscriptions(self, ws, name: str, provider: Provider) -> None:
        with self._lock:
            target = set(self._needed[name])
            current = set(self._subscribed[name])
        added = target - current
        removed = current - target
        if added:
            ws.send(provider.subscribe_message(sorted(added)))
            logger.info("Провайдер %s: подписка на %s", name, sorted(added))
        if removed:
            ws.send(provider.unsubscribe_message(sorted(removed)))
            logger.info("Провайдер %s: отписка от %s", name, sorted(removed))
        with self._lock:
            self._subscribed[name] = set(target)

    def _handle_message(self, provider: Provider, raw: str) -> None:
        parsed = provider.parse(raw)
        if parsed is not None:
            pair, point = parsed
            key = ResolvedCoin(provider.name, pair).key
            with self._lock:
                self._prices[key] = point
            return
        error_pair = provider.parse_error(raw)
        if error_pair is not None:
            logger.warning("Провайдер %s: ошибка подписки на %r", provider.name, error_pair)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_prices_engine.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add prices/engine.py tests/test_prices_engine.py
git commit -m "feat(prices): движок websocket с кэшем цен и подписками"
```

---

## Task 5: Конфигурация крипты

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write the failing test**

В `tests/test_config.py` заменить `test_crypto_defaults` и добавить тесты:

```python
def test_crypto_defaults(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("CRYPTO_DATABASE_ID", "db2")
    cfg = load_config()
    assert cfg.crypto.symbol_field == "Symbol"
    assert cfg.crypto.price_field == "Price"
    assert cfg.crypto.updated_field == "Last Updated"
    assert cfg.crypto.yesterday_price_field == "Price (Yesterday)"
    assert cfg.crypto.tick_seconds == 30
    assert cfg.crypto.resync_seconds == 300
    assert cfg.crypto.providers == ["kraken", "coinbase"]
    assert cfg.crypto.stale_seconds == 300
    assert cfg.crypto.heartbeat_seconds == 0


def test_crypto_tick_clamped_to_20(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("CRYPTO_DATABASE_ID", "db2")
    env.setenv("CRYPTO_TICK_SECONDS", "5")
    assert load_config().crypto.tick_seconds == 20


def test_crypto_providers_parsed(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("CRYPTO_DATABASE_ID", "db2")
    env.setenv("CRYPTO_PROVIDERS", "coinbase")
    assert load_config().crypto.providers == ["coinbase"]


def test_crypto_unknown_provider_raises(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("CRYPTO_DATABASE_ID", "db2")
    env.setenv("CRYPTO_PROVIDERS", "binance")
    with pytest.raises(ConfigError):
        load_config()
```

В список `RELEVANT` добавить `CRYPTO_TICK_SECONDS`, `CRYPTO_RESYNC_SECONDS`, `CRYPTO_PROVIDERS`, `CRYPTO_STALE_SECONDS`, `CRYPTO_HEARTBEAT_SECONDS`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'CryptoConfig' object has no attribute 'tick_seconds'`.

- [ ] **Step 3: Write minimal implementation**

В `config.py` заменить dataclass `CryptoConfig` и `parse_crypto_config`, добавить логгер и парсер провайдеров:

```python
import logging
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)
```

```python
@dataclass
class CryptoConfig:
    database_id: str
    symbol_field: str
    price_field: str
    updated_field: str
    yesterday_price_field: str
    tick_seconds: int
    resync_seconds: int
    providers: list[str]
    stale_seconds: int
    heartbeat_seconds: int


def _parse_providers(value: str) -> list[str]:
    known = {"kraken", "coinbase"}
    result = [item.strip().lower() for item in value.split(",") if item.strip()]
    unknown = [item for item in result if item not in known]
    if unknown:
        raise ConfigError(f"CRYPTO_PROVIDERS: неизвестные провайдеры {unknown}; допустимы {sorted(known)}")
    if not result:
        raise ConfigError("CRYPTO_PROVIDERS: пусто")
    return result
```

```python
def parse_crypto_config() -> CryptoConfig | None:
    if not _get_bool("ENABLE_CRYPTO", True):
        return None
    for deprecated in ("CRYPTO_UPDATE_SECONDS", "CRYPTO_CHUNK_SIZE", "CRYPTO_CRON"):
        if _get_str(deprecated):
            logger.warning("%s устарела и игнорируется (крипта перешла на websocket)", deprecated)
    return CryptoConfig(
        database_id=_require("CRYPTO_DATABASE_ID", _get_str("CRYPTO_DATABASE_ID")),
        symbol_field=_get_str("CRYPTO_SYMBOL_FIELD", "Symbol"),
        price_field=_get_str("CRYPTO_PRICE_FIELD", "Price"),
        updated_field=_get_str("CRYPTO_UPDATED_FIELD", "Last Updated"),
        yesterday_price_field=_get_str("CRYPTO_YESTERDAY_PRICE_FIELD", "Price (Yesterday)"),
        tick_seconds=max(20, _get_int("CRYPTO_TICK_SECONDS", 30)),
        resync_seconds=_get_int("CRYPTO_RESYNC_SECONDS", 300),
        providers=_parse_providers(_get_str("CRYPTO_PROVIDERS", "kraken,coinbase")),
        stale_seconds=_get_int("CRYPTO_STALE_SECONDS", 300),
        heartbeat_seconds=_get_int("CRYPTO_HEARTBEAT_SECONDS", 0),
    )
```

В `.env.example` заменить блок крипты:

```
# ---- Крипта (ENABLE_CRYPTO=true) ----
CRYPTO_DATABASE_ID=
CRYPTO_SYMBOL_FIELD=Symbol
CRYPTO_PRICE_FIELD=Price
CRYPTO_UPDATED_FIELD=Last Updated
CRYPTO_YESTERDAY_PRICE_FIELD=Price (Yesterday)
CRYPTO_TICK_SECONDS=30
CRYPTO_RESYNC_SECONDS=300
CRYPTO_PROVIDERS=kraken,coinbase
CRYPTO_STALE_SECONDS=300
CRYPTO_HEARTBEAT_SECONDS=0
COINGECKO_DEMO_API_KEY=
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (все тесты зелёные).

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py .env.example
git commit -m "feat(config): параметры websocket-крипты, deprecate poll-переменных"
```

---

## Task 6: `CryptoUpdater` — запись и дедуп

**Files:**
- Rewrite: `updaters/crypto.py`
- Rewrite: `tests/test_crypto.py`

Полный текст `updaters/crypto.py`:

```python
"""Обновление цен криптовалют в Notion из websocket-кэша.

HTTP-опрос CoinGecko удалён. Цены берутся из PriceEngine (prices/engine.py);
здесь — только чтение базы, дедуп и запись изменившихся значений.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

import notion
from config import CryptoConfig
from prices.engine import PriceEngine
from prices.models import CoinSpec
from prices.symbols import CoinGeckoList, resolve_candidates

logger = logging.getLogger(__name__)


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
    return (arr[0].get("text", {}).get("content", "") or "").strip()


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)


class CryptoUpdater:
    def __init__(self, config: CryptoConfig, engine: PriceEngine, dry_run: bool = False) -> None:
        self.config = config
        self.engine = engine
        self.dry_run = dry_run
        self._coingecko = CoinGeckoList()
        self._pages: list[tuple[str, str]] = []  # (page_id, raw_symbol)
        self._last: dict[str, tuple[float, float | None]] = {}
        self._last_write: dict[str, float] = {}

    def resync(self) -> None:
        logger.info("Крипта: перечитываю базу Notion %s", self.config.database_id)
        try:
            pages = notion.query_database(self.config.database_id)
        except Exception as e:  # noqa: BLE001
            logger.error("Крипта: ошибка чтения базы Notion: %s", e)
            return

        specs: list[CoinSpec] = []
        page_pairs: list[tuple[str, str]] = []
        for page in pages:
            page_id = page["id"]
            raw = _symbol_from_props(page.get("properties", {}), self.config.symbol_field)
            if not raw:
                logger.warning("Крипта: у страницы %s пустое поле '%s'", page_id, self.config.symbol_field)
                continue
            candidates = resolve_candidates(raw, self.config.providers, self._coingecko.symbol_for)
            if not candidates:
                logger.warning("Крипта: не удалось разрешить символ %r (страница %s)", raw, page_id)
                continue
            specs.append(CoinSpec(page_id=page_id, raw_symbol=raw, candidates=candidates))
            page_pairs.append((page_id, raw))

        self.engine.set_coins(specs)
        removed = {pid for pid, _ in self._pages} - {pid for pid, _ in page_pairs}
        for pid in removed:
            self._last.pop(pid, None)
            self._last_write.pop(pid, None)
        self._pages = page_pairs
        logger.info("Крипта: страниц с монетами %s, подписок %s", len(specs), len(specs))

    def write_tick(self) -> dict:
        snapshot = self.engine.snapshot()
        now = datetime.now(timezone.utc)
        now_mono = now.timestamp()
        updated = 0
        skipped = 0
        errors = 0

        for page_id, raw in self._pages:
            point = snapshot.get(raw)
            if point is None:
                skipped += 1
                continue

            previous = self._last.get(page_id)
            if previous is not None and _same(previous[0], point.price) and _same(previous[1], point.yesterday):
                heartbeat = self.config.heartbeat_seconds
                last_write = self._last_write.get(page_id, 0.0)
                if heartbeat and (now_mono - last_write) >= heartbeat:
                    if self._write(page_id, point.price, point.yesterday, heartbeat_only=True):
                        updated += 1
                        self._last_write[page_id] = now_mono
                    else:
                        errors += 1
                else:
                    skipped += 1
                continue

            if self._write(page_id, point.price, point.yesterday):
                updated += 1
                self._last[page_id] = (point.price, point.yesterday)
                self._last_write[page_id] = now_mono
            else:
                errors += 1

        logger.info("Крипта: записано=%s пропущено=%s ошибок=%s (из %s)", updated, skipped, errors, len(self._pages))
        return {"updated": updated, "skipped": skipped, "errors": errors}

    def _write(self, page_id: str, price: float, yesterday: float | None, heartbeat_only: bool = False) -> bool:
        props: dict = {self.config.updated_field: {"date": {"start": datetime.now(timezone.utc).isoformat()}}}
        if not heartbeat_only:
            props[self.config.price_field] = {"number": float(price)}
            if yesterday is not None:
                props[self.config.yesterday_price_field] = {"number": float(yesterday)}
        if self.dry_run:
            logger.info("[DRY_RUN] Крипта: страница %s -> %s", page_id, props)
            return True
        try:
            notion.update_page(page_id, props)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("Крипта: ошибка записи страницы %s: %s", page_id, e)
            return False
```

`tests/test_crypto.py` (полностью):
```python
from datetime import datetime, timezone

from prices.models import PricePoint
from updaters.crypto import CryptoUpdater, _same, _symbol_from_props


class _Cfg:
    database_id = "db"
    symbol_field = "Symbol"
    price_field = "Price"
    updated_field = "Last Updated"
    yesterday_price_field = "Price (Yesterday)"
    tick_seconds = 30
    resync_seconds = 300
    providers = ["kraken"]
    stale_seconds = 300
    heartbeat_seconds = 0


class _Engine:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.coins = None

    def set_coins(self, specs):
        self.coins = specs

    def snapshot(self):
        return self._snapshot


def test_symbol_from_props_rich_text_and_title():
    assert _symbol_from_props({"Symbol": {"type": "rich_text", "rich_text": [{"text": {"content": " BTC "}}]}}, "Symbol") == "BTC"
    assert _symbol_from_props({"Symbol": {"type": "title", "title": [{"text": {"content": "eth"}}]}}, "Symbol") == "eth"
    assert _symbol_from_props({}, "Symbol") == ""


def test_same_handles_none_and_close():
    assert _same(None, None)
    assert not _same(1.0, None)
    assert _same(1.0000000001, 1.0)
    assert not _same(1.0, 1.1)


def test_write_tick_writes_changed_and_skips_unchanged(monkeypatch):
    writes = []
    monkeypatch.setattr("updaters.crypto.notion.update_page", lambda pid, props: writes.append((pid, props)))
    updater = CryptoUpdater(_Cfg(), _Engine({}))
    updater._pages = [("p1", "BTC")]

    updater.engine._snapshot = {"BTC": PricePoint(100.0, 75.0, datetime.now(timezone.utc))}
    updater.write_tick()
    assert len(writes) == 1
    assert writes[0][1]["Price"]["number"] == 100.0

    updater.engine._snapshot = {"BTC": PricePoint(100.0, 75.0, datetime.now(timezone.utc))}
    updater.write_tick()
    assert len(writes) == 1  # без изменений — не пишем


def test_write_tick_skips_missing_price(monkeypatch):
    writes = []
    monkeypatch.setattr("updaters.crypto.notion.update_page", lambda pid, props: writes.append(pid))
    updater = CryptoUpdater(_Cfg(), _Engine({}))
    updater._pages = [("p1", "BTC")]
    updater.write_tick()
    assert writes == []


def test_resync_resolves_and_sets_coins(monkeypatch):
    monkeypatch.setattr("updaters.crypto.notion.query_database", lambda db: [
        {"id": "p1", "properties": {"Symbol": {"type": "rich_text", "rich_text": [{"text": {"content": "BTC"}}]}}},
    ])
    updater = CryptoUpdater(_Cfg(), _Engine({}))
    updater.resync()
    assert [s.raw_symbol for s in updater.engine.coins] == ["BTC"]
    assert updater.engine.coins[0].candidates[0].pair == "BTC/USD"
```

- [ ] **Step 1: Заменить тест и убедиться, что падает**

Run: `python -m pytest tests/test_crypto.py -v`
Expected: FAIL — старые импорты (`_coingecko_headers`) отсутствуют / `CryptoUpdater` не найден.

- [ ] **Step 2: Записать реализацию**

Записать `updaters/crypto.py` и `tests/test_crypto.py` из блоков выше.

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_crypto.py -v`
Expected: PASS (5 passed).

- [ ] **Step 4: Commit**

```bash
git add updaters/crypto.py tests/test_crypto.py
git commit -m "feat(crypto): писатель Notion с дедупом поверх websocket-кэша"
```

---

## Task 7: Подключение к планировщику и точке входа

**Files:**
- Modify: `scheduler.py`
- Modify: `main.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

`tests/test_scheduler.py`:
```python
from config import Config, CryptoConfig, CurrencyConfig, HabitsConfig
from scheduler import build_scheduler


class _Engine:
    def set_coins(self, specs):
        pass

    def snapshot(self):
        return {}


def _config():
    return Config(
        notion_token="t",
        timezone="Europe/Minsk",
        log_level="INFO",
        dry_run=True,
        enable_currency=False,
        enable_crypto=True,
        enable_habits=False,
        currency=None,
        crypto=CryptoConfig(
            database_id="db", symbol_field="Symbol", price_field="Price",
            updated_field="Last Updated", yesterday_price_field="Price (Yesterday)",
            tick_seconds=30, resync_seconds=300, providers=["kraken"],
            stale_seconds=300, heartbeat_seconds=0,
        ),
        habits=None,
    )


def test_scheduler_registers_crypto_jobs():
    scheduler = build_scheduler(_config(), engine=_Engine())
    ids = {job.id for job in scheduler.get_jobs()}
    assert ids == {"crypto_write", "crypto_resync"}
    scheduler.shutdown(wait=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `build_scheduler() got an unexpected keyword argument 'engine'`.

- [ ] **Step 3: Write minimal implementation**

В `scheduler.py`:

Заменить импорт крипты и функцию `_job_crypto`, а `build_scheduler` — на версию с `engine`:

```python
from config import Config
from prices.engine import PriceEngine
from updaters import currency, habits
from updaters.crypto import CryptoUpdater
```

Удалить `_job_crypto`. В `build_scheduler`:

```python
def build_scheduler(config: Config, engine: PriceEngine | None = None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=ZoneInfo(config.timezone))
    logger.info("Часовой пояс планировщика: %s", config.timezone)

    if config.enable_currency and config.currency:
        _add_cron_or_interval(
            scheduler,
            lambda: _job_currency(config),
            "currency",
            config.currency.cron,
            {"hours": config.currency.update_hours},
        )

    if config.enable_crypto and config.crypto and engine is not None:
        updater = CryptoUpdater(config.crypto, engine, dry_run=config.dry_run)
        now = datetime.now(scheduler.timezone)

        def _wrap(action, label):
            def _run():
                result = action()
                logger.info(
                    "Крипта[%s]: записано=%s пропущено=%s ошибок=%s",
                    label, result["updated"], result["skipped"], result["errors"],
                )
            return _run

        scheduler.add_job(
            _wrap(updater.write_tick, "write"),
            "interval",
            id="crypto_write",
            replace_existing=True,
            seconds=config.crypto.tick_seconds,
            next_run_time=now,
            **_JOB_DEFAULTS,
        )
        scheduler.add_job(
            _wrap(updater.resync, "resync"),
            "interval",
            id="crypto_resync",
            replace_existing=True,
            seconds=config.crypto.resync_seconds,
            next_run_time=now,
            **_JOB_DEFAULTS,
        )
        logger.info(
            "crypto_write: каждые %sс; crypto_resync: каждые %sс",
            config.crypto.tick_seconds, config.crypto.resync_seconds,
        )

    if config.enable_habits and config.habits:
        # ... без изменений ...
```

Note: `updater.resync` возвращает `None`, поэтому `_wrap` должен уметь печатать без полей. Заменить логирование на безопасное:

```python
        def _wrap(action, label):
            def _run():
                result = action()
                if isinstance(result, dict):
                    logger.info(
                        "Крипта[%s]: записано=%s пропущено=%s ошибок=%s",
                        label, result["updated"], result["skipped"], result["errors"],
                    )
                else:
                    logger.info("Крипта[%s]: готово", label)
            return _run
```

В `main.py`:

```python
from prices.engine import PriceEngine
from prices.providers import build_providers
from scheduler import build_scheduler
```

После `config = load_config()` и логов, перед `build_scheduler`:

```python
    engine = None
    if config.enable_crypto and config.crypto:
        providers = build_providers(config.crypto.providers)
        engine = PriceEngine(providers, stale_seconds=config.crypto.stale_seconds)
        engine.start()

    scheduler = build_scheduler(config, engine=engine)
```

В `finally`:

```python
    finally:
        scheduler.shutdown(wait=False)
        if engine is not None:
            engine.stop()
        logger.info("Остановлено.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest -q`
Expected: PASS (все тесты зелёные).

- [ ] **Step 5: Commit**

```bash
git add scheduler.py main.py tests/test_scheduler.py
git commit -m "feat: запуск websocket-движка и задач crypto_write/crypto_resync"
```

---

## Task 8: Зависимости, README, финальная проверка

**Files:**
- Modify: `requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: Добавить зависимость**

`requirements.txt`:
```
requests>=2.31.0
websocket-client>=1.7.0
APScheduler>=3.10,<4
python-dotenv>=1.0.0
```

Run: `pip install -r requirements-dev.txt`
Expected: установка без ошибок.

- [ ] **Step 2: Обновить README**

В таблицу модулей и раздел «Крипта» внести:
- источник — websocket Kraken + Coinbase fallback;
- новые переменные (`CRYPTO_TICK_SECONDS`, `CRYPTO_RESYNC_SECONDS`, `CRYPTO_PROVIDERS`, `CRYPTO_STALE_SECONDS`, `CRYPTO_HEARTBEAT_SECONDS`);
- убрать `CRYPTO_CHUNK_SIZE` / `CRYPTO_UPDATE_SECONDS` / `CRYPTO_CRON` из таблицы;
- описать поведение: push-цены, запись раз в 30с только по изменившимся, resync базы раз в 5 мин, `Symbol` понимает пару/тикер/CoinGecko-id.

- [ ] **Step 3: Полный прогон тестов**

Run: `python -m pytest -q`
Expected: все зелёные, без обращений к сети.

- [ ] **Step 4: Ручная проверка (DRY_RUN)**

Run (bash):
```bash
DRY_RUN=true ENABLE_CURRENCY=false ENABLE_HABITS=false CRYPTO_DATABASE_ID=<id> NOTION_TOKEN=<token> python main.py
```
Expected в логах: `Провайдер kraken: подключён`, `подписка на [...]`, `Крипта: перечитываю базу`, `[DRY_RUN] Крипта: страница ... -> {...}`. Процесс реагирует на Ctrl+C.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt README.md
git commit -m "docs: описать websocket-крипту, обновить зависимости и README"
```

---

## Self-review checklist (для исполнителя)

- Покрытие спека: push-стрим (Task 3–4), fallback Kraken→Coinbase (Task 2, 4), «без танцев» через resync (Task 6), дедуп/порог 30с (Task 5–6), staleness/reconnect (Task 4), конфиг (Task 5), тесты без сети (Task 1–7).
- Типы согласованы: `ResolvedCoin(provider, pair).key`, `CoinSpec.candidates`, `PricePoint(price, yesterday, ts)`, `CryptoUpdater.resync/write_tick`.
- Старый код CoinGecko-опроса полностью удалён из `updaters/crypto.py`.
