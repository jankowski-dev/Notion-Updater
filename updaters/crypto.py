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
