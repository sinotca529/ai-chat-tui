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

    def __str__(self) -> str:
        match self:
            case self.USER:
                return "ME"

            case self.ASSISTANT:
                return "AI"
