# flask_socket_server.py
import os
from flask import Flask, request
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv

from ai_services import SYSTEM_PROMPT, setup_ai_service
from chat_service import ChatService

load_dotenv()

app = Flask(__name__)

_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("SOCKETIO_CORS", "").split(",") if o.strip()]
if not _ALLOWED_ORIGINS:
    raise RuntimeError("SOCKETIO_CORS is empty. Set it to http://localhost:3000 for dev.")

print(f"🔐 CORS allowed origins: {_ALLOWED_ORIGINS}")

socketio = SocketIO(
    app,
    cors_allowed_origins=_ALLOWED_ORIGINS,
    ping_interval=25,
    ping_timeout=60,
)

# Core brain shared here too
chat_service = ChatService()

# Per-connection ephemeral state: sid -> dict(user_state)
CLIENT_STATES: dict[str, dict] = {}

# Tools cache injected from telegram_bot at startup
TOOLS_CACHE: list[dict] = []
def set_tools_cache(tools: list[dict]):
    global TOOLS_CACHE
    TOOLS_CACHE = tools or []

# Ensure OpenRouter HTTP session is ready
setup_ai_service()

@app.route("/")
def health():
    return {"ok": True, "service": "socketio", "origins": _ALLOWED_ORIGINS}, 200

@socketio.on("connect")
def on_connect():
    print(f"✅ client connected sid={request.sid}")
    CLIENT_STATES[request.sid] = {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
        "mcp_tools": TOOLS_CACHE,
    }
    emit("ready", {"ok": True}, to=request.sid)

@socketio.on("disconnect")
def on_disconnect():
    print(f"⛔ client disconnected sid={request.sid}")
    CLIENT_STATES.pop(request.sid, None)

@socketio.on("send_message")
def on_send_message(data):
    text = (data or {}).get("text", "")
    if not isinstance(text, str) or not text.strip():
        emit("error", {"message": "empty text"}, to=request.sid)
        return

    sid = request.sid
    print(f"📩 recv send_message sid={sid} data={data!r}")
    emit("status", {"typing": True}, to=sid)

    def _work():
        import asyncio
        try:
            user_state = CLIENT_STATES.setdefault(
                sid,
                {"messages":[{"role":"system","content":SYSTEM_PROMPT}], "mcp_tools": TOOLS_CACHE}
            )
            display_text, awaiting = asyncio.run(chat_service.handle(user_state, text.strip()))
            print(f"🤖 done handle sid={sid}, awaiting={awaiting}")
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("message", {"text": display_text, "awaiting": awaiting}, to=sid)
        except Exception as e:
            print(f"💥 worker error sid={sid}: {e}")
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("error", {"message": f"server error: {e}"}, to=sid)

    socketio.start_background_task(_work)

@socketio.on("confirm_post")
def on_confirm_post():
    sid = request.sid
    emit("status", {"typing": True}, to=sid)

    def _work():
        import asyncio
        try:
            user_state = CLIENT_STATES.setdefault(
                sid,
                {"messages":[{"role":"system","content":SYSTEM_PROMPT}], "mcp_tools": TOOLS_CACHE}
            )
            response_text = asyncio.run(chat_service.confirm_post(user_state))
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("message", {"text": response_text}, to=sid)
        except Exception as e:
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("error", {"message": f"server error: {e}"}, to=sid)

    socketio.start_background_task(_work)

# Guard to prevent double-starts if imported twice
_SERVER_STARTED = False

def start_socketio_server():
    global _SERVER_STARTED
    if _SERVER_STARTED:
        print("ℹ️ Socket.IO server already started; skipping duplicate start.")
        return
    _SERVER_STARTED = True
    port = int(os.getenv("PORT", "5055"))
    host = "0.0.0.0"
    print(f"🌐 Socket.IO binding on {host}:{port} (origins={_ALLOWED_ORIGINS})")
    # Critical inside thread: disable reloader
    socketio.run(app, host=host, port=port, use_reloader=False)
