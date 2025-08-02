from collections import defaultdict
import random
from datetime import datetime, timedelta
from api_client import generate_ai_response

class GameManager:
    def __init__(self):
        self.games = {}
        self.themes = self.load_themes()
    
    def load_themes(self):
        """Загрузка тем из файла или генерация"""
        try:
            with open('themes.txt', 'r', encoding='utf-8') as f:
                return [line.strip() for line in f.readlines() if line.strip()]
        except FileNotFoundError:
            # Примерный список тем (в реальном боте замените на 100 реальных тем)
            return [f"Тема {i}" for i in range(1, 101)]
    
    def new_game(self, chat_id: int, admin_id: int):
        self.games[chat_id] = {
            'admin': admin_id,
            'theme': None,
            'players': {},
            'ai_answer': None,
            'status': 'theme_select',
            'voting_options': [],
            'votes': defaultdict(int),
            'voted_users': set()
        }
    
    def set_theme(self, chat_id: int, theme_index: int):
        try:
            self.games[chat_id]['theme'] = self.themes[int(theme_index) - 1]
            self.games[chat_id]['status'] = 'collecting_answers'
            return True
        except:
            return False
    
    def add_answer(self, chat_id: int, user_id: int, answer: str):
        if self.games.get(chat_id, {}).get('status') == 'collecting_answers':
            self.games[chat_id]['players'][user_id] = answer
            return True
        return False
    
    def start_voting(self, chat_id: int):
        game = self.games[chat_id]
        theme = game['theme']
        
        # Генерация ответа нейросети
        game['ai_answer'] = generate_ai_response(
            f"Придумай креативный ответ на тему: {theme}"
        )
        
        all_answers = list(game['players'].values()) + [game['ai_answer']]
        random.shuffle(all_answers)
        game['voting_options'] = all_answers
        game['status'] = 'voting'
        game['start_time'] = datetime.now()
    
    def add_vote(self, chat_id: int, user_id: int, option_index: int):
        if user_id in self.games[chat_id]['voted_users']:
            return False
        
        self.games[chat_id]['votes'][option_index] += 1
        self.games[chat_id]['voted_users'].add(user_id)
        return True
    
    def get_results(self, chat_id: int):
        game = self.games[chat_id]
        total_votes = sum(game['votes'].values())
        results = []
        
        for idx, count in game['votes'].items():
            percentage = (count / total_votes * 100) if total_votes > 0 else 0
            results.append(f"Вариант {idx+1}: {percentage:.1f}%")
        
        return "\n".join(results), game['ai_answer']
    
    def end_game(self, chat_id: int):
        if chat_id in self.games:
            del self.games[chat_id]

manager = GameManager()