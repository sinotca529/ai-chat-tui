from enum import Enum


class Role(Enum):
    USER = 1
    ASSISTANT = 2

    def role_name(self) -> str:
        match self:
            case self.USER:
                return "user"
            case self.ASSISTANT:
                return "assistant"
            case _:
                raise ValueError(f"Unknown role: {self}")

    def __str__(self) -> str:
        match self:
            case self.USER:
                return "ME"
            case self.ASSISTANT:
                return "AI"
            case _:
                raise ValueError(f"Unknown role: {self}")

    @staticmethod
    def from_str(role: str) -> "Role":
        match role:
            case "user":
                return Role.USER
            case "assistant":
                return Role.ASSISTANT
            case _:
                raise ValueError(f"Unknown role: {role}")
