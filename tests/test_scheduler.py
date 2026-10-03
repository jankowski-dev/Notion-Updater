from config import Config, CryptoConfig
from scheduler import build_scheduler


class _Engine:
    def set_coins(self, specs):
        pass

    def snapshot(self):
        return {}


def _config():
    return Config(
        notion_token="t",
        timezone="Europe/Minsk",
        log_level="INFO",
        dry_run=True,
        enable_currency=False,
        enable_crypto=True,
        enable_habits=False,
        currency=None,
        crypto=CryptoConfig(
            database_id="db", symbol_field="Symbol", price_field="Price",
            updated_field="Last Updated", yesterday_price_field="Price (Yesterday)",
            tick_seconds=30, resync_seconds=300, providers=["kraken"],
            stale_seconds=300, heartbeat_seconds=0, rest_seconds=60,
        ),
        habits=None,
    )


def test_scheduler_registers_crypto_jobs():
    scheduler = build_scheduler(_config(), engine=_Engine())
    ids = {job.id for job in scheduler.get_jobs()}
    assert ids == {"crypto_write", "crypto_resync", "crypto_rest"}
    scheduler.start(paused=True)
    scheduler.shutdown(wait=False)


def test_scheduler_skips_rest_when_disabled():
    config = _config()
    config.crypto.rest_seconds = 0
    scheduler = build_scheduler(config, engine=_Engine())
    ids = {job.id for job in scheduler.get_jobs()}
    assert ids == {"crypto_write", "crypto_resync"}
    scheduler.start(paused=True)
    scheduler.shutdown(wait=False)
