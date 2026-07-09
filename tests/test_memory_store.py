import json

import pytest

from infrastructure.memory_store import (
    MAX_ENTRIES,
    MAX_ENTRY_CHARS,
    MemoryStore,
    make_save_memory_tool,
)


@pytest.fixture
def memory_store(tmp_path) -> MemoryStore:
    return MemoryStore(str(tmp_path))


def test_add_and_list_round_trip(memory_store):
    memory_store.add("Python 3.13 を使っている")
    memory_store.add("応答は日本語でほしい")
    texts = [m["text"] for m in memory_store.list_all()]
    assert texts == ["Python 3.13 を使っている", "応答は日本語でほしい"]
    # id は連番、日付が付く
    entries = memory_store.list_all()
    assert [m["id"] for m in entries] == [1, 2]
    assert all(m["created_at"] for m in entries)


def test_empty_store_lists_nothing(memory_store):
    assert memory_store.list_all() == []


def test_external_edits_are_picked_up(memory_store, tmp_path):
    """アプリ起動中の memory.json 手編集が次の読み出しに反映される"""
    memory_store.add("消される予定のメモ")
    path = tmp_path / "memory.json"
    path.write_text(
        json.dumps({"memories": [{"id": 5, "text": "手で書いたメモ", "created_at": "2026-01-01"}]}),
        encoding="utf-8",
    )
    assert [m["text"] for m in memory_store.list_all()] == ["手で書いたメモ"]
    memory_store.add("追記")  # 手編集後の id=5 から連番が続く
    assert [m["id"] for m in memory_store.list_all()] == [5, 6]


def test_add_rejects_empty_and_too_long(memory_store):
    with pytest.raises(ValueError):
        memory_store.add("   ")
    with pytest.raises(ValueError, match="too long"):
        memory_store.add("あ" * (MAX_ENTRY_CHARS + 1))
    assert memory_store.list_all() == []


def test_add_rejects_when_full(memory_store):
    for i in range(MAX_ENTRIES):
        memory_store.add(f"メモ{i}")
    with pytest.raises(ValueError, match="full"):
        memory_store.add("あふれるメモ")
    assert len(memory_store.list_all()) == MAX_ENTRIES


def test_corrupt_json_reads_empty_but_refuses_writes(memory_store, tmp_path):
    """壊れた JSON: 読み出しは空扱い（チャットを止めない）、書き込みは拒否
    （黙って上書きしてデータを失わない）"""
    (tmp_path / "memory.json").write_text("{broken json", encoding="utf-8")
    assert memory_store.list_all() == []
    with pytest.raises(ValueError, match="corrupted"):
        memory_store.add("新しいメモ")
    # 壊れたファイルが上書きされていないこと
    assert (tmp_path / "memory.json").read_text(encoding="utf-8") == "{broken json"


def test_save_memory_tool_saves_and_reports(memory_store):
    save_memory = make_save_memory_tool(memory_store)
    assert save_memory({"content": "犬を飼っている"}) == "Saved to memory."
    assert [m["text"] for m in memory_store.list_all()] == ["犬を飼っている"]


def test_save_memory_tool_returns_error_string(memory_store):
    """上限超過等は例外ではなくエラーメッセージ文字列（モデルが対処できる）"""
    save_memory = make_save_memory_tool(memory_store)
    result = save_memory({"content": "あ" * (MAX_ENTRY_CHARS + 1)})
    assert result.startswith("Error:")
    assert memory_store.list_all() == []


def test_tool_definition_and_indicator(memory_store):
    save_memory = make_save_memory_tool(memory_store)
    fn = save_memory.definition["function"]
    assert fn["name"] == "save_memory"
    assert "content" in fn["parameters"]["required"]
    assert save_memory.indicator({"content": "x"}) == "[save_memory: x]\n"
