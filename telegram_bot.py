# telegram_bot.py (Updated)

import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ChatAction

# Import the functions from your ai_services.py file
from ai_services import setup_ai_service, get_ai_completion

# --- Telegram Message Handlers ---

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command by sending a static welcome message.
    """
    await update.message.reply_text(
        'Hello! I am an AI assistant powered by OpenRouter. Ask me anything.'
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    This handler processes all incoming text messages.
    """
    message = update.message
    chat_id = message.chat_id
    text = message.text

    if not text:
        return

    print(f'🧠 Processing AI request for chat {chat_id}: "{text}"')
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        # 👇 CHANGE: The 'await' keyword is removed from this line
        ai_reply = get_ai_completion(text)

        if ai_reply:
            await message.reply_text(ai_reply)
        else:
            await message.reply_text("Sorry, I couldn't come up with a response.")

    except Exception as error:
        print(f"💥 Failed to get AI response for chat {chat_id}: {error}")
        await message.reply_text(
            "Sorry, I'm having trouble connecting to my brain right now. Please try again later."
        )

# --- Main Application Logic ---

def main():
    """
    This function initializes and runs the entire bot.
    """
    print("🚀 Starting bot...")
    load_dotenv()
    setup_ai_service()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("FATAL ERROR: TELEGRAM_BOT_TOKEN is not set in your .env file.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_command_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print(f"✅ Telegram Bot is polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()