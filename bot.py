import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from game_manager import manager
from api_client import generate_ai_response
from config import BOT_TOKEN, TIMEOUT

# Логгирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
SELECT_THEME, COLLECT_ANSWERS, VOTING = range(3)


# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type == "private":
        await update.message.reply_text("❌ Добавьте меня в группу для игры!")
        return ConversationHandler.END

    manager.new_game(chat.id, user.id)
    themes = manager.themes[:10]
    theme_list = "\n".join([f"{i+1}. {theme}" for i, theme in enumerate(themes)])

    await update.message.reply_text(
        f"🎮 **Начинаем игру!**\n"
        f"Администратор: {user.full_name}\n\n"
        f"Выберите тему (введите номер):\n{theme_list}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Показать все темы", callback_data="show_all")]]
        ),
    )
    return SELECT_THEME


async def show_all_themes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    theme_list = "\n".join([f"{i+1}. {theme}" for i, theme in enumerate(manager.themes)])
    for i in range(0, len(theme_list), 4000):
        await query.edit_message_text(
            text=f"Все темы:\n{theme_list[i:i+4000]}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("◀️ Назад", callback_data="back_to_start")]]
            ),
        )
    return SELECT_THEME


async def select_theme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    raw_text = update.message.text.strip()

    if raw_text.startswith("/"):
        raw_text = raw_text[1:]

    try:
        choice = int(raw_text)
    except ValueError:
        await update.message.reply_text("❌ Введите число (например, 5).")
        return SELECT_THEME

    try:
        if manager.set_theme(chat_id, choice):
            theme = manager.games[chat_id]["theme"]

            await update.message.reply_text(
                f"✅ Тема выбрана: *{theme}*\n\n"
                "⏱️ У игроков есть 5 минут на отправку ответов!",
                parse_mode="Markdown",
            )

            context.job_queue.run_once(end_answers_phase, TIMEOUT, chat_id=chat_id)
            return COLLECT_ANSWERS
        else:
            await update.message.reply_text("❌ Неверный номер темы! Попробуйте снова.")
            return SELECT_THEME

    except Exception as e:
        logger.error(f"Ошибка выбора темы ({chat_id}): {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Ошибка при выборе темы, попробуйте ещё раз."
        )
        return SELECT_THEME


async def handle_private_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    text = update.message.text

    for chat_id, game in manager.games.items():
        if game["status"] == "collecting_answers" and user.id in game["players"]:
            if manager.add_answer(chat_id, user.id, text):
                await update.message.reply_text(
                    "✅ Ответ сохранен! Ожидайте начала голосования."
                )
            else:
                await update.message.reply_text("❌ Вы уже отправили ответ!")
            break
    else:
        await update.message.reply_text("ℹ️ Сейчас нет активных игр, где вы участвуете.")

    return COLLECT_ANSWERS


async def end_answers_phase(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    game = manager.games.get(chat_id)

    if not game or game["status"] != "collecting_answers":
        return

    manager.start_voting(chat_id)
    options = game["voting_options"]

    answers_text = "\n\n".join(
        [f"🔹 Ответ {i+1}: {ans}" for i, ans in enumerate(options)]
    )

    await context.bot.send_message(
        chat_id,
        f"🕒 Время вышло! Все ответы:\n\n{answers_text}\n\n"
        "❓ **Голосуйте за вариант, который по вашему мнению сгенерировала нейросеть!**",
        parse_mode="Markdown",
    )

    keyboard = [
        [InlineKeyboardButton(f"Вариант {i+1}", callback_data=f"vote_{i}")]
        for i in range(len(options))
    ]

    for user_id in game["players"]:
        try:
            await context.bot.send_message(
                user_id,
                "🗳️ **Выберите ответ нейросети:**",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить клавиатуру пользователю {user_id}: {e}")

    context.job_queue.run_once(end_voting_phase, TIMEOUT, chat_id)


async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    data = query.data

    try:
        option_idx = int(data.split("_")[1])
        for chat_id, game in manager.games.items():
            if game["status"] == "voting" and user.id in game["players"]:
                if manager.add_vote(chat_id, user.id, option_idx):
                    await query.answer("✅ Ваш голос учтен!")
                else:
                    await query.answer("❌ Вы уже голосовали!")
                break
        else:
            await query.answer("ℹ️ Голосование завершено или вы не участвуете!")
    except Exception:
        await query.answer("❌ Ошибка обработки голоса!")

    return VOTING


async def end_voting_phase(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    game = manager.games.get(chat_id)

    if not game or game["status"] != "voting":
        return

    results_text, ai_answer = manager.get_results(chat_id)

    await context.bot.send_message(
        chat_id,
        f"🏁 **Голосование завершено!**\n\n"
        f"{results_text}\n\n"
        f"🤖 **Ответ нейросети:**\n{ai_answer}\n\n"
        "Игра окончена! Для новой игры используйте /start",
        parse_mode="Markdown",
    )

    manager.end_game(chat_id)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    if chat_id in manager.games:
        manager.end_game(chat_id)
        await update.message.reply_text("❌ Игра отменена!")
    return ConversationHandler.END


# --- Main ---
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не найден!")

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_THEME: [
                CallbackQueryHandler(show_all_themes, pattern="^show_all$"),
                CallbackQueryHandler(start, pattern="^back_to_start$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_theme),
            ],
            COLLECT_ANSWERS: [
                MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_private_answer)
            ],
            VOTING: [CallbackQueryHandler(handle_vote, pattern="^vote_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, handle_private_answer))

    # --- Важно: Webhook вместо Polling ---
    port = int(os.environ.get("PORT", 8443))
    app_url = os.getenv("RENDER_EXTERNAL_URL")
    if not app_url:
        raise RuntimeError("RENDER_EXTERNAL_URL не найден!")

    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=BOT_TOKEN,
        webhook_url=f"{app_url}/{BOT_TOKEN}",
    )


if __name__ == "__main__":
    main()
