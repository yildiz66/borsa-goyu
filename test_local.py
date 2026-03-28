import sys
sys.path.append('.')
import borsa

# Mocking the bot
class MockBot:
    def send_message(self, chat_id, text, **kwargs):
        print(f"BOT MESSAGE TO {chat_id}: {text}")
    def send_photo(self, chat_id, photo, caption, **kwargs):
        print(f"BOT PHOTO TO {chat_id} with caption: {caption}")

borsa.bot = MockBot()
borsa.MY_ID = "mock_id"

print("--- Testing _tek_hisse_islem THYAO ---")
# Call directly, synchronously
borsa._tek_hisse_islem("mock_id", "THYAO")

print("--- Testing _ai_sohbet_islem THYAO ---")
borsa._ai_sohbet_islem("mock_id", "THYAO", "Hisse sence uçar mı?")
