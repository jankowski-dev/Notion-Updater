from config import CurrencyConfig
from updaters.currency import CurrencyUpdater


def _config() -> CurrencyConfig:
    return CurrencyConfig(
        database_id="db",
        code_field="ID_money",
        rate_field="Money_rate",
        update_hours=2,
        cron="",
        city="Минск",
    )


def test_extract_currency_code_mapping():
    updater = CurrencyUpdater(_config())
    assert updater.extract_currency_code({"ID_money": {"type": "number", "number": 145}}) == "USD"
    assert updater.extract_currency_code({"ID_money": {"type": "number", "number": 1}}) == "BYN"


def test_extract_currency_code_unknown_and_wrong_type():
    updater = CurrencyUpdater(_config())
    assert updater.extract_currency_code({"ID_money": {"type": "number", "number": 999}}) is None
    assert updater.extract_currency_code({"ID_money": {"type": "rich_text"}}) is None
    assert updater.extract_currency_code({}) is None


def test_exchange_rates_batch_byn_and_bank(monkeypatch):
    updater = CurrencyUpdater(_config())
    monkeypatch.setattr(updater.parser, "_get_belarusbank_rates", lambda: {"USD": 3.2})
    rates = updater.parser.get_exchange_rates_batch({"USD", "BYN"})
    assert rates["BYN"] == 1.0
    assert rates["USD"] == 3.2


def test_exchange_rates_batch_fixed_fallback(monkeypatch):
    updater = CurrencyUpdater(_config())
    monkeypatch.setattr(updater.parser, "_get_belarusbank_rates", lambda: {})
    rates = updater.parser.get_exchange_rates_batch({"EUR", "XXX"})
    assert rates["EUR"] == 3.40
    assert "XXX" not in rates


def test_dry_run_skips_write(monkeypatch):
    updater = CurrencyUpdater(_config(), dry_run=True)
    called = {"count": 0}
    monkeypatch.setattr("updaters.currency.notion.update_page", lambda *a, **k: called.__setitem__("count", called["count"] + 1))
    assert updater._update_single_page("page1", 3.2) is True
    assert called["count"] == 0
