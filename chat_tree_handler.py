from chat_tree import ChatTree
from api_handler import ApiHandler
from typing import Generator
from role import Role


class ChatTreeHandler:
    def __init__(self, tree: ChatTree, api_handler: ApiHandler):
        self.api_handler = api_handler
        self.tree = tree
        self.thread_id = self.tree.first_thread_id()

    def send_message(self, msg: str) -> Generator[str, None, None]:
        """OpenAI API にメッセージを送信"""
        thread = [
            {"role": e["role"], "content": e["content"]}
            for e in self.current_thread()
        ]
        stream = self.api_handler.send_message(thread, msg)

        response = ""
        for chunk in stream:
            response += chunk
            yield chunk

        self.tree.append(Role.USER, msg)
        self.thread_id = self.tree.append(Role.ASSISTANT, response)

    def current_thread(self):
        return self.tree.thread(self.thread_id)
