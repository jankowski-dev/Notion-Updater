from notion import extract_id, get_number, get_rich_text, get_select, get_title


def test_get_title_and_rich_text():
    props = {
        "Name": {"type": "title", "title": [{"plain_text": "Привычка"}]},
        "Note": {"type": "rich_text", "rich_text": [{"plain_text": "текст"}]},
    }
    assert get_title(props, "Name") == "Привычка"
    assert get_rich_text(props, "Note") == "текст"
    assert get_title(props, "Missing") == ""


def test_get_number_defaults_zero():
    assert get_number({"N": {"number": 5}}, "N") == 5
    assert get_number({"N": {"number": None}}, "N") == 0
    assert get_number({}, "N") == 0


def test_get_select():
    assert get_select({"S": {"select": {"name": "Новая"}}}, "S") == "Новая"
    assert get_select({"S": {"select": None}}, "S") == ""


def test_extract_id_number():
    assert extract_id({"ID": {"type": "number", "number": 42}}, "ID") == "42"
    assert extract_id({"ID": {"type": "number", "number": 42.0}}, "ID") == "42"


def test_extract_id_rich_text_and_title():
    assert extract_id({"ID": {"type": "rich_text", "rich_text": [{"plain_text": "abc"}]}}, "ID") == "abc"
    assert extract_id({"ID": {"type": "title", "title": [{"plain_text": "ttl"}]}}, "ID") == "ttl"


def test_extract_id_unique_id():
    prop = {"ID": {"type": "unique_id", "unique_id": {"prefix": "PRJ", "number": 7}}}
    assert extract_id(prop, "ID") == "PRJ-7"
    prop2 = {"ID": {"type": "unique_id", "unique_id": {"prefix": None, "number": 7}}}
    assert extract_id(prop2, "ID") == "7"


def test_extract_id_formula():
    prop = {"ID": {"type": "formula", "formula": {"type": "number", "number": 3.0}}}
    assert extract_id(prop, "ID") == "3"


def test_extract_id_missing_and_empty():
    assert extract_id({}, "ID") == ""
    assert extract_id({"ID": {"type": "number", "number": None}}, "ID") == ""
    assert extract_id({"ID": {"type": "select", "select": {"name": "X"}}}, "ID") == "X"
