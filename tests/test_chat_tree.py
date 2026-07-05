from domain.chat_tree import ChatTree
from domain.role import Role


def _build_branched_tree() -> ChatTree:
    """root(user) ─ a1(asst) ─ u2(user) ─ a2(asst)
                  └ u2b(user)  ← a1 からの分岐"""
    tree = ChatTree()
    root = tree.insert(None, Role.USER, "q1")
    a1 = tree.insert(root, Role.ASSISTANT, "ans1")
    u2 = tree.insert(a1, Role.USER, "q2")
    a2 = tree.insert(u2, Role.ASSISTANT, "ans2")
    tree.insert(a1, Role.USER, "q2-branch")
    tree.set_current(a2)
    return tree


def test_insert_assigns_sequential_ids():
    tree = ChatTree()
    assert tree.insert(None, Role.USER, "a") == 0
    assert tree.insert(0, Role.ASSISTANT, "b") == 1
    assert tree.insert(1, Role.USER, "c") == 2


def test_thread_returns_path_from_root():
    tree = _build_branched_tree()
    assert [n.content for n in tree.thread(3)] == ["q1", "ans1", "q2", "ans2"]
    assert [n.content for n in tree.thread(4)] == ["q1", "ans1", "q2-branch"]


def test_thread_of_none_is_empty():
    assert ChatTree().thread(None) == []


def test_children_derived_from_parent_id():
    tree = _build_branched_tree()
    assert tree.children(1) == [2, 4]
    assert tree.children(3) == []


def test_siblings_with_self_sorted_by_id():
    tree = _build_branched_tree()
    assert tree.siblings_with_self(2) == [2, 4]
    assert tree.siblings_with_self(4) == [2, 4]


def test_root_nodes_are_siblings_of_each_other():
    """parent_id=None のルートノード同士も兄弟として導出される"""
    tree = _build_branched_tree()
    assert tree.siblings_with_self(0) == [0]  # ルートが 1 つなら自身のみ

    second_root = tree.insert(None, Role.USER, "another root")
    assert tree.siblings_with_self(0) == [0, second_root]
    assert tree.siblings_with_self(second_root) == [0, second_root]


def test_set_current_none_returns_to_root():
    tree = _build_branched_tree()
    tree.set_current(None)
    assert tree.current_id is None
    assert tree.thread(tree.current_id) == []


def test_rollback_pops_tail_and_resets_current_to_parent():
    tree = _build_branched_tree()
    tree.rollback()  # q2-branch (id=4) を取り消し
    assert tree.current_id == 1  # 親 a1
    assert tree.children(1) == [2]


def test_rollback_on_empty_tree_is_noop():
    tree = ChatTree()
    tree.rollback()
    assert tree.current_id is None


def test_dict_round_trip_preserves_everything():
    tree = _build_branched_tree()
    tree.set_title("タイトル")
    tree.set_system_prompt("プロンプト")
    tool_msgs = (
        {"role": "assistant", "content": None, "tool_calls": []},
        {"role": "tool", "tool_call_id": "t1", "content": "result"},
    )
    node_id = tree.insert(3, Role.ASSISTANT, "with tools", tool_messages=tool_msgs)
    tree.set_current(node_id)

    restored = ChatTree.from_dict(tree.to_dict())

    assert restored.tree_id == tree.tree_id
    assert restored.title == "タイトル"
    assert restored.system_prompt == "プロンプト"
    assert restored.current_id == node_id
    assert [n.content for n in restored.thread(node_id)] == [
        "q1", "ans1", "q2", "ans2", "with tools",
    ]
    assert restored.thread(node_id)[-1].tool_messages == tool_msgs
    assert restored.thread(node_id)[-1].role is Role.ASSISTANT


def test_from_dict_accepts_legacy_nodes_without_tool_messages():
    """tool_messages キーを持たない旧形式 JSON も読めること（後方互換）"""
    data = {
        "tree_id": "legacy",
        "current_id": 1,
        "nodes": [
            {"id": 0, "role": "user", "content": "q", "parent_id": None},
            {"id": 1, "role": "assistant", "content": "a", "parent_id": 0},
        ],
    }
    tree = ChatTree.from_dict(data)
    assert tree.title == ""
    assert tree.system_prompt == ""
    assert tree.thread(1)[0].tool_messages == ()
