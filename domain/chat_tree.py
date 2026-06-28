import uuid
from domain.node import Node
from domain.role import Role


class ChatTree:
    def __init__(
        self,
        tree_id: str | None = None,
        nodes: list[Node] | None = None,
        current_id: int | None = None,
        title: str = "",
    ) -> None:
        self._tree_id = tree_id or str(uuid.uuid4())
        self._nodes: list[Node] = nodes or []
        self._current_id: int | None = current_id
        self._title: str = title

    @property
    def tree_id(self) -> str:
        return self._tree_id

    @property
    def title(self) -> str:
        return self._title

    def set_title(self, title: str) -> None:
        self._title = title

    @property
    def current_id(self) -> int | None:
        return self._current_id

    def set_current(self, node_id: int) -> None:
        self._current_id = node_id

    def insert(self, parent_id: int | None, role: Role, content: str) -> int:
        node_id = len(self._nodes)
        self._nodes.append(Node(id=node_id, role=role, content=content, parent_id=parent_id))
        return node_id

    def thread(self, node_id: int) -> list[Node]:
        """root から node_id までのパスを返す"""
        if node_id is None:
            return []
        path: list[Node] = []
        current: int | None = node_id
        while current is not None:
            node = self._nodes[current]
            path.append(node)
            current = node.parent_id
        return list(reversed(path))

    def children(self, node_id: int) -> list[int]:
        return [n.id for n in self._nodes if n.parent_id == node_id]

    def siblings_with_self(self, node_id: int) -> list[int]:
        """同じ親を持つノードの ID リスト（自身を含む、ID 昇順）"""
        parent_id = self._nodes[node_id].parent_id
        if parent_id is None:
            return [node_id]
        return [n.id for n in self._nodes if n.parent_id == parent_id]

    def rollback(self) -> None:
        """末尾ノードを取り消し、current_id を親に戻す"""
        if not self._nodes:
            return
        node = self._nodes.pop()
        self._current_id = node.parent_id

    def to_dict(self) -> dict:
        return {
            "tree_id": self._tree_id,
            "title": self._title,
            "current_id": self._current_id,
            "nodes": [
                {
                    "id": n.id,
                    "role": n.role,
                    "content": n.content,
                    "parent_id": n.parent_id,
                }
                for n in self._nodes
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChatTree":
        nodes = [
            Node(
                id=n["id"],
                role=Role(n["role"]),
                content=n["content"],
                parent_id=n["parent_id"],
            )
            for n in data["nodes"]
        ]
        return cls(
            tree_id=data["tree_id"],
            nodes=nodes,
            current_id=data.get("current_id"),
            title=data.get("title", ""),
        )
