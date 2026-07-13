from dataclasses import dataclass, field
from domain.role import Role


@dataclass(frozen=True)
class Node:
    id: int
    role: Role
    content: str
    parent_id: int | None
    tool_messages: tuple = field(default=(), compare=False, hash=False)
    # 添付ファイルのスナップショット（{"path": str, "content": str} のタプル列）。
    # 送信時点の内容を保存するため、後でファイルが変更・移動されても会話の再現性が保たれる。
    attachments: tuple = field(default=(), compare=False, hash=False)
