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
