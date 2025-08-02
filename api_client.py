import requests
import os
from dotenv import load_dotenv

load_dotenv()

AI21_API_KEY = os.getenv('AI21_API_KEY')

def generate_ai_response(prompt: str) -> str:
    """Генерация ответа с помощью AI21 API"""
    headers = {
        "Authorization": f"Bearer {AI21_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "jamba-large-1.6-2025-03",
        "messages": [
            {
                "role": "system",
                "content": "Ты креативный помощник для игры. Отвечай кратко и оригинально."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.7,
        "top_p": 1,
        "max_tokens": 200
    }
    
    try:
        response = requests.post(
            "https://api.ai21.com/studio/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"AI21 API error: {e}")
        return "Интересный ответ (ошибка генерации)"