# run.py
import threading
from flask_socket_server import app, socketio
from telegram_bot import start_telegram_bot

# Start Telegram immediately on import (so Gunicorn workers launch it)
t = threading.Thread(target=start_telegram_bot, daemon=True)
t.start()

# Gunicorn entrypoint
application = app

# For local dev only:
if __name__ == "__main__":
    from flask_socket_server import start_socketio_server
    start_socketio_server()
