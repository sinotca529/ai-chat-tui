from dataclasses import dataclass
from domain.node import Node


@dataclass(frozen=True)
class ThreadEntry:
    node: Node
    sibling_index: int  # 1 始まり
    sibling_count: int  # 自身を含む総数
