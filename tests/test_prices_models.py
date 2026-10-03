from datetime import datetime, timezone

from prices.models import CoinSpec, PricePoint, ResolvedCoin


def test_resolved_coin_key():
    c = ResolvedCoin(provider="kraken", pair="BTC/USD")
    assert c.key == "kraken:BTC/USD"


def test_coin_spec_defaults():
    spec = CoinSpec(page_id="p1", raw_symbol="BTC")
    assert spec.candidates == []


def test_price_point_fields():
    ts = datetime.now(timezone.utc)
    p = PricePoint(price=1.5, yesterday=1.4, ts=ts)
    assert (p.price, p.yesterday, p.ts) == (1.5, 1.4, ts)
