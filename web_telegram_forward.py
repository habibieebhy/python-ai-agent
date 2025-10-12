# web_telegram_forward.py
from telegram import Bot
import os
from dotenv import load_dotenv

load_dotenv()

SALES_ORDER_BOT_TOKEN = os.getenv("SALES_ORDER_BOT_TOKEN")
if not SALES_ORDER_BOT_TOKEN:
    raise RuntimeError("SALES_ORDER_BOT_TOKEN not set")

_bot = Bot(token=SALES_ORDER_BOT_TOKEN)

def send_message_to_telegram(chat_id: int | str, text: str, reply_to_message_id: int | None = None) -> dict:
    """
    Sends text to `chat_id`. Returns the telegram message dict (including message_id).
    reply_to_message_id: optional to make the message a reply in Telegram.
    """
    if not text or not text.strip():
        raise ValueError("empty text")
    text = text.strip()[:4000]  # safe guard

    msg = _bot.send_message(chat_id=chat_id, text=text, reply_to_message_id=reply_to_message_id)
    return msg.to_dict()
