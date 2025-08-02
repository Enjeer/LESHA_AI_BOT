import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
AI_API_KEY = os.getenv('AI_API_KEY')
TIMEOUT = int(os.getenv('TIMEOUT_MINUTES', 5)) * 60  # Конвертация в секунды