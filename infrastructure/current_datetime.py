from datetime import datetime

from .tool_registry import tool

_WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


def _now() -> datetime:
    """現在のローカル日時（タイムゾーン付き）。テストで差し替える。"""
    return datetime.now().astimezone()


@tool(
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": (
                "Get the current local date and time. Use this whenever the answer "
                "depends on today's date or the current time, e.g. questions about "
                "'today', 'now', 'this year', 'latest', or relative dates, and when "
                "building web search queries about recent events."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    indicator=lambda args: "[get_current_datetime]\n",
)
def get_current_datetime() -> str:
    now = _now()
    weekday = _WEEKDAYS_JA[now.weekday()]
    offset = now.strftime("%z")  # 例: +0900
    offset = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC?"
    tz_name = now.tzname() or ""
    return f"{now:%Y-%m-%d} ({weekday}) {now:%H:%M:%S} {tz_name} ({offset})"
