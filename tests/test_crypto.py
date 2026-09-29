from updaters import crypto
from updaters.crypto import _coingecko_headers, _symbol_from_props, compute_yesterday_price


def test_compute_yesterday_price_positive_change():
    assert compute_yesterday_price(100, 25) == 80


def test_compute_yesterday_price_negative_change():
    assert compute_yesterday_price(100, -20) == 125


def test_compute_yesterday_price_none_inputs():
    assert compute_yesterday_price(None, 10) is None
    assert compute_yesterday_price(100, None) is None


def test_coingecko_headers_default(monkeypatch):
    monkeypatch.delenv("COINGECKO_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("COINGECKO_PRO_API_KEY", raising=False)
    assert _coingecko_headers()["User-Agent"] == "Notion-Updater/1.0"


def test_coingecko_headers_demo_key(monkeypatch):
    monkeypatch.delenv("COINGECKO_PRO_API_KEY", raising=False)
    monkeypatch.setenv("COINGECKO_DEMO_API_KEY", "demo123")
    assert _coingecko_headers()["x-cg-demo-api-key"] == "demo123"


def test_coingecko_headers_pro_key(monkeypatch):
    monkeypatch.delenv("COINGECKO_DEMO_API_KEY", raising=False)
    monkeypatch.setenv("COINGECKO_PRO_API_KEY", "pro123")
    assert _coingecko_headers()["x-cg-pro-api-key"] == "pro123"


def test_symbol_from_props_rich_text():
    props = {"Symbol": {"type": "rich_text", "rich_text": [{"text": {"content": " BTC "}}]}}
    assert _symbol_from_props(props, "Symbol") == "BTC"


def test_symbol_from_props_title():
    props = {"Symbol": {"type": "title", "title": [{"text": {"content": "eth"}}]}}
    assert _symbol_from_props(props, "Symbol") == "eth"


def test_symbol_from_props_empty_and_wrong_type():
    assert _symbol_from_props({}, "Symbol") == ""
    assert _symbol_from_props({"Symbol": {"type": "number"}}, "Symbol") == ""
    assert _symbol_from_props({"Symbol": {"type": "rich_text", "rich_text": []}}, "Symbol") == ""


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self.headers = {}
        self.text = "blocked"
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_markets_returns_none_on_403(monkeypatch):
    monkeypatch.setattr(crypto.requests, "get", lambda *a, **k: _Resp(403))
    monkeypatch.setattr(crypto, "sleep", lambda *a, **k: None)
    assert crypto._fetch_markets(["bitcoin"], 200) is None


def test_fetch_fallback_to_per_coin(monkeypatch):
    def fake_get(url, **kwargs):
        if "markets" in url:
            return _Resp(403)
        return _Resp(200, {"market_data": {"current_price": {"usd": 100.0}, "price_change_percentage_24h": 25.0}})

    monkeypatch.setattr(crypto.requests, "get", fake_get)
    monkeypatch.setattr(crypto, "sleep", lambda *a, **k: None)
    current, yesterday = crypto.fetch_prices_from_coingecko(["bitcoin"], 200)
    assert current["bitcoin"] == 100.0
    assert yesterday["bitcoin"] == 80.0
