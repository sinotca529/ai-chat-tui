import json
import os

from domain.chat_tree import ChatTree
from domain.role import Role
from infrastructure.chat_tree_store import ChatTreeStore


def test_save_and_load_round_trip(store):
    tree = ChatTree()
    node_id = tree.insert(None, Role.USER, "こんにちは")
    tree.set_current(node_id)
    tree.set_title("挨拶")
    store.save(tree)

    loaded = store.load(tree.tree_id)
    assert loaded.title == "挨拶"
    assert loaded.current_id == node_id
    assert loaded.thread(node_id)[0].content == "こんにちは"


def test_new_tree_is_not_persisted(store, tmp_path):
    """空ツリーの非永続化: new_tree() はファイルを作らない"""
    store.new_tree()
    assert os.listdir(str(tmp_path / "trees")) == []


def test_list_trees_returns_id_title_pairs_sorted(store):
    for tree_id, title in [("b-tree", "B"), ("a-tree", "A")]:
        tree = ChatTree(tree_id=tree_id, title=title)
        store.save(tree)
    assert store.list_trees() == [("a-tree", "A"), ("b-tree", "B")]


def test_list_trees_ignores_non_json_and_tolerates_corrupt_files(store, tmp_path):
    save_dir = tmp_path / "trees"
    (save_dir / "note.txt").write_text("not a tree")
    (save_dir / "broken.json").write_text("{invalid json")
    tree = ChatTree(tree_id="ok", title="正常")
    store.save(tree)

    assert store.list_trees() == [("broken", ""), ("ok", "正常")]


def test_delete_removes_file_and_is_noop_when_missing(store, tmp_path):
    tree = ChatTree(tree_id="target")
    store.save(tree)
    store.delete("target")
    assert store.list_trees() == []
    store.delete("nonexistent")  # 例外にならないこと


def test_saved_json_is_utf8_readable(store, tmp_path):
    tree = ChatTree(tree_id="jp", title="日本語タイトル")
    store.save(tree)
    raw = (tmp_path / "trees" / "jp.json").read_text(encoding="utf-8")
    assert "日本語タイトル" in raw  # ensure_ascii=False で保存されている
    assert json.loads(raw)["title"] == "日本語タイトル"
