# telegram_bot.py (Final Correction)
import os
import json
import asyncio
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

from ai_services import (
    setup_ai_service,
    get_ai_completion,
    get_and_format_mcp_tools,
    close_mcp_client,
    mcp_call_tool,
    SYSTEM_PROMPT,
)

async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Hello! I am an AI assistant powered by OpenRouter. I can now use tools to help you. Ask me anything.'
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat_id
    text = message.text

    if not text:
        return

    print(f'🧠 Processing agent request for chat {chat_id}: "{text}"')
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        
        tools = context.bot_data.get('mcp_tools', [])

        while True:
            ai_response_message = await asyncio.to_thread(get_ai_completion, messages, tools)
            
            if not ai_response_message:
                raise ValueError("Failed to get a response from the AI.")

            messages.append(ai_response_message)
            tool_calls = ai_response_message.get("tool_calls")

            if not tool_calls:
                break

            for tool_call in tool_calls:
                function_name = tool_call['function']['name']
                try:
                    function_args = json.loads(tool_call['function']['arguments'])
                    print(f"  -> Calling tool: {function_name} with args {function_args}")
                    
                    tool_result = await mcp_call_tool(function_name, function_args)
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "content": json.dumps(tool_result),
                    })
                except Exception as e:
                    print(f"  -> Tool call failed: {e}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call['id'],
                        "content": f"Error executing tool {function_name}: {e}",
                    })
        
        final_answer = messages[-1].get('content')

        if final_answer:
            await message.reply_text(final_answer)
        else:
            await message.reply_text("Sorry, I couldn't come up with a response.")

    except Exception as error:
        print(f"💥 Failed to get AI response for chat {chat_id}: {error}")
        await message.reply_text(
            "Sorry, I'm having trouble connecting to my brain right now. Please try again later."
        )

# FIX: Create a proper async function for post_init
async def post_init_setup(app: Application):
    """
    This function runs once after the bot is initialized.
    It fetches the tools and stores them in the bot's data context.
    """
    app.bot_data['mcp_tools'] = await get_and_format_mcp_tools()

def main():
    print("🚀 Starting agent bot...")
    load_dotenv()
    
    setup_ai_service()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("FATAL ERROR: TELEGRAM_BOT_TOKEN is not set in your .env file.")

    app_builder = Application.builder().token(token)
    
    # FIX: Pass the new async setup function to post_init
    app_builder.post_init(post_init_setup)
    
    app = app_builder.build()

    app.add_handler(CommandHandler("start", start_command_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    try:
        print(f"✅ Telegram Bot is polling for messages...")
        app.run_polling()
    finally:
        print("🛑 Shutting down. Closing MCP client...")
        asyncio.run(close_mcp_client())

if __name__ == "__main__":
    main()