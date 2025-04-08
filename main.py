from ui.chat_app import ChatApp

if __name__ == "__main__":
    url = "http://localhost:8888/v1"
    model = "dummy_model"
    save_dir = "./tree"
    ChatApp(url, "dummy_api_key", model, save_dir).run()
