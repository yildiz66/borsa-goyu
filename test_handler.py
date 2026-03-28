import sys
sys.path.append('.')
from borsa import cmd_hisse_slash, _tek_hisse_islem, analiz_motoru

class MockChat:
    def __init__(self):
        self.id = 12345

class MockMessage:
    def __init__(self, text):
        self.text = text
        self.chat = MockChat()

# We need to mock the bot instance in the borsa module
import borsa
class MockBot:
    def send_message(self, chat_id, text, **kwargs):
        print(f"[BOT MSG] {chat_id}: {text}")
    def send_photo(self, chat_id, photo, **kwargs):
        print(f"[BOT PHOTO] {chat_id}")
    def message_handler(self, **kwargs):
        def decorator(func):
            return func
        return decorator

borsa.bot = MockBot()

print("Testing cmd_hisse_slash with '/hisse THYAO'")
try:
    cmd_hisse_slash(MockMessage("/hisse THYAO"))
except Exception as e:
    print(f"FAILED: {e}")

print("Done testing.")
