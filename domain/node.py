from dataclasses import dataclass
from domain.role import Role


@dataclass(frozen=True)
class Node:
    id: int
    role: Role
    content: str
    parent_id: int | None
