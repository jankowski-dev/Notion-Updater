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
    rest_seconds = 60


class _Engine:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.coins = None

    def set_coins(self, specs):
        self.coins = specs

    def snapshot(self):
        return self._snapshot


class _CG:
    """Фейковый CoinGeckoList: без сети."""

    def __init__(self, symbols=None, ids=None):
        self._symbols = symbols or {}
        self._ids = ids or {}

    def symbol_for(self, value):
        return self._symbols.get(value)

    def id_for(self, value):
        return self._ids.get(value)


class _Rest:
    """Фейковый CoinGeckoRest: без сети."""

    def __init__(self):
        self.cache = {}
        self.calls = []

    def snapshot(self):
        return dict(self.cache)

    def refresh(self, ids):
        self.calls.append(list(ids))


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


def test_write_tick_heartbeat_writes_only_updated(monkeypatch):
    writes = []
    monkeypatch.setattr("updaters.crypto.notion.update_page", lambda pid, props: writes.append((pid, props)))
    cfg = _Cfg()
    cfg.heartbeat_seconds = 1
    updater = CryptoUpdater(cfg, _Engine({}))
    updater._pages = [("p1", "BTC")]
    updater.engine._snapshot = {"BTC": PricePoint(100.0, 75.0, datetime.now(timezone.utc))}
    updater.write_tick()  # first write
    assert len(writes) == 1

    updater.engine._snapshot = {"BTC": PricePoint(100.0, 75.0, datetime.now(timezone.utc))}
    updater._last_write["p1"] -= 10  # force heartbeat interval to elapse
    result = updater.write_tick()

    assert len(writes) == 2
    assert "Price" not in writes[1][1]  # heartbeat updates only Last Updated
    assert result["heartbeat"] == 1
    assert result["updated"] == 0


def test_write_tick_logs_stale_warning(monkeypatch, caplog):
    import logging

    monkeypatch.setattr("updaters.crypto.notion.update_page", lambda pid, props: None)
    updater = CryptoUpdater(_Cfg(), _Engine({}))
    updater._pages = [("p1", "BTC")]
    with caplog.at_level(logging.WARNING, logger="updaters.crypto"):
        result = updater.write_tick()
    assert result["skipped"] == 1
    assert any("нет свежей цены" in r.message for r in caplog.records)


def test_resync_resolves_records_cg_id_and_refreshes_rest(monkeypatch):
    monkeypatch.setattr("updaters.crypto.notion.query_database", lambda db: [
        {"id": "p1", "properties": {"Symbol": {"type": "rich_text", "rich_text": [{"text": {"content": "BTC"}}]}}},
    ])
    rest = _Rest()
    updater = CryptoUpdater(_Cfg(), _Engine({}), coingecko=_CG(ids={"BTC": "bitcoin"}), rest=rest)
    updater.resync()
    assert [s.raw_symbol for s in updater.engine.coins] == ["BTC"]
    assert updater.engine.coins[0].candidates[0].pair == "BTC/USD"
    assert updater._cg_ids["p1"] == "bitcoin"
    assert rest.calls == [["bitcoin"]]  # BTC нет в ws-снапшоте -> ушёл в REST


def test_resync_includes_rest_only_coin(monkeypatch):
    monkeypatch.setattr("updaters.crypto.notion.query_database", lambda db: [
        {"id": "p1", "properties": {"Symbol": {"type": "rich_text", "rich_text": [{"text": {"content": "orochi-network"}}]}}},
    ])
    rest = _Rest()
    updater = CryptoUpdater(
        _Cfg(), _Engine({}),
        coingecko=_CG(symbols={}, ids={"orochi-network": "orochi-network"}), rest=rest,
    )
    updater.resync()
    # нет ws-пар, но монета записана и ушла в REST-fallback
    assert updater._cg_ids["p1"] == "orochi-network"
    assert rest.calls == [["orochi-network"]]


def test_write_tick_uses_rest_fallback(monkeypatch):
    writes = []
    monkeypatch.setattr("updaters.crypto.notion.update_page", lambda pid, props: writes.append((pid, props)))
    rest = _Rest()
    rest.cache = {"orochi-network": PricePoint(0.1, 0.09, datetime.now(timezone.utc))}
    updater = CryptoUpdater(_Cfg(), _Engine({}), coingecko=_CG(), rest=rest)
    updater._pages = [("p1", "orochi-network")]
    updater._cg_ids = {"p1": "orochi-network"}
    updater.write_tick()
    assert len(writes) == 1
    assert writes[0][1]["Price"]["number"] == 0.1


def test_refresh_rest_skips_covered_and_disabled(monkeypatch):
    rest = _Rest()
    updater = CryptoUpdater(_Cfg(), _Engine({}), coingecko=_CG(), rest=rest)
    updater._pages = [("p1", "BTC"), ("p2", "orochi-network")]
    updater._cg_ids = {"p1": "bitcoin", "p2": "orochi-network"}
    updater.engine._snapshot = {"BTC": PricePoint(1.0, 1.0, datetime.now(timezone.utc))}
    updater.refresh_rest()
    assert rest.calls == [["orochi-network"]]  # BTC покрыт ws -> не запрашиваем

    cfg = _Cfg()
    cfg.rest_seconds = 0
    rest2 = _Rest()
    updater2 = CryptoUpdater(cfg, _Engine({}), coingecko=_CG(), rest=rest2)
    updater2._pages = [("p1", "orochi-network")]
    updater2._cg_ids = {"p1": "orochi-network"}
    updater2.refresh_rest()
    assert rest2.calls == []  # REST выключен
