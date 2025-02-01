import asyncio
from role import Role
from textual.widgets import ListView, ListItem, Static
from textual.containers import HorizontalGroup


class ThreadView(ListView):
    CSS = """
    Thread {
        width: 100%;
        height: 85%;
        overflow: auto;
        padding: 1;
        background: black;
    }

    ListItem {
        margin-bottom: 1
    }

    .role {
        width: 5;
    }

    .assistant {
        color: lightgreen;
    }
    """

    async def update_chat(self, role: Role, stream):
        role_elem = Static(str(role), classes="role")
        role_elem.add_class(role.role_name())

        msg_elem = Static(classes="msg")
        msg_elem.add_class(role.role_name())

        line_elem = ListItem(HorizontalGroup(role_elem, msg_elem))
        self.append(line_elem)
        await asyncio.sleep(0.1)

        for chunk in stream:
            msg_elem.update(msg_elem.renderable + str(chunk))
            msg_elem.refresh()
            await asyncio.sleep(0.1)
