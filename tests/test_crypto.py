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
    assert _coingecko_headers()["x_cg_demo_api_key"] == "demo123"


def test_coingecko_headers_pro_key(monkeypatch):
    monkeypatch.delenv("COINGECKO_DEMO_API_KEY", raising=False)
    monkeypatch.setenv("COINGECKO_PRO_API_KEY", "pro123")
    assert _coingecko_headers()["x_cg_pro_api_key"] == "pro123"


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
