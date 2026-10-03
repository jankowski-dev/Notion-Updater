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
