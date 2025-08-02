import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackContext, CallbackQueryHandler, ConversationHandler
)
from game_manager import manager
from api_client import generate_ai_response
from config import BOT_TOKEN, TIMEOUT

# Настройки логгирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Состояния
SELECT_THEME, COLLECT_ANSWERS, VOTING = range(3)

def start(update: Update, context: CallbackContext) -> int:
    """Обработка команды /start"""
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type == 'private':
        update.message.reply_text("❌ Добавьте меня в группу для игры!")
        return ConversationHandler.END
    
    # Создаем новую игру
    manager.new_game(chat.id, user.id)
    
    # Показываем первые 10 тем
    themes = manager.themes[:10]
    theme_list = "\n".join([f"{i+1}. {theme}" for i, theme in enumerate(themes)])
    
    update.message.reply_text(
        f"🎮 **Начинаем игру!**\n"
        f"Администратор: {user.full_name}\n\n"
        f"Выберите тему (введите номер):\n{theme_list}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Показать все темы", callback_data='show_all')]
        ])
    )
    return SELECT_THEME

def show_all_themes(update: Update, context: CallbackContext) -> int:
    """Показ всех 100 тем"""
    query = update.callback_query
    query.answer()
    
    theme_list = "\n".join([f"{i+1}. {theme}" for i, theme in enumerate(manager.themes)])
    
    # Разбиваем на части из-за ограничения длины сообщения
    for i in range(0, len(theme_list), 4000):
        query.edit_message_text(
            text=f"Все темы:\n{theme_list[i:i+4000]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data='back_to_start')]
            ])
        )
    return SELECT_THEME

def select_theme(update: Update, context: CallbackContext) -> int:
    """Обработка выбора темы"""
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    
    try:
        if manager.set_theme(chat_id, text):
            theme = manager.games[chat_id]['theme']
            update.message.reply_text(f"✅ Тема выбрана: **{theme}**\n\n"
                                     "⏱️ У игроков есть 5 минут на отправку ответов!",
                                     parse_mode="Markdown")
            
            # Отправка запросов игрокам
            for member in context.bot.get_chat_members(chat_id):
                if not member.user.is_bot:
                    try:
                        context.bot.send_message(
                            member.user.id,
                            f"🎯 Тема: **{theme}**\n"
                            "Пришлите ваш ответ в личном сообщении (одним сообщением)!",
                            parse_mode="Markdown"
                        )
                    except:
                        logger.warning(f"Не удалось отправить сообщение пользователю: {member.user.id}")
            
            # Таймер для завершения этапа ответов
            context.job_queue.run_once(end_answers_phase, TIMEOUT, context=chat_id)
            return COLLECT_ANSWERS
    except:
        pass
    
    update.message.reply_text("❌ Неверный номер темы! Попробуйте снова.")
    return SELECT_THEME

def handle_private_answer(update: Update, context: CallbackContext) -> int:
    """Обработка ответов от игроков"""
    user = update.effective_user
    text = update.message.text
    
    # Ищем активную игру с участием пользователя
    for chat_id, game in manager.games.items():
        if game['status'] == 'collecting_answers' and user.id in [p for p in game['players']]:
            if manager.add_answer(chat_id, user.id, text):
                update.message.reply_text("✅ Ответ сохранен! Ожидайте начала голосования.")
            else:
                update.message.reply_text("❌ Вы уже отправили ответ!")
            break
    else:
        update.message.reply_text("ℹ️ Сейчас нет активных игр, где вы участвуете.")
    
    return COLLECT_ANSWERS

def end_answers_phase(context: CallbackContext):
    chat_id = context.job.context
    game = manager.games.get(chat_id)
    
    if not game or game['status'] != 'collecting_answers':
        return
    
    # Запускаем генерацию ответа ИИ и голосование
    manager.start_voting(chat_id)
    
    # Формируем сообщение с ответами
    options = game['voting_options']
    answers_text = "\n\n".join(
        [f"🔹 Ответ {idx+1}: {ans}" for idx, ans in enumerate(options)]
    )
    
    context.bot.send_message(
        chat_id,
        f"🕒 Время вышло! Все ответы:\n\n{answers_text}\n\n"
        "❓ **Голосуйте за вариант, который по вашему мнению сгенерировала нейросеть!**",
        parse_mode="Markdown"
    )
    
    # Отправка кнопок голосования игрокам
    keyboard = [
        [InlineKeyboardButton(f"Вариант {i+1}", callback_data=f"vote_{i}")]
        for i in range(len(options))
    ]
    
    for user_id in game['players']:
        try:
            context.bot.send_message(
                user_id,
                "🗳️ **Выберите ответ нейросети:**",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except:
            logger.warning(f"Не удалось отправить клавиатуру пользователю: {user_id}")
    
    # Таймер для завершения голосования
    context.job_queue.run_once(end_voting_phase, TIMEOUT, context=chat_id)


def handle_vote(update: Update, context: CallbackContext) -> int:
    """Обработка голосования"""
    query = update.callback_query
    user = query.from_user
    data = query.data
    
    try:
        option_idx = int(data.split('_')[1])
        for chat_id, game in manager.games.items():
            if game['status'] == 'voting' and user.id in game['players']:
                if manager.add_vote(chat_id, user.id, option_idx):
                    query.answer("✅ Ваш голос учтен!")
                else:
                    query.answer("❌ Вы уже голосовали!")
                break
        else:
            query.answer("ℹ️ Голосование завершено или вы не участвуете!")
    except:
        query.answer("❌ Ошибка обработки голоса!")
    
    return VOTING

def end_voting_phase(context: CallbackContext):
    """Завершение голосования"""
    chat_id = context.job.context
    game = manager.games.get(chat_id)
    
    if not game or game['status'] != 'voting':
        return
    
    # Получаем результаты
    results_text, ai_answer = manager.get_results(chat_id)
    
    context.bot.send_message(
        chat_id,
        f"🏁 **Голосование завершено!**\n\n"
        f"{results_text}\n\n"
        f"🤖 **Ответ нейросети:**\n{ai_answer}\n\n"
        "Игра окончена! Для новой игры используйте /start",
        parse_mode="Markdown"
    )
    
    # Завершаем игру
    manager.end_game(chat_id)

def cancel(update: Update, context: CallbackContext) -> int:
    """Отмена игры"""
    chat_id = update.effective_chat.id
    if chat_id in manager.games:
        manager.end_game(chat_id)
        update.message.reply_text("❌ Игра отменена!")
    return ConversationHandler.END

def main():
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SELECT_THEME: [
                CallbackQueryHandler(show_all_themes, pattern='^show_all$'),
                CallbackQueryHandler(start, pattern='^back_to_start$'),
                MessageHandler(Filters.text & ~Filters.command, select_theme)
            ],
            COLLECT_ANSWERS: [
                MessageHandler(Filters.text & Filters.private, handle_private_answer)
            ],
            VOTING: [
                CallbackQueryHandler(handle_vote, pattern='^vote_')
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(conv_handler)
    dp.add_handler(CommandHandler('cancel', cancel))
    
    # Обработка ответов вне ConversationHandler
    dp.add_handler(MessageHandler(Filters.private & Filters.text, handle_private_answer))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()