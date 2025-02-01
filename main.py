from ui.chat_app import ChatApp

if __name__ == "__main__":
    url = "http://localhost:11434/v1/"
    model = "7shi/tanuki-dpo-v1.0:latest"
    save_dir = "./threads"
    ChatApp(url, "dummy_api_key", model, save_dir).run()
