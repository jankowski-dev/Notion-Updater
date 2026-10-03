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
