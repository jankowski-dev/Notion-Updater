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


def test_snapshot_prefers_kraken_over_coinbase():
    engine = PriceEngine({"kraken": KrakenProvider(), "coinbase": KrakenProvider()})
    engine.set_coins([
        CoinSpec(page_id="p1", raw_symbol="BTC",
                 candidates=[ResolvedCoin("kraken", "BTC/USD"), ResolvedCoin("coinbase", "BTC-USD")]),
    ])
    engine._prices["kraken:BTC/USD"] = PricePoint(100.0, 75.0, datetime.now(timezone.utc))
    engine._prices["coinbase:BTC-USD"] = PricePoint(200.0, 175.0, datetime.now(timezone.utc))
    assert engine.snapshot()["BTC"].price == 100.0


def test_handle_message_warns_once_per_pair(caplog):
    import logging

    engine = PriceEngine({"kraken": KrakenProvider()})
    raw = (
        '{"method":"subscribe","success":false,"error":"Unknown",'
        '"params":{"channel":"ticker","symbol":["NOPE/USD"]}}'
    )
    with caplog.at_level(logging.WARNING, logger="prices.engine"):
        engine._handle_message(engine._providers["kraken"], raw)
        engine._handle_message(engine._providers["kraken"], raw)
    assert sum("NOPE/USD" in r.message for r in caplog.records) == 1
