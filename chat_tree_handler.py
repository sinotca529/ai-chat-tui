from chat_tree import ChatTree
from api_handler import ApiHandler
from typing import Generator
from role import Role


class ChatTreeHandler:
    def __init__(self, tree: ChatTree, api_handler: ApiHandler):
        self.api_handler = api_handler
        self.tree = tree
        self.thread_id = self.tree.first_thread_id()

    def send_message(self, msg: str) -> (int, Generator[str, None, None]):
        """OpenAI API にメッセージを送信"""
        thread = [
            {"role": e["role"], "content": e["content"]}
            for e in self.current_thread()
        ]
        stream = self.api_handler.send_message(thread, msg)

        user_message_id = self.tree.append(Role.USER, msg)

        def generator():
            response = ""
            for chunk in stream:
                response += chunk
                yield chunk
            self.thread_id = self.tree.append(Role.ASSISTANT, response)

        return user_message_id, generator()

    def current_thread(self):
        return self.tree.thread(self.thread_id)
