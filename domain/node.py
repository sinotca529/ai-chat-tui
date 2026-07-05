from dataclasses import dataclass, field
from domain.role import Role


@dataclass(frozen=True)
class Node:
    id: int
    role: Role
    content: str
    parent_id: int | None
    tool_messages: tuple = field(default=(), compare=False, hash=False)
