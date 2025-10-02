# run.py -> main runner for production deployments like Render
import threading
import os
from flask_socket_server import start_socketio_server
from telegram_bot import start_telegram_bot

def main():
    # Start Telegram in a background thread
    t = threading.Thread(target=start_telegram_bot, daemon=True)
    t.start()

    # Run the web server in the main thread (Render expects this)
    start_socketio_server()

if __name__ == "__main__":
    main()
