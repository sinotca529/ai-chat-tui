from datetime import datetime, timedelta, timezone

from infrastructure import current_datetime
from infrastructure.current_datetime import get_current_datetime

_JST = timezone(timedelta(hours=9), "JST")


def test_returns_formatted_local_datetime(monkeypatch):
    fixed = datetime(2026, 7, 6, 14, 30, 5, tzinfo=_JST)  # 月曜日
    monkeypatch.setattr(current_datetime, "_now", lambda: fixed)
    assert get_current_datetime({}) == "2026-07-06 (月) 14:30:05 JST (UTC+09:00)"


def test_weekday_is_japanese(monkeypatch):
    fixed = datetime(2026, 7, 12, 0, 0, 0, tzinfo=_JST)  # 日曜日
    monkeypatch.setattr(current_datetime, "_now", lambda: fixed)
    assert "(日)" in get_current_datetime({})


def test_tool_definition_and_indicator():
    fn = get_current_datetime.definition["function"]
    assert fn["name"] == "get_current_datetime"
    assert fn["parameters"] == {"type": "object", "properties": {}}  # 引数なし
    assert get_current_datetime.indicator({}) == "[get_current_datetime]\n"


def test_real_clock_output_shape():
    """実時計でも形式が崩れないこと（値は検証しない）"""
    import re
    text = get_current_datetime({})
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2} \([月火水木金土日]\) \d{2}:\d{2}:\d{2} \S* \(UTC[+-]\d{2}:\d{2}\)",
        text,
    ), text
