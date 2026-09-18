import notion
from config import HabitsConfig
from updaters import habits


def _config() -> HabitsConfig:
    return HabitsConfig(
        database_id="db",
        habits=["Кофе", "Сахар"],
        name_field="Название",
        counter_field="Срок [P]",
        hour=22,
        minute=0,
    )


def _page(page_id: str, name: str, counter: float) -> dict:
    return {
        "id": page_id,
        "properties": {
            "Название": {"type": "title", "title": [{"plain_text": name}]},
            "Срок [P]": {"type": "number", "number": counter},
        },
    }


def test_increments_only_listed_habits(monkeypatch):
    pages = [_page("p1", "Кофе", 5), _page("p2", "Спорт", 1), _page("p3", "Сахар", 0)]
    updates = []

    monkeypatch.setattr(notion, "query_database", lambda *a, **k: pages)
    monkeypatch.setattr(notion, "update_page", lambda page_id, props: updates.append((page_id, props)))

    updated = habits.run(_config())

    assert updated == 2
    assert updates == [
        ("p1", {"Срок [P]": {"number": 6}}),
        ("p3", {"Срок [P]": {"number": 1}}),
    ]


def test_dry_run_does_not_write(monkeypatch):
    pages = [_page("p1", "Кофе", 5)]
    updates = []

    monkeypatch.setattr(notion, "query_database", lambda *a, **k: pages)
    monkeypatch.setattr(notion, "update_page", lambda page_id, props: updates.append(page_id))

    updated = habits.run(_config(), dry_run=True)

    assert updated == 1
    assert updates == []


def test_query_error_returns_zero(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")

    monkeypatch.setattr(notion, "query_database", boom)
    assert habits.run(_config()) == 0
