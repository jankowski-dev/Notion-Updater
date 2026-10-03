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
