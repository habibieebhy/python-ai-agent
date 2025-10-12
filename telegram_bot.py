# telegram_bot.py
import os
import re
import json
import asyncio
import threading
from dotenv import load_dotenv

from telegram import Update, Bot
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

try:
    from flask_socket_server import set_tools_cache, socketio as socketio_server
except Exception:
    # keep the file import-safe if you run telegram_bot.py by itself
    socketio_server = None
    def set_tools_cache(_): pass

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

# NO AI sales order helper
async def send_message_to_telegram(chat_id: int | str, text: str, token: str | None = None):
    """
    Utility to send a plain message to a telegram chat id.
    Useful for web -> telegram forwards. Non-blocking wrapper.
    """
    tkn = token or os.getenv("SALES_ORDER_BOT_TOKEN")
    if not tkn:
        print("send_message_to_telegram: no token available")
        return False
    try:
        bot = Bot(token=tkn)
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as e:
        print(f"send_message_to_telegram: failed to send to {chat_id}: {e}")
        return False

# ---------- Handlers ----------
async def start_command_handler(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello. I'm online. Ask me anything.")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = message.chat_id
    text = message.text or ""
    if not text.strip():
        return
    
    # NO AI section here ---------------------------------------
    # Emit to web clients that a human/telegram bot has sent something
    payload = {
        "from_chat_id": chat_id,
        "from_name": (message.from_user.full_name if message.from_user else str(chat_id)),
        "text": text,
        "timestamp": message.date.isoformat() if message.date else None,
    }
    try:
        if socketio_server:
            socketio_server.emit("human_message", payload)
        else:
            # defensive: don't fail if socketio wasn't importable
            print("socketio_server not available; skipping human_message emit")
    except Exception as e:
        print("failed to emit human_message to socketio:", e)
    # NO AI section ends here ---------------------------------------------

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