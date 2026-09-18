"""Единый клиент Notion API: запросы к базам и страницам, извлечение свойств.

Выделен из Nexter.Bot/notion_api.py и логики currency-updater/crypto-updater.
"""

import os

import requests

NOTION_API_VERSION = "2022-06-28"
NOTION_API_BASE = "https://api.notion.com/v1"


def notion_headers() -> dict:
    api_key = os.environ.get("NOTION_TOKEN") or os.environ.get("NOTION_API_KEY") or ""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_API_VERSION,
    }


def query_database(db_id: str, filter: dict | None = None, page_size: int = 100) -> list[dict]:
    """Возвращает все страницы базы с пагинацией."""
    url = f"{NOTION_API_BASE}/databases/{db_id}/query"
    headers = notion_headers()
    pages: list[dict] = []
    payload: dict = {"page_size": page_size}
    if filter:
        payload["filter"] = filter
    while True:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data.get("next_cursor")
    return pages


def get_page(page_id: str) -> dict:
    url = f"{NOTION_API_BASE}/pages/{page_id}"
    response = requests.get(url, headers=notion_headers(), timeout=15)
    response.raise_for_status()
    return response.json()


def update_page(page_id: str, properties: dict) -> None:
    url = f"{NOTION_API_BASE}/pages/{page_id}"
    response = requests.patch(
        url, headers=notion_headers(), json={"properties": properties}, timeout=15
    )
    response.raise_for_status()


def get_title(props: dict, field: str) -> str:
    arr = props.get(field, {}).get("title", [])
    return arr[0].get("plain_text", "") if arr else ""


def get_rich_text(props: dict, field: str) -> str:
    arr = props.get(field, {}).get("rich_text", [])
    return arr[0].get("plain_text", "") if arr else ""


def get_number(props: dict, field: str) -> float:
    return props.get(field, {}).get("number", 0) or 0


def get_select(props: dict, field: str) -> str:
    sel = props.get(field, {}).get("select")
    return sel["name"] if sel else ""


def _num_to_str(val) -> str:
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def extract_id(props: dict, field: str) -> str:
    """Извлекает значение свойства «ID» с учётом его типа."""
    prop = props.get(field)
    if not prop:
        return ""
    ptype = prop.get("type", "")

    if ptype == "number":
        val = prop.get("number")
        return _num_to_str(val) if val is not None else ""
    if ptype in ("rich_text", "title"):
        arr = prop.get(ptype, [])
        return arr[0].get("plain_text", "") if arr else ""
    if ptype == "unique_id":
        uid = prop.get("unique_id") or {}
        number = uid.get("number")
        if number is None:
            return ""
        prefix = uid.get("prefix")
        return f"{prefix}-{number}" if prefix else str(number)
    if ptype == "formula":
        formula = prop.get("formula") or {}
        ftype = formula.get("type", "")
        val = formula.get(ftype)
        if val is None:
            return ""
        return _num_to_str(val)
    if ptype == "select":
        return get_select(props, field)
    return ""
