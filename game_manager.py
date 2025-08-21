from collections import defaultdict
import random
from datetime import datetime
from api_client import generate_ai_response


class GameManager:
    def __init__(self):
        self.games = {}
        self.themes = self.load_themes()
    
    def load_themes(self):
        """Загрузка тем из файла или генерация списка"""
        try:
            with open('themes.txt', 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            # Заглушка (100 тем)
            return [f"Тема {i}" for i in range(1, 101)]
    
    def new_game(self, chat_id: int, admin_id: int):
        """Создание новой игры"""
        self.games[chat_id] = {
            "admin": admin_id,
            "theme": None,
            "players": {},  # user_id -> answer
            "ai_answer": None,
            "status": "theme_select",  # ожидание выбора темы
            "voting_options": [],
            "votes": defaultdict(int),
            "voted_users": set()
        }
        return "Игра создана! Введите номер темы (например: 5 или /5)."
    
    def set_theme(self, chat_id: int, theme_input: str):
        """Выбор темы по номеру (5 или /5)"""
        if chat_id not in self.games:
            return "Сначала начните новую игру командой /game"
        
        game = self.games[chat_id]
        if game["status"] != "theme_select":
            return "Тема уже выбрана!"
        
        # обработка формата ввода
        theme_input = theme_input.strip().lstrip("/")  
        if not theme_input.isdigit():
            return "Введите номер темы (например: 5 или /5)"
        
        idx = int(theme_input) - 1
        if idx < 0 or idx >= len(self.themes):
            return f"Неверный номер. Доступны от 1 до {len(self.themes)}"
        
        game["theme"] = self.themes[idx]
        game["status"] = "collecting_answers"
        return f"Вы выбрали тему: *{game['theme']}*\n\nИгроки, присылайте свои ответы!"
    
    def add_answer(self, chat_id: int, user_id: int, answer: str):
        """Игрок присылает свой ответ"""
        game = self.games.get(chat_id)
        if not game or game["status"] != "collecting_answers":
            return False
        
        game["players"][user_id] = answer
        return True
    
    def start_voting(self, chat_id: int):
        """Переход к голосованию"""
        game = self.games.get(chat_id)
        if not game:
            return "Игра не найдена."
        
        if not game["players"]:
            return "Нет ответов игроков! Нечего голосовать."
        
        # ответ ИИ
        game["ai_answer"] = generate_ai_response(f"Придумай креативный ответ на тему: {game['theme']}")
        
        all_answers = list(game["players"].values()) + [game["ai_answer"]]
        random.shuffle(all_answers)
        
        game["voting_options"] = all_answers
        game["status"] = "voting"
        game["start_time"] = datetime.now()
        
        options_text = "\n".join([f"{i+1}. {ans}" for i, ans in enumerate(all_answers)])
        return f"Голосование началось!\n\n{options_text}\n\nГолосуйте, отправив номер варианта."
    
    def add_vote(self, chat_id: int, user_id: int, option_input: str):
        """Игрок голосует за вариант"""
        game = self.games.get(chat_id)
        if not game or game["status"] != "voting":
            return "Сейчас нельзя голосовать."
        
        if user_id in game["voted_users"]:
            return "Вы уже голосовали!"
        
        option_input = option_input.strip().lstrip("/")
        if not option_input.isdigit():
            return "Введите номер варианта (например: 2 или /2)"
        
        idx = int(option_input) - 1
        if idx < 0 or idx >= len(game["voting_options"]):
            return "Неверный номер варианта."
        
        game["votes"][idx] += 1
        game["voted_users"].add(user_id)
        return f"Вы проголосовали за вариант {idx+1}"
    
    def get_results(self, chat_id: int):
        """Подсчёт голосов"""
        game = self.games.get(chat_id)
        if not game:
            return "Игра не найдена."
        
        total_votes = sum(game["votes"].values())
        if total_votes == 0:
            return "Никто не проголосовал!"
        
        results = []
        for idx, text in enumerate(game["voting_options"]):
            count = game["votes"].get(idx, 0)
            percentage = (count / total_votes * 100) if total_votes > 0 else 0
            results.append(f"{idx+1}. {text[:40]}... — {count} голосов ({percentage:.1f}%)")
        
        ai_text = f"\nОтвет ИИ был: «{game['ai_answer']}»"
        return "\n".join(results) + ai_text
    
    def end_game(self, chat_id: int):
        if chat_id in self.games:
            del self.games[chat_id]
            return "Игра завершена."
        return "Игра не найдена."

manager = GameManager()
