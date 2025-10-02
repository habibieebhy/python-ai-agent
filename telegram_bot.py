# telegram_bot.py
import os
import re
import json
import asyncio
import threading
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from ai_services import (
    setup_ai_service,
    get_and_format_mcp_tools,
    close_mcp_client,
    SYSTEM_PROMPT,
    pydantic_json_default,  # still handy for debug prints
)

# Core brain shared by all transports
from chat_service import ChatService

# Socket.IO server starter and tools cache setter
from flask_socket_server import start_socketio_server, set_tools_cache

chat_service = ChatService()

# ---------- Utilities ----------
def _ensure_history_store(context: ContextTypes.DEFAULT_TYPE) -> list[dict]:
    msgs = context.user_data.get("messages")
    if not msgs:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        context.user_data["messages"] = msgs
    return msgs

def _rescue_id(text: str) -> int | None:
    m = re.search(
        r"(?:user|dealer|report|dvr|tvr|sales\s*order|sales|order|id)\s*#?\s*(\d+)|(\d+)\s*$",
        text, re.IGNORECASE
    )
    if not m:
        return None
    try:
        return int(m.group(1) or m.group(2))
    except ValueError:
        return None

# ---------- Handlers ----------
async def start_command_handler(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello. I'm online. Ask me anything.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat_id
    text = message.text or ""
    if not text.strip():
        return

    # Turn-2: if user replied 'Y', try executing stored POST
    if text.strip().upper() == "Y" and context.user_data.get("pending_tool_payload"):
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        response = await chat_service.confirm_post(context.user_data)
        await message.reply_text(response)
        return

    # Normal chat turn
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    # Preload tools into user_state once
    context.user_data.setdefault("mcp_tools", context.bot_data.get("mcp_tools", []))
    _ensure_history_store(context)

    # Optional host-side ID rescue
    rescued = _rescue_id(text)
    if rescued is not None:
        text = f"{text} [Host System Note: Relevant ID rescued from user text: {rescued}]"

    # Ask the core to handle the message
    display_text, awaiting_confirmation = await chat_service.handle(context.user_data, text)

    # Telegram just shows the cleaned text. If awaiting_confirmation == True,
    # the user can reply 'Y' next message to execute the stored POST.
    await message.reply_text(display_text)

async def post_init_setup(app: Application):
    # Fetch MCP tools once and cache in bot_data
    tools = await get_and_format_mcp_tools()
    app.bot_data["mcp_tools"] = tools
    # Share tools with Socket.IO adapter too
    set_tools_cache(tools)

# ---------- Public entrypoint for run.py ----------
def start_telegram_bot():
    """
    Start the Telegram bot in the CURRENT THREAD.
    Intended to be called by run.py, while the web server runs on the main thread.
    """
    print("🤖 Booting Telegram bot worker...")
    load_dotenv()

    # Prepare OpenRouter HTTP session once
    setup_ai_service()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("FATAL: TELEGRAM_BOT_TOKEN is not set.")

    # Create and set an explicit event loop to silence the deprecation warning
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app_builder = Application.builder().token(token)
    app_builder.post_init(post_init_setup)
    app = app_builder.build()

    app.add_handler(CommandHandler("start", start_command_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("✅ Telegram Bot is polling for messages...")
    try:
        
        app.run_polling(stop_signals=None)
    finally:
        # Clean shutdown of MCP client
        try:
            loop.run_until_complete(close_mcp_client())
        except Exception:
            pass
        # Don't print scary "Shutdown complete" lines on every redeploy/restart

# ---------- Legacy standalone mode (optional for local dev) ----------
if __name__ == "__main__":
    # Standalone: you can still run this file directly for local testing.
    start_telegram_bot()