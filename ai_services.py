# ai_services.py
import os
import json
import logging
import asyncio
from typing import Optional, Any, Dict, List
# import requests # COMMENTED: Not needed for native OpenAI SDK
# from requests.adapters import HTTPAdapter # COMMENTED: Not needed for native OpenAI SDK
# from urllib3.util.retry import Retry # COMMENTED: Not needed for native OpenAI SDK
from dotenv import load_dotenv

from openai import OpenAI 

from fastmcp import Client
from ai_prompt_helper import get_system_prompt # prompt helper function

load_dotenv()

SYSTEM_PROMPT = get_system_prompt() # use the imported Prompt

# --- OLD OPENROUTER CONFIG ---
# OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
# OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") # Use OPENAI_API_KEY instead
# YOUR_SITE_URL = os.getenv("YOUR_SITE_URL", "")
# YOUR_SITE_NAME = os.getenv("YOUR_SITE_NAME", "")
# ---------------------------------------------

# --- OPENAI CONFIG ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # Read native key
_openai_client: Optional[OpenAI] = None # New global client instance
# -------------------------

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

# --- OLD REQUESTS/OPENROUTER GLOBALS/HELPERS ---
# _session: Optional[requests.Session] = None 

# def _validate_and_get_key() -> str:
#     key = (OPENROUTER_API_KEY or "").strip()
#     if not key: raise RuntimeError("OPENROUTER_API_KEY missing")
#     if any(ord(ch) > 127 for ch in key): raise RuntimeError("OPENROUTER_API_KEY contains non-ASCII characters")
#     return key

# def _build_session() -> requests.Session:
#     s = requests.Session()
#     retry = Retry(total=4, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset(["GET", "POST"]), raise_on_status=False)
#     adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=50)
#     s.mount("https://", adapter)
#     s.mount("http://", adapter)
#     s.headers.update({"Authorization": f"Bearer {_validate_and_get_key()}", "HTTP-Referer": YOUR_SITE_URL, "X-Title": YOUR_SITE_NAME})
#     return s
# ------------------------------------------------------------------

# --- OPENAI CLIENT SETUP ---

def _ensure_openai_client() -> OpenAI:
    """Helper to ensure the client is initialized before use."""
    if _openai_client is None: raise RuntimeError("OpenAI client not initialized. Call setup_ai_service() first.")
    return _openai_client

def setup_ai_service():
    """Initializes the OpenAI API client."""
    global _openai_client
    
    if _openai_client is not None:
        logger.info("✅ OpenAI service already initialized.")
        return

    # New OpenAI Client setup
    key = (OPENAI_API_KEY or os.getenv("OPENAI_API_KEY") or "").strip()
    if not key: 
        logger.error("FATAL: OPENAI_API_KEY is not set.")
        return

    _openai_client = OpenAI(api_key=key)
    logger.info("✅ OpenAI Client initialized")

# --- UPDATED COMPLETION FUNCTION ---

def get_ai_completion(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    client = _ensure_openai_client()
    model = "gpt-5-nano" # THE CHATGPT MODEL
    
    logger.info(f'🤖 Sending request to OpenAI Agent ({model})...')
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            # Only send tools if the list is not empty
            tools=tools if tools else None, 
            tool_choice="auto" if tools else "none"
        )
    except Exception as e:
        logger.error(f"💥 OpenAI API Error: {e}")
        return None

    # Parse and structure the response to match the expected dict format 
    # (compatible with the original chat_service.py parsing)
    ai_msg = response.choices[0].message
    
    tool_calls_list = []
    if ai_msg.tool_calls:
        for tc in ai_msg.tool_calls:
            # Reconstruct the tool_calls structure expected by the rest of the app
            tool_calls_list.append({
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    # tc.function.arguments is already a string of JSON
                    "arguments": tc.function.arguments, 
                }
            })
            
    # The return format must match the original: a dict with 'role', 'content', and 'tool_calls'
    result_message = {
        "role": ai_msg.role,
        "content": ai_msg.content, # This will be None if a tool call is made
        "tool_calls": tool_calls_list
    }
    
    logger.info("✅ AI Response Received.")
    return result_message
    
# --- MCP CLIENT FUNCTIONS (Unchanged and Correct) ---

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
            # This logic is correct for converting MCP schemas to OpenAI's tool format
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