import pytest

from config import ConfigError, load_config

RELEVANT = [
    "NOTION_TOKEN",
    "NOTION_API_KEY",
    "TZ",
    "LOG_LEVEL",
    "DRY_RUN",
    "ENABLE_CURRENCY",
    "ENABLE_CRYPTO",
    "ENABLE_HABITS",
    "CURRENCY_DATABASE_ID",
    "CURRENCY_CODE_FIELD",
    "CURRENCY_RATE_FIELD",
    "CURRENCY_UPDATE_HOURS",
    "CURRENCY_CRON",
    "CURRENCY_CITY",
    "CRYPTO_DATABASE_ID",
    "CRYPTO_SYMBOL_FIELD",
    "CRYPTO_PRICE_FIELD",
    "CRYPTO_UPDATED_FIELD",
    "CRYPTO_YESTERDAY_PRICE_FIELD",
    "CRYPTO_CHUNK_SIZE",
    "CRYPTO_UPDATE_SECONDS",
    "CRYPTO_CRON",
    "HABITS_DATABASE_ID",
    "HABITS_LIST",
    "HABITS_NAME_FIELD",
    "HABITS_COUNTER_FIELD",
    "HABITS_INCREMENT_TIME",
]


@pytest.fixture
def env(monkeypatch):
    for name in RELEVANT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NOTION_TOKEN", "test-token")
    return monkeypatch


def test_all_disabled_returns_none_modules(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("ENABLE_HABITS", "false")
    cfg = load_config()
    assert cfg.currency is None
    assert cfg.crypto is None
    assert cfg.habits is None
    assert cfg.timezone == "Europe/Minsk"


def test_currency_defaults(env):
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("CURRENCY_DATABASE_ID", "db1")
    cfg = load_config()
    assert cfg.currency.database_id == "db1"
    assert cfg.currency.code_field == "ID_money"
    assert cfg.currency.rate_field == "Money_rate"
    assert cfg.currency.update_hours == 2
    assert cfg.currency.cron == ""


def test_crypto_defaults(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("CRYPTO_DATABASE_ID", "db2")
    cfg = load_config()
    assert cfg.crypto.symbol_field == "Symbol"
    assert cfg.crypto.price_field == "Price"
    assert cfg.crypto.updated_field == "Last Updated"
    assert cfg.crypto.yesterday_price_field == "Price (Yesterday)"
    assert cfg.crypto.update_seconds == 300


def test_habits_parsing(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("HABITS_DATABASE_ID", "db3")
    env.setenv("HABITS_LIST", " Курение , Алкоголь,,Кофе ")
    env.setenv("HABITS_INCREMENT_TIME", "21:30")
    cfg = load_config()
    assert cfg.habits.habits == ["Курение", "Алкоголь", "Кофе"]
    assert (cfg.habits.hour, cfg.habits.minute) == (21, 30)


def test_missing_database_id_raises(env):
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("ENABLE_HABITS", "false")
    with pytest.raises(ConfigError):
        load_config()


def test_habits_missing_list_raises(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("HABITS_DATABASE_ID", "db3")
    with pytest.raises(ConfigError):
        load_config()


def test_bad_int_raises(env):
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("CURRENCY_DATABASE_ID", "db1")
    env.setenv("CURRENCY_UPDATE_HOURS", "abc")
    with pytest.raises(ConfigError):
        load_config()


def test_bad_time_raises(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("HABITS_DATABASE_ID", "db3")
    env.setenv("HABITS_LIST", "Кофе")
    env.setenv("HABITS_INCREMENT_TIME", "25:99")
    with pytest.raises(ConfigError):
        load_config()


def test_bad_timezone_raises(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("TZ", "Mars/Olympus")
    with pytest.raises(ConfigError):
        load_config()


def test_dry_run_flag(env):
    env.setenv("ENABLE_CURRENCY", "false")
    env.setenv("ENABLE_CRYPTO", "false")
    env.setenv("ENABLE_HABITS", "false")
    env.setenv("DRY_RUN", "true")
    assert load_config().dry_run is True
