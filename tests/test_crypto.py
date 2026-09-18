from updaters.crypto import _symbol_from_props, compute_yesterday_price


def test_compute_yesterday_price_positive_change():
    assert compute_yesterday_price(100, 25) == 80


def test_compute_yesterday_price_negative_change():
    assert compute_yesterday_price(100, -20) == 125


def test_compute_yesterday_price_none_inputs():
    assert compute_yesterday_price(None, 10) is None
    assert compute_yesterday_price(100, None) is None


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
