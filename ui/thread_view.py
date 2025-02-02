import asyncio
from typing import Generator
from role import Role
from textual.widgets import ListView, ListItem, Static, TextArea
from textual.containers import HorizontalGroup, VerticalGroup
from textual.app import ComposeResult
from textual.screen import ModalScreen


class EditUserMessageWindow(ModalScreen[str]):
    CSS = """
    EditUserMessageWindow {
        align: center middle;
    }
    VerticalGroup {
        width: 60%;
        height: 60%;
    }
    """

    def __init__(self, current_message: str) -> None:
        super().__init__()
        self.current_message = current_message

    def compose(self) -> ComposeResult:
        with VerticalGroup():
            yield Static("Edit Message...")
            yield TextArea(self.current_message)

    def on_key(self, event) -> None:
        match event.key:
            case "escape":
                self.app.pop_screen()

            case "ctrl+d":
                edit_area = self.query_one(TextArea)
                self.dismiss(edit_area.text)


class UserMessage(ListItem):
    def __init__(
        self,
        message: str,
        message_id: int,
        siblings: list[int]
    ) -> None:
        super().__init__(id=f"item{message_id}")
        self.message = message
        self.message_id = message_id
        self.sib = siblings

    def compose(self) -> ComposeResult:
        role = Role.USER
        sibling_index = len([s for s in self.sib if s < self.message_id]) + 1

        with HorizontalGroup():
            yield Static(str(role), classes=f"role {role.role_name()}")
            with VerticalGroup():
                yield Static(
                    self.message,
                    classes=f"msg {role.role_name()}",
                    id=f"msg{self.message_id}",
                )
                yield Static(
                    f"{sibling_index}/{len(self.sib)+1}",
                    classes="siblings"
                )


class TreeView(ListView):
    async def add_user_message(
        self,
        message: str,
        message_id: int,
        siblings: list[int]
    ) -> None:
        self.append(UserMessage(message, message_id, siblings))
        self.refresh()
        await asyncio.sleep(0.1)

    async def add_assistant_message(
        self,
        stream: list[str] | Generator[str, None, None]
    ) -> None:
        role = Role.ASSISTANT

        role_elem = Static(str(role), classes="role")
        role_elem.add_class(role.role_name())

        msg_elem = Static(classes="msg")
        msg_elem.add_class(role.role_name())

        line_elem = ListItem(HorizontalGroup(role_elem, msg_elem))
        self.append(line_elem)

        self.refresh()
        await asyncio.sleep(0.1)

        for chunk in stream:
            msg_elem.update(msg_elem.renderable + str(chunk))
            msg_elem.refresh()
            await asyncio.sleep(0.1)

    async def render_thread(self, thread: list[dict]) -> None:
        self.clear()
        for msg in thread:
            match Role.from_str(msg["role"]):
                case Role.USER:
                    await self.add_user_message(
                        msg["content"],
                        msg["id"],
                        msg["siblings"]
                    )
                case Role.ASSISTANT:
                    await self.add_assistant_message(
                        [msg["content"]]
                    )

    async def on_key(self, event) -> None:
        match event.key:
            case "r":
                message_id = self._highlighted_user_message_id()
                if message_id is None:
                    return

                msg_elem = self.query_one(f"#msg{message_id}", Static)
                current_msg = msg_elem.renderable

                self.app.push_screen(
                    EditUserMessageWindow(current_msg),
                    self._tmp
                )

            case "h":
                message_id = self._highlighted_user_message_id()
                if not message_id:
                    return

    def _tmp(self) -> None:
        pass

    def _highlighted_user_message_id(self) -> int | None:
        if self.highlighted_child is None:
            return None

        message_id = self.highlighted_child.id
        if message_id is None:
            return None

        return int(message_id[len("item"):])
