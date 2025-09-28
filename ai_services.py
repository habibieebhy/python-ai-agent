# ai_services.py
import os
import json
import logging
import asyncio
from typing import Optional, Any, Dict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from dotenv import load_dotenv

# Async FastMCP client
from fastmcp import Client  # pip install fastmcp

load_dotenv()

# -----------------------------
# Config
# -----------------------------
SYSTEM_PROMPT = (
    "You are a helpful and friendly AI assistant. Your name is CemTemChat AI. "
    "Keep your responses concise, friendly, and easy to understand. Do not mention that "
    "you are an AI unless it is directly relevant to the conversation."
)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
YOUR_SITE_URL = os.getenv("YOUR_SITE_URL", "")
YOUR_SITE_NAME = os.getenv("YOUR_SITE_NAME", "")
FASTMCP_URL = os.getenv("FASTMCP_URL", "https://brixta-mycoco-mcp.fastmcp.app/mcp")

# -----------------------------
# Logging
# -----------------------------
logger = logging.getLogger("ai_services")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

def _safe_ascii(obj) -> str:
    try:
        return ascii(obj)
    except Exception:
        try:
            return repr(obj)
        except Exception:
            return "<unrepresentable>"

# -----------------------------
# OpenRouter HTTP client (sync)
# -----------------------------
_session: Optional[requests.Session] = None

def _validate_and_get_key() -> str:
    key = (OPENROUTER_API_KEY or "").strip()
    if not key:
        logger.error("❌ OPENROUTER_API_KEY missing from environment.")
        raise RuntimeError("OPENROUTER_API_KEY missing")
    if any(ord(ch) > 127 for ch in key):
        logger.error("❌ OPENROUTER_API_KEY contains non-ASCII characters. Fix your .env.")
        raise RuntimeError("OPENROUTER_API_KEY contains non-ASCII characters")
    return key

def _build_session() -> requests.Session:
    s = requests.Session()

    # Robust retry policy
    retry = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=50)
    s.mount("https://", adapter)
    s.mount("http://", adapter)

    # Headers - These match the documentation's requirements
    s.headers.update({
        "Authorization": f"Bearer {_validate_and_get_key()}",
        "HTTP-Referer": YOUR_SITE_URL,
        "X-Title": YOUR_SITE_NAME,
    })
    return s

def setup_ai_service() -> Dict[str, Any]:
    global _session
    if _session is None:
        _session = _build_session()
        logger.info("✅ HTTP session initialized for OpenRouter (base: %s)", OPENROUTER_BASE_URL)
    else:
        logger.info("✅ AI service already initialized.")
    return {"session": _session, "base_url": OPENROUTER_BASE_URL}

def get_ai_completion(user_message: str) -> Optional[str]:
    global _session
    if _session is None:
        raise RuntimeError("AI service not initialized. Call setup_ai_service() first.")

    logger.info('🤖 Sending request to OpenRouter for: "%s"', _safe_ascii(user_message))

    # This payload structure exactly matches the documentation's data field
    payload = {
        "model": "deepseek/deepseek-chat-v3.1:free",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_message},
        ],
    }

    try:
        # This POST request goes to the correct URL and sends the payload as JSON
        resp = _session.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            json=payload,  # This correctly sends the data as JSON with the right header
            timeout=20,
        )
        resp.encoding = "utf-8"
        resp.raise_for_status()

        data = resp.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            logger.error("💥 Unexpected response structure. body: %s", _safe_ascii(resp.text))
            raise ValueError("Missing 'choices' in AI response")

        content = choices[0].get("message", {}).get("content")
        if content is None:
            logger.error("💥 Choice missing 'content'. body: %s", _safe_ascii(resp.text))
            raise ValueError("AI response 'content' missing")

        logger.info("✅ AI Response Received.")
        return content

    except requests.RequestException as e:
        logger.error("💥 HTTP error: %s", _safe_ascii(e))
        if 'resp' in locals() and getattr(resp, "text", None):
            logger.error("    body: %s", _safe_ascii(resp.text))
        raise
    except (ValueError, KeyError, IndexError) as e:
        logger.error("💥 Parse error: %s", _safe_ascii(e))
        if 'resp' in locals() and getattr(resp, "text", None):
            logger.error("    body: %s", _safe_ascii(resp.text))
        raise

# Async-friendly wrapper so you can use the sync AI inside async code
async def ask_ai_async(user_message: str) -> Optional[str]:
    return await asyncio.to_thread(get_ai_completion, user_message)

# -----------------------------
# FastMCP client (async)
# -----------------------------
_mcp_client: Optional[Client] = None
_mcp_lock = asyncio.Lock()

async def setup_mcp_client(mcp_url: Optional[str] = None) -> Client:
    global _mcp_client
    url = mcp_url or FASTMCP_URL

    async with _mcp_lock:
        if _mcp_client is not None:
            return _mcp_client
        client = Client(url)
        await client.__aenter__()
        _mcp_client = client
        logger.info("✅ Connected to FastMCP: %s", url)
        return _mcp_client

async def close_mcp_client():
    global _mcp_client
    async with _mcp_lock:
        if _mcp_client is not None:
            try:
                await _mcp_client.__aexit__(None, None, None)
            finally:
                _mcp_client = None
                logger.info("🛑 FastMCP client closed")

def _ensure_mcp() -> Client:
    if _mcp_client is None:
        raise RuntimeError("FastMCP client not initialized. Call setup_mcp_client() first.")
    return _mcp_client

async def mcp_ping() -> Any:
    return await _ensure_mcp().ping()

async def mcp_list_tools() -> Any:
    return await _ensure_mcp().list_tools()

async def mcp_list_resources() -> Any:
    return await _ensure_mcp().list_resources()

async def mcp_list_prompts() -> Any:
    return await _ensure_mcp().list_prompts()

async def mcp_call_tool(tool_name: str, params: Dict[str, Any]) -> Any:
    return await _ensure_mcp().call_tool(tool_name, params)