import asyncio
import os
import tomllib

from dotenv import load_dotenv

from application.chat_session import ChatSession
from infrastructure.api_handler import ApiHandler
from infrastructure.chat_tree_store import ChatTreeStore
from infrastructure.calculator import calculate
from infrastructure.current_datetime import get_current_datetime
from infrastructure.memory_store import MemoryStore, make_save_memory_tool
from infrastructure.tool_registry import ToolRegistry
from infrastructure.web_fetch import fetch_page
from infrastructure.web_search import web_search
from ui.chat_app import ChatApp


def load_config(path: str = "config.toml") -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


async def main() -> None:
    load_dotenv()

    config = load_config()
    api_key = os.environ.get("OPENAI_API_KEY", "dummy")
    url = config["api"]["url"]
    model = config["api"]["model"]
    api_key_header = config["api"].get("api_key_header")
    context_window = config["api"].get("context_window")
    save_dir = config["storage"]["save_dir"]

    default_system_prompt = config.get("system", {}).get("prompt", "")

    memory_store = MemoryStore(save_dir)

    registry = ToolRegistry()
    registry.register(
        web_search, fetch_page, get_current_datetime, calculate,
        make_save_memory_tool(memory_store),
    )

    store = ChatTreeStore(save_dir)
    api = ApiHandler(url=url, api_key=api_key, model=model, api_key_header=api_key_header, registry=registry)
    tree = store.new_tree()
    session = ChatSession(
        tree=tree,
        api=api,
        store=store,
        default_system_prompt=default_system_prompt,
        context_window=context_window,
        memory_store=memory_store,
    )

    app = ChatApp(session)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
