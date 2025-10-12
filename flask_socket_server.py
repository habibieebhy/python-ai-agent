# flask_socket_server.py
import os
from flask import Flask, request
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
import asyncio
import threading
from queue import Queue
import traceback

from ai_services import SYSTEM_PROMPT, setup_ai_service
from chat_service import ChatService
from web_telegram_forward import send_message_to_telegram
from cachetools import TTLCache

load_dotenv()

app = Flask(__name__)

_ALLOWED_ORIGINS = [o.strip() for o in os.getenv("SOCKETIO_CORS", "").split(",") if o.strip()]
if not _ALLOWED_ORIGINS:
    raise RuntimeError("SOCKETIO_CORS is empty. Set it to http://localhost:3000 for dev.")

print(f"🔐 CORS allowed origins: {_ALLOWED_ORIGINS}")

TG_TO_WEB_MAP = TTLCache(maxsize=5000, ttl=60 * 60)  # keep mappings for 1 hour; adjust as needed
ALLOWED_FORWARD_TARGETS = [s.strip() for s in os.getenv("ALLOWED_FORWARD_TARGETS", "").split(",") if s.strip()]
# Example env: ALLOWED_FORWARD_TARGETS="123456789,987654321" OR leave empty to use HUMANS only
DEFAULT_HUMAN_CHAT_ID = os.getenv("HUMAN_CHAT_ID")  # required fallback in production ideally
WEB_CLIENT_REGISTRY: dict[str, str] = {}
MAP_LOCK = threading.Lock()

socketio = SocketIO(
    app,
    cors_allowed_origins=_ALLOWED_ORIGINS,
    ping_interval=25,
    ping_timeout=60,
    async_mode="eventlet",   # eventlet for production (handles multiple clients); threading for local testing
    path="/socket.io"
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

def _run_coro_in_fresh_loop(coro):
    """
    Run a coroutine in a brand-new asyncio event loop that lives ONLY
    inside this OS thread. No cross-talk, no nested-loop drama.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()

def _run_async_in_thread(coro):
    """
    Execute an async coroutine in a dedicated OS thread that owns its own event loop.
    Blocks until the result is ready; returns value or raises exception.
    """
    q: Queue = Queue(maxsize=1)

    def _runner():
        try:
            result = _run_coro_in_fresh_loop(coro)
            q.put((True, result))
        except BaseException as e:
            q.put((False, e))

    t = threading.Thread(target=_runner, daemon=True, name="ai-coro-worker")
    t.start()
    ok, payload = q.get()  # blocks until done
    if ok:
        return payload
    raise payload

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
        try:
            user_state = CLIENT_STATES.setdefault(
                sid,
                {"messages":[{"role":"system","content":SYSTEM_PROMPT}], "mcp_tools": TOOLS_CACHE}
            )
            display_text, awaiting = _run_async_in_thread(
                chat_service.handle(user_state, text.strip())
            )
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("bot_message", {"text": display_text, "awaiting": awaiting}, to=sid)
        except Exception as e:
            print(f"💥 worker error sid={sid}: {e}\n{traceback.format_exc()}")
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("server_error", {"message": f"server error: {e}"}, to=sid)

    socketio.start_background_task(_work)

@socketio.on("confirm_post")
def on_confirm_post():
    sid = request.sid
    emit("status", {"typing": True}, to=sid)

    def _work():
        try:
            user_state = CLIENT_STATES.setdefault(
                sid,
                {"messages":[{"role":"system","content":SYSTEM_PROMPT}], "mcp_tools": TOOLS_CACHE}
            )
            response_text = _run_async_in_thread(
                chat_service.confirm_post(user_state)
            )
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("bot_message", {"text": response_text}, to=sid)
        except Exception as e:
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("server_error", {"message": f"server error: {e}"}, to=sid)

    socketio.start_background_task(_work)

# for web/app to telegram bot/user and back chatting (NO AI USED HERE)
@socketio.on("register_forward_target")
def on_register_forward_target(data):
    client_id = (data or {}).get("client_id")
    if not client_id:
        emit("server_error", {"message": "missing client_id"}, to=request.sid)
        return
    WEB_CLIENT_REGISTRY[client_id] = request.sid
    emit("register_ack", {"client_id": client_id}, to=request.sid)

@socketio.on("unregister_forward_target")
def on_unregister_forward_target(data):
    cid = (data or {}).get("client_id")
    if cid and cid in WEB_CLIENT_REGISTRY:
        WEB_CLIENT_REGISTRY.pop(cid, None)
    emit("unregister_ack", {"client_id": cid}, to=request.sid)

@socketio.on("forward_to_telegram")
def on_forward_to_telegram(data):
    """
    data: {
      text: str,
      target_chat_id?: int|string,      # optional override
      client_id?: string,               # required to route replies back
      reply_to_tg_msg_id?: int|null     # optional to reply to existing TG msg
    }
    """
    sid = request.sid
    text = (data or {}).get("text", "")
    client_id = (data or {}).get("client_id")
    target = (data or {}).get("target_chat_id") or DEFAULT_HUMAN_CHAT_ID
    reply_to_tg_msg_id = (data or {}).get("reply_to_tg_msg_id")

    if not text or not target or not client_id:
        emit("server_error", {"message": "missing text/target/client_id"}, to=sid)
        return

    # security allowlist check (if configured)
    if ALLOWED_FORWARD_TARGETS and str(target) not in ALLOWED_FORWARD_TARGETS:
        emit("server_error", {"message": "target not allowed"}, to=sid)
        return

    emit("forward_ack", {"status": "queued", "snippet": text[:200]}, to=sid)
    emit("status", {"typing": True}, to=sid)

    def _work():
        try:
            # send to telegram and get message dict
            tg_msg = send_message_to_telegram(target, text, reply_to_message_id=reply_to_tg_msg_id)
            tg_mid = int(tg_msg.get("message_id"))

            # store mapping so replies in Telegram referencing this message route back
            with MAP_LOCK:
                TG_TO_WEB_MAP[tg_mid] = {"client_id": client_id, "sid": sid}

            # respond back to web client as success ack
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("bot_message", {
                "text": "Thanks — order received and forwarded to the human. Telegram message id saved.",
                "meta": {"telegram_message_id": tg_mid}
            }, to=sid)
        except Exception as e:
            socketio.emit("status", {"typing": False}, to=sid)
            socketio.emit("server_error", {"message": f"failed to forward: {e}"}, to=sid)

    socketio.start_background_task(_work)

@socketio.on("disconnect")
def on_disconnect():
    print(f"⛔ client disconnected sid={request.sid}")
    # remove any client_id -> sid in registry
    to_remove = [cid for cid, s in WEB_CLIENT_REGISTRY.items() if s == request.sid]
    for cid in to_remove:
        WEB_CLIENT_REGISTRY.pop(cid, None)
    # optional: leave TG_TO_WEB_MAP alone — TTL will expire
    CLIENT_STATES.pop(request.sid, None)

# Guard to prevent double-starts if imported twice
_SERVER_STARTED = False

def start_socketio_server():
    global _SERVER_STARTED
    if _SERVER_STARTED:
        print("Socket.IO server already started; skipping duplicate start.")
        return
    _SERVER_STARTED = True
    port = int(os.getenv("PORT", "5055"))
    host = "0.0.0.0"
    print(f"🌐 Socket.IO binding on {host}:{port} (origins={_ALLOWED_ORIGINS})")
    # Dev-only runner; don't use under Gunicorn
    socketio.run(app, host=host, port=port, use_reloader=False)
