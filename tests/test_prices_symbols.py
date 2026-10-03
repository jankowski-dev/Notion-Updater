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


def test_coingecko_list_failure_cooldown(monkeypatch):
    cg = CoinGeckoList(cooldown_seconds=300.0)
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("net down")

    monkeypatch.setattr(cg, "_fetch", boom)
    assert cg.symbol_for("bitcoin") is None
    assert cg.symbol_for("solana") is None
    assert calls["n"] == 1  # в пределах cooldown сеть не дёргаем повторно
