import asyncio
import os
import tomllib

from dotenv import load_dotenv

from application.chat_session import ChatSession
from infrastructure.api_handler import ApiHandler
from infrastructure.chat_tree_store import ChatTreeStore
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
    extra_headers = config["api"].get("headers", {})
    save_dir = config["storage"]["save_dir"]

    default_system_prompt = config.get("system", {}).get("prompt", "")

    store = ChatTreeStore(save_dir)
    api = ApiHandler(url=url, api_key=api_key, model=model, extra_headers=extra_headers)
    tree = store.new_tree()
    session = ChatSession(
        tree=tree,
        api=api,
        store=store,
        default_system_prompt=default_system_prompt,
    )

    app = ChatApp(session)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
