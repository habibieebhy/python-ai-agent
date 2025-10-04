# ai_services.py
import os
import json
import logging
import asyncio
from typing import Optional, Any, Dict, List
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from fastmcp import Client
from ai_prompt_helper import get_system_prompt # prompt helper function

load_dotenv()

SYSTEM_PROMPT = get_system_prompt() # use the imported Prompt

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
YOUR_SITE_URL = os.getenv("YOUR_SITE_URL", "")
YOUR_SITE_NAME = os.getenv("YOUR_SITE_NAME", "")
FASTMCP_URL = os.getenv("FASTMCP_URL", "https://brixta-mycoco-mcp.fastmcp.app/mcp")
logger = logging.getLogger("ai_services")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

# --- Custom JSON Serializer for Pydantic/FastMCP Objects ---
def pydantic_json_default(obj):
    """Converts a Pydantic object or custom class instance to a serializable dictionary or string."""
    if hasattr(obj, 'model_dump'):
        # Pydantic V2 serialization
        return obj.model_dump()
    if hasattr(obj, 'dict'):
        # Pydantic V1 serialization (fallback)
        return obj.dict()
    
    # CRITICAL FALLBACK: If it's still a non-basic object, convert it to a string.
    # This prevents the TypeError from crashing the program loop.
    if not isinstance(obj, (dict, list, str, int, float, bool, type(None))):
         return str(obj) 
    
    # If all else fails, raise the original error for standard json types
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def _safe_ascii(obj) -> str:
    try: return ascii(obj)
    except Exception:
        try: return repr(obj)
        except Exception: return "<unrepresentable>"
_session: Optional[requests.Session] = None

def _validate_and_get_key() -> str:
    key = (OPENROUTER_API_KEY or "").strip()
    if not key: raise RuntimeError("OPENROUTER_API_KEY missing")
    if any(ord(ch) > 127 for ch in key): raise RuntimeError("OPENROUTER_API_KEY contains non-ASCII characters")
    return key

def _build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET", "POST"]), raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=50)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"Authorization": f"Bearer {_validate_and_get_key()}", "HTTP-Referer": YOUR_SITE_URL, "X-Title": YOUR_SITE_NAME})
    return s

def setup_ai_service() -> Dict[str, Any]:
    global _session
    if _session is None:
        _session = _build_session()
        logger.info("✅ HTTP session initialized for OpenRouter (base: %s)", OPENROUTER_BASE_URL)
    else: logger.info("✅ AI service already initialized.")
    return {"session": _session, "base_url": OPENROUTER_BASE_URL}

def get_ai_completion(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    global _session
    if _session is None: raise RuntimeError("AI service not initialized. Call setup_ai_service() first.")
    logger.info('🤖 Sending request to OpenRouter Agent...')
    payload = {"model": "deepseek/deepseek-chat-v3.1:free", "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        resp = _session.post(f"{OPENROUTER_BASE_URL}/chat/completions", json=payload, timeout=30)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list): raise ValueError("Missing 'choices' in AI response")
        message = choices[0].get("message")
        if message is None: raise ValueError("AI response 'message' missing")
        logger.info("✅ AI Response Received.")
        return message
    except requests.RequestException as e:
        logger.error("💥 HTTP error: %s", _safe_ascii(e))
        if 'resp' in locals() and getattr(resp, "text", None): logger.error("    body: %s", _safe_ascii(resp.text))
        raise
    except (ValueError, KeyError, IndexError) as e:
        logger.error("💥 Parse error: %s", _safe_ascii(e))
        if 'resp' in locals() and getattr(resp, "text", None): logger.error("    body: %s", _safe_ascii(resp.text))
        raise
    
_mcp_client: Optional[Client] = None
_mcp_lock = asyncio.Lock()

async def setup_mcp_client(mcp_url: Optional[str] = None) -> Client:
    global _mcp_client
    url = mcp_url or FASTMCP_URL
    async with _mcp_lock:
        if _mcp_client is not None: return _mcp_client
        client = Client(url)
        await client.__aenter__()
        _mcp_client = client
        logger.info("✅ Connected to FastMCP: %s", url)
        return client
async def close_mcp_client():
    global _mcp_client
    async with _mcp_lock:
        if _mcp_client is not None:
            try: await _mcp_client.__aexit__(None, None, None)
            finally:
                _mcp_client = None
                logger.info("🛑 FastMCP client closed")

def _ensure_mcp() -> Client:
    if _mcp_client is None: raise RuntimeError("FastMCP client not initialized. Call setup_mcp_client() first.")
    return _mcp_client

async def mcp_ping() -> Any: return await _ensure_mcp().ping()
async def mcp_list_tools() -> Any: return await _ensure_mcp().list_tools()
async def mcp_list_resources() -> Any: return await _ensure_mcp().list_resources()
async def mcp_list_prompts() -> Any: return await _ensure_mcp().list_prompts()
async def mcp_call_tool(tool_name: str, params: Dict[str, Any]) -> Any: return await _ensure_mcp().call_tool(tool_name, params)

async def get_and_format_mcp_tools() -> List[Dict[str, Any]]:
    logger.info("🛠️ Fetching and formatting tools from MCP server...")
    try:
        mcp_client = await setup_mcp_client()
        mcp_tools = await mcp_client.list_tools()
        formatted_tools = []
        for tool in mcp_tools:
            formatted_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.model_json_schema(),
                }
            })
        logger.info(f"✅ Found and formatted {len(formatted_tools)} tools.")
        return formatted_tools
    except Exception as e:
        logger.error(f"💥 Failed to fetch tools from MCP: {e}")
        return []