"""Обновление цен криптовалют в Notion из websocket-кэша.

HTTP-опрос CoinGecko удалён. Цены берутся из PriceEngine (prices/engine.py);
здесь — только чтение базы, дедуп и запись изменившихся значений.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timezone

import notion
from config import CryptoConfig
from prices.coingecko_rest import CoinGeckoRest
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
    def __init__(
        self,
        config: CryptoConfig,
        engine: PriceEngine,
        dry_run: bool = False,
        coingecko: CoinGeckoList | None = None,
        rest: CoinGeckoRest | None = None,
    ) -> None:
        self.config = config
        self.engine = engine
        self.dry_run = dry_run
        self._coingecko = coingecko or CoinGeckoList()
        self.rest = rest or CoinGeckoRest()
        self._pages: list[tuple[str, str]] = []  # (page_id, raw_symbol)
        self._cg_ids: dict[str, str] = {}  # page_id -> CoinGecko-id (для REST-fallback)
        self._last: dict[str, tuple[float, float | None]] = {}
        self._last_write: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stale_warned: set[str] = set()

    def resync(self) -> None:
        logger.info("Крипта: перечитываю базу Notion %s", self.config.database_id)
        try:
            pages = notion.query_database(self.config.database_id)
        except Exception as e:  # noqa: BLE001
            logger.error("Крипта: ошибка чтения базы Notion: %s", e)
            return

        specs: list[CoinSpec] = []
        page_pairs: list[tuple[str, str]] = []
        cg_ids: dict[str, str] = {}
        for page in pages:
            page_id = page["id"]
            raw = _symbol_from_props(page.get("properties", {}), self.config.symbol_field)
            if not raw:
                logger.warning("Крипта: у страницы %s пустое поле '%s'", page_id, self.config.symbol_field)
                continue
            candidates = resolve_candidates(raw, self.config.providers, self._coingecko.symbol_for)
            cg_id = self._coingecko.id_for(raw)
            if not candidates and not cg_id:
                logger.warning("Крипта: не удалось разрешить символ %r (страница %s)", raw, page_id)
                continue
            specs.append(CoinSpec(page_id=page_id, raw_symbol=raw, candidates=candidates))
            page_pairs.append((page_id, raw))
            if cg_id:
                cg_ids[page_id] = cg_id

        self.engine.set_coins(specs)
        with self._lock:
            removed = {pid for pid, _ in self._pages} - {pid for pid, _ in page_pairs}
            for pid in removed:
                self._last.pop(pid, None)
                self._last_write.pop(pid, None)
                self._stale_warned.discard(pid)
            self._pages = page_pairs
            self._cg_ids = cg_ids
        logger.info("Крипта: страниц с монетами %s", len(specs))
        self.refresh_rest()

    def refresh_rest(self) -> None:
        """Подтягивает CoinGecko /simple/price для монет без websocket-цены."""
        if self.config.rest_seconds <= 0:
            return
        snapshot = self.engine.snapshot()
        with self._lock:
            pages = list(self._pages)
            cg_ids = dict(self._cg_ids)
        ids = [cg_ids[pid] for pid, raw in pages if raw not in snapshot and cg_ids.get(pid)]
        self.rest.refresh(ids)

    def write_tick(self) -> dict:
        ws_prices = self.engine.snapshot()
        rest_prices = self.rest.snapshot()
        with self._lock:
            pages = list(self._pages)
            cg_ids = dict(self._cg_ids)
        now_utc = datetime.now(timezone.utc)
        now_mono = time.monotonic()
        updated = 0
        skipped = 0
        errors = 0
        heartbeat = 0

        for page_id, raw in pages:
            point = ws_prices.get(raw)
            cg_id = cg_ids.get(page_id)
            if point is None and cg_id:
                point = rest_prices.get(cg_id)
            if point is not None and (now_utc - point.ts).total_seconds() > self.config.stale_seconds:
                point = None
            if point is None:
                with self._lock:
                    first_time = page_id not in self._stale_warned
                    self._stale_warned.add(page_id)
                if first_time:
                    logger.warning("Крипта: нет свежей цены для %r (страница %s)", raw, page_id)
                skipped += 1
                continue

            with self._lock:
                self._stale_warned.discard(page_id)
                previous = self._last.get(page_id)

            if previous is not None and _same(previous[0], point.price) and _same(previous[1], point.yesterday):
                hb = self.config.heartbeat_seconds
                with self._lock:
                    last_write = self._last_write.get(page_id, 0.0)
                if hb and (now_mono - last_write) >= hb:
                    if self._write(page_id, point.price, point.yesterday, heartbeat_only=True):
                        with self._lock:
                            self._last_write[page_id] = now_mono
                        heartbeat += 1
                    else:
                        errors += 1
                else:
                    skipped += 1
                continue

            if self._write(page_id, point.price, point.yesterday):
                with self._lock:
                    self._last[page_id] = (point.price, point.yesterday)
                    self._last_write[page_id] = now_mono
                updated += 1
            else:
                errors += 1

        logger.info(
            "Крипта: записано=%s пропущено=%s ошибок=%s пульс=%s (из %s)",
            updated, skipped, errors, heartbeat, len(pages),
        )
        return {"updated": updated, "skipped": skipped, "errors": errors, "heartbeat": heartbeat}

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
